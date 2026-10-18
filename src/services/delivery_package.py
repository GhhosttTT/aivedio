"""Build reproducible delivery packages for approved productions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import re


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
            archive_names = archive.namelist()
            names = set(archive_names)
            manifest_name = "metadata/delivery_manifest.json"
            if manifest_name not in names:
                result["errors"].append("Embedded delivery manifest is missing")
                return result
            if len(archive_names) != len(names):
                result["errors"].append("ZIP contains duplicate archive entries")
            manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
            if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
                result["errors"].append("Embedded delivery manifest is invalid")
                return result
            result["manifest_schema_version"] = manifest.get("schema_version")
            listed_names: set[str] = set()
            for item in manifest["files"]:
                archive_name = item.get("path") if isinstance(item, dict) else None
                archive_path = Path(archive_name) if isinstance(archive_name, str) else None
                if not archive_path or archive_path.is_absolute() or ".." in archive_path.parts:
                    result["errors"].append(f"Unsafe manifest path: {archive_name!r}")
                    continue
                if archive_name in listed_names:
                    result["errors"].append(f"Duplicate manifest path: {archive_name}")
                    continue
                listed_names.add(archive_name)
                if archive_name not in names:
                    result["errors"].append(f"Manifest file is missing from ZIP: {archive_name}")
                    continue
                payload = archive.read(archive_name)
                if not isinstance(item.get("size"), int) or item.get("size") < 0:
                    result["errors"].append(f"Invalid manifest size: {archive_name}")
                elif item.get("size") != len(payload):
                    result["errors"].append(f"Size mismatch: {archive_name}")
                expected_hash = item.get("sha256")
                if (
                    not isinstance(expected_hash, str)
                    or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash)
                    or expected_hash.lower() != hashlib.sha256(payload).hexdigest()
                ):
                    result["errors"].append(f"SHA-256 mismatch: {archive_name}")
                result["checked_files"] += 1
            unexpected = sorted(names - listed_names - {manifest_name})
            if unexpected:
                result["errors"].append(
                    "ZIP contains files missing from manifest: " + ", ".join(unexpected)
                )
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
        (".generation.json", "reviews/final_generation.json"),
        (".provider.json", "reviews/final_provider.json"),
        (".quality.json", "reviews/final_quality.json"),
    ):
        sidecar = final_path.with_suffix(suffix)
        if sidecar.is_file():
            candidates.append((sidecar, archive_name))

    review_root = project_root / "reviews"
    for report_path in sorted(review_root.glob("*.json")):
        if report_path.is_file():
            candidates.append((report_path, f"reviews/{report_path.name}"))

    # Platform exports are independently decoded and hash-validated before
    # delivery. Include both the encoded asset and its preset manifest so the
    # recipient can reproduce and verify every published variant.
    export_root = project_root / "exports"
    for export_path in sorted(export_root.iterdir()) if export_root.is_dir() else []:
        if export_path.is_file() and export_path.suffix.lower() in {".mp4", ".mov", ".json"}:
            candidates.append((export_path, f"exports/{export_path.name}"))

    scene_subtitles = [
        Path(getattr(scene, "subtitle_path", ""))
        for scene in getattr(project, "scenes", [])
        if getattr(scene, "subtitle_path", None)
    ]
    for subtitle_path in scene_subtitles:
        if subtitle_path.is_file():
            candidates.append((subtitle_path, f"subtitles/scenes/{subtitle_path.name}"))

    # Include the exact scene assets and their generation/review sidecars used
    # to approve the final episode, keeping the exported master auditable.
    for scene in sorted(
        getattr(project, "scenes", []) or [],
        key=lambda item: int(getattr(item, "scene_number", 0) or 0),
    ):
        scene_number = int(getattr(scene, "scene_number", 0) or 0)
        if scene_number <= 0:
            continue
        for kind, value in (
            ("image", getattr(scene, "image_path", None)),
            ("video", getattr(scene, "video_path", None)),
            ("audio", getattr(scene, "audio_path", None)),
            ("subtitle", getattr(scene, "subtitle_path", None)),
        ):
            source = Path(str(value or ""))
            if not source.is_file():
                continue
            candidates.append((
                source,
                f"media/scenes/scene_{scene_number:04d}_{kind}{source.suffix.lower()}",
            ))
            for suffix in (
                ".quality.json", ".final_review.json", ".provider.json",
                ".continuity.json", ".generation.json",
            ):
                sidecar = source.with_suffix(suffix)
                if sidecar.is_file():
                    candidates.append((
                        sidecar,
                        f"reviews/scenes/scene_{scene_number:04d}_{kind}{suffix}",
                    ))

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
    final_path = Path(getattr(project, "final_video_path", None) or "").resolve()
    final_composition = reports.get("final_composition") if isinstance(reports, dict) else None
    manual_approval = (
        isinstance(final_composition, dict)
        and final_composition.get("status") in {"needs_review", "review_unavailable"}
        and isinstance(final_composition.get("human_decision"), dict)
        and final_composition["human_decision"].get("decision") == "approved"
    )
    if (
        not isinstance(final_composition, dict)
        or (final_composition.get("status") != "passed" and not manual_approval)
    ):
        raise DeliveryPackageError("Final composition review is not passed; delivery is blocked")
    if Path(str(final_composition.get("video_path") or "")).resolve() != final_path:
        raise DeliveryPackageError("Final composition review points to a different video")
    if final_composition.get("video_sha256") != _sha256(final_path):
        raise DeliveryPackageError("Final composition review is stale for the current video")
    delivery_root = root / "delivery"
    package_path = delivery_root / "delivery_package.zip"
    manifest_path = delivery_root / "delivery_manifest.json"
    from src.services.cover_generator import CoverGenerationError, generate_cover
    cover_path = delivery_root / "cover.jpg"
    try:
        cover_report = generate_cover(final_path, cover_path)
    except CoverGenerationError as exc:
        raise DeliveryPackageError(str(exc)) from exc
    # Dynamic project audits are part of the signed delivery evidence. Persist
    # them before collecting review files so a package cannot omit the exact
    # continuity/rhythm evidence used by the approval decision.
    for audit_key in ("continuity_audit", "rhythm_audit"):
        audit_report = reports.get(audit_key)
        if isinstance(audit_report, dict):
            _write_json_atomic(root / "reviews" / f"{audit_key}.json", audit_report)
    files = _collect_files(project, root, reports)

    project_metadata = delivery_root / "project_metadata.json"
    topic_brief = {}
    topic_brief_path = root / "topic_brief.json"
    if topic_brief_path.is_file():
        try:
            loaded_brief = json.loads(topic_brief_path.read_text(encoding="utf-8"))
            if isinstance(loaded_brief, dict):
                topic_brief = loaded_brief
        except (OSError, ValueError):
            topic_brief = {}
    _write_json_atomic(project_metadata, {
        "project_id": getattr(project, "id", None),
        "name": getattr(project, "name", ""),
        "theme": getattr(project, "theme", None),
        "outline": getattr(project, "outline", None),
        "script": getattr(project, "script", None),
        "topic_brief": topic_brief,
    })
    files.append((project_metadata, "metadata/project.json"))
    if cover_report.get("status") == "ready":
        files.append((cover_path, "cover/cover.jpg"))
    cover_metadata = delivery_root / "cover_metadata.json"
    _write_json_atomic(cover_metadata, cover_report)
    files.append((cover_metadata, "metadata/cover.json"))

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
        "cover": cover_report,
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
