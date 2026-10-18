"""Build reproducible delivery packages for approved productions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


class DeliveryPackageError(ValueError):
    """Raised when a project cannot be exported as a production package."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def verify_delivery_package(package_path: str | Path) -> dict:
    """Verify a delivery ZIP against its embedded SHA-256 manifest."""
    path = Path(package_path).resolve()
    result = {"status": "failed", "package_path": str(path), "checked_files": 0, "errors": []}
    if not path.is_file():
        result["errors"].append(f"Delivery package is missing: {path}")
        return result
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            manifest_name = "metadata/delivery_manifest.json"
            if manifest_name not in names:
                result["errors"].append("Embedded delivery manifest is missing")
                return result
            manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
            if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
                result["errors"].append("Embedded delivery manifest is invalid")
                return result
            result["manifest_schema_version"] = manifest.get("schema_version")
            for item in manifest["files"]:
                archive_name = item.get("path") if isinstance(item, dict) else None
                archive_path = Path(archive_name) if isinstance(archive_name, str) else None
                if not archive_path or archive_path.is_absolute() or ".." in archive_path.parts:
                    result["errors"].append(f"Unsafe manifest path: {archive_name!r}")
                    continue
                if archive_name not in names:
                    result["errors"].append(f"Manifest file is missing from ZIP: {archive_name}")
                    continue
                payload = archive.read(archive_name)
                if item.get("size") != len(payload):
                    result["errors"].append(f"Size mismatch: {archive_name}")
                if item.get("sha256") != hashlib.sha256(payload).hexdigest():
                    result["errors"].append(f"SHA-256 mismatch: {archive_name}")
                result["checked_files"] += 1
            result["status"] = "passed" if not result["errors"] else "failed"
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        result["errors"].append(f"Cannot verify delivery package: {exc}")
    return result


def _collect_files(project, project_root: Path, reports: dict) -> list[tuple[Path, str]]:
    final_path = Path(getattr(project, "final_video_path", None) or "")
    if not final_path.is_file():
        raise DeliveryPackageError("Final video is missing; generate and approve the project first")

    candidates: list[tuple[Path, str]] = [(final_path, "media/final_video" + final_path.suffix.lower())]
    for suffix, archive_name in (
        (".srt", "subtitles/final.srt"),
        (".ass", "subtitles/final.ass"),
        (".composition_review.json", "reviews/final_composition.json"),
    ):
        sidecar = final_path.with_suffix(suffix)
        if sidecar.is_file():
            candidates.append((sidecar, archive_name))

    review_root = project_root / "reviews"
    for report_path in sorted(review_root.glob("*.json")):
        if report_path.is_file():
            candidates.append((report_path, f"reviews/{report_path.name}"))

    scene_subtitles = [
        Path(getattr(scene, "subtitle_path", ""))
        for scene in getattr(project, "scenes", [])
        if getattr(scene, "subtitle_path", None)
    ]
    for subtitle_path in scene_subtitles:
        if subtitle_path.is_file():
            candidates.append((subtitle_path, f"subtitles/scenes/{subtitle_path.name}"))

    # Preserve deterministic order and avoid duplicate archive names when a
    # report is also discoverable through the final-video sidecar.
    unique: dict[str, tuple[Path, str]] = {}
    for source, archive_name in candidates:
        unique.setdefault(archive_name, (source, archive_name))
    return list(unique.values())


def build_delivery_package(project, project_root: str | Path, reports: dict, review_summary: dict) -> dict:
    """Create a signed manifest and ZIP for a quality-approved project."""
    if not isinstance(review_summary, dict) or review_summary.get("status") != "ready":
        raise DeliveryPackageError("Project quality review is not ready for delivery")

    root = Path(project_root).resolve()
    delivery_root = root / "delivery"
    package_path = delivery_root / "delivery_package.zip"
    manifest_path = delivery_root / "delivery_manifest.json"
    # Dynamic project audits are part of the signed delivery evidence. Persist
    # them before collecting review files so a package cannot omit the exact
    # continuity/rhythm evidence used by the approval decision.
    for audit_key in ("continuity_audit", "rhythm_audit"):
        audit_report = reports.get(audit_key)
        if isinstance(audit_report, dict):
            _write_json_atomic(root / "reviews" / f"{audit_key}.json", audit_report)
    files = _collect_files(project, root, reports)

    project_metadata = delivery_root / "project_metadata.json"
    _write_json_atomic(project_metadata, {
        "project_id": getattr(project, "id", None),
        "name": getattr(project, "name", ""),
        "theme": getattr(project, "theme", None),
        "outline": getattr(project, "outline", None),
        "script": getattr(project, "script", None),
    })
    files.append((project_metadata, "metadata/project.json"))

    manifest_files = []
    for source, archive_name in files:
        manifest_files.append({
            "path": archive_name,
            "size": source.stat().st_size,
            "sha256": _sha256(source),
        })

    report_statuses = {
        name: report.get("status")
        for name, report in reports.items()
        if isinstance(report, dict) and report.get("status")
    }
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": getattr(project, "id", None),
        "project_name": getattr(project, "name", ""),
        "status": "ready",
        "quality_summary": review_summary,
        "report_statuses": report_statuses,
        "files": manifest_files,
        "package_path": str(package_path),
    }
    _write_json_atomic(manifest_path, manifest)

    delivery_root.mkdir(parents=True, exist_ok=True)
    temporary_package = delivery_root / f".{package_path.name}.tmp"
    try:
        with zipfile.ZipFile(temporary_package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source, archive_name in files:
                archive.write(source, archive_name)
            archive.write(manifest_path, "metadata/delivery_manifest.json")
        os.replace(temporary_package, package_path)
    finally:
        temporary_package.unlink(missing_ok=True)

    manifest["manifest_path"] = str(manifest_path)
    verification = verify_delivery_package(package_path)
    if verification.get("status") != "passed":
        raise DeliveryPackageError(
            "Generated delivery package failed verification: "
            + "; ".join(verification.get("errors") or [])
        )
    manifest["verification"] = verification
    return manifest
