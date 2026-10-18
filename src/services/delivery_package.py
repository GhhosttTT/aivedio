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


def _delivery_generation_evidence(reports: dict) -> list[dict]:
    """Keep the provider and spatial hashes visible at the delivery root."""
    evidence = []
    for name, report in (reports or {}).items():
        if not isinstance(report, dict):
            continue
        run = report.get("generation_run_evidence")
        if not isinstance(run, dict):
            continue
        evidence.append({
            "report": name,
            "status": run.get("status"),
            "request_contract_hashes": list(run.get("request_contract_hashes") or []),
            "spatial_scene_contract_hashes": list(run.get("spatial_scene_contract_hashes") or []),
            "spatial_project_signatures": list(run.get("spatial_project_signatures") or []),
            "providers": list(run.get("providers") or []),
            "video_sha256s": list(run.get("video_sha256s") or []),
            "selected_video_sha256": run.get("selected_video_sha256"),
            "accepted_video_sha256": run.get("accepted_video_sha256"),
        })
    return evidence


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
            manifest_entries: dict[str, dict] = {}
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
                if isinstance(item, dict):
                    manifest_entries[archive_name] = item
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
            final_video_entry = next(
                (
                    item for archive_name, item in manifest_entries.items()
                    if archive_name.startswith("media/final_video")
                ),
                None,
            )
            final_archive_name = next(
                (
                    archive_name for archive_name in manifest_entries
                    if archive_name.startswith("media/final_video")
                ),
                None,
            )
            final_review_name = "reviews/final_composition.json"
            if final_review_name not in names:
                result["errors"].append("Final composition review is missing from delivery package")
            elif not isinstance(final_video_entry, dict):
                result["errors"].append("Final video is missing from delivery manifest")
            else:
                try:
                    final_review = json.loads(archive.read(final_review_name).decode("utf-8"))
                except (UnicodeDecodeError, ValueError, TypeError) as exc:
                    result["errors"].append(f"Final composition review is invalid: {exc}")
                else:
                    final_metrics = (
                        final_review.get("final_technical_metrics")
                        if isinstance(final_review, dict)
                        else None
                    )
                    if (
                        not isinstance(final_review, dict)
                        or final_review.get("video_sha256") != final_video_entry.get("sha256")
                    ):
                        result["errors"].append(
                            "Final composition review video hash does not match delivery manifest"
                        )
                    if (
                        not isinstance(final_metrics, dict)
                        or final_metrics.get("status") != "available"
                        or final_metrics.get("temporal_sample_evidence") != "sufficient"
                    ):
                        result["errors"].append(
                            "Final composition review technical evidence is missing or insufficient"
                        )
                    elif any(
                        key in final_metrics
                        for key in ("width", "height", "duration_seconds", "sampled_frames")
                    ):
                        from src.services.video_quality_metrics import video_candidate_metrics

                        with tempfile.TemporaryDirectory(prefix="delivery-final-verify-") as temporary_root:
                            final_path = Path(temporary_root) / Path(final_archive_name or "final.mp4").name
                            final_path.write_bytes(archive.read(final_archive_name))
                            observed = video_candidate_metrics(final_path, max_samples=8)
                        if (
                            not isinstance(observed, dict)
                            or observed.get("status") != "available"
                            or observed.get("temporal_sample_evidence") != "sufficient"
                        ):
                            result["errors"].append(
                                "Final composition media failed technical evidence revalidation"
                            )
                    if isinstance(final_review, dict) and final_review.get("final_audio_expected") is True:
                        audio_status = final_metrics.get("audio_signal_status")
                        audio_quality = final_metrics.get("audio_quality_status")
                        if audio_status != "usable" or audio_quality != "passed":
                            result["errors"].append(
                                "Final composition native-audio evidence is missing or failed"
                            )
            platform_exports = [
                (archive_name, item)
                for archive_name, item in manifest_entries.items()
                if archive_name.startswith("exports/")
                and Path(archive_name).suffix.lower() in {".mp4", ".mov"}
            ]
            if platform_exports:
                from src.services.video_quality_metrics import video_candidate_metrics

                with tempfile.TemporaryDirectory(prefix="delivery-verify-") as temporary_root:
                    for archive_name, manifest_item in platform_exports:
                        export_path = Path(temporary_root) / Path(archive_name).name
                        export_path.write_bytes(archive.read(archive_name))
                        observed = video_candidate_metrics(export_path, max_samples=8)
                        declared = None
                        manifest_path = f"{Path(archive_name).with_suffix('')}.json"
                        if manifest_path in names:
                            try:
                                declared = json.loads(archive.read(manifest_path).decode("utf-8"))
                            except (UnicodeDecodeError, ValueError, TypeError):
                                declared = None
                        declared_metrics = (
                            declared.get("technical_metrics")
                            if isinstance(declared, dict)
                            else None
                        )
                        if (
                            not isinstance(declared_metrics, dict)
                            or declared_metrics.get("status") != "available"
                            or declared_metrics.get("temporal_sample_evidence") != "sufficient"
                            or not isinstance(observed, dict)
                            or observed.get("status") != "available"
                            or observed.get("temporal_sample_evidence") != "sufficient"
                        ):
                            result["errors"].append(
                                f"Platform export technical evidence failed: {archive_name}"
                            )
            review_index_name = "metadata/review_index.json"
            if review_index_name in names:
                try:
                    review_index = json.loads(archive.read(review_index_name).decode("utf-8"))
                except (UnicodeDecodeError, ValueError, TypeError) as exc:
                    result["errors"].append(f"Review index is invalid: {exc}")
                else:
                    if not isinstance(review_index, dict):
                        result["errors"].append("Review index is invalid")
                    else:
                        final_video_entry = next(
                            (item for path, item in manifest_entries.items() if path.startswith("media/final_video")),
                            None,
                        )
                        if (
                            isinstance(final_video_entry, dict)
                            and review_index.get("final_video_sha256")
                            != final_video_entry.get("sha256")
                        ):
                            result["errors"].append("Review index final video hash does not match manifest")
                        for item in review_index.get("review_files", []) or []:
                            archive_name = item.get("path") if isinstance(item, dict) else None
                            manifest_item = manifest_entries.get(archive_name)
                            if manifest_item is None:
                                result["errors"].append(
                                    f"Review index references unmanifested file: {archive_name}"
                                )
                                continue
                            if (
                                item.get("sha256") != manifest_item.get("sha256")
                                or item.get("size") != manifest_item.get("size")
                            ):
                                result["errors"].append(
                                    f"Review index hash or size mismatch: {archive_name}"
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
            if export_path.suffix.lower() in {".mp4", ".mov"}:
                export_manifest_path = export_root / f"{export_path.stem}.json"
                try:
                    export_manifest = json.loads(export_manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise DeliveryPackageError(
                        f"Platform export manifest is missing or invalid: {export_manifest_path}"
                    ) from exc
                technical_metrics = (
                    export_manifest.get("technical_metrics")
                    if isinstance(export_manifest, dict) else None
                )
                if (
                    not isinstance(export_manifest, dict)
                    or export_manifest.get("status") != "ready"
                    or not isinstance(technical_metrics, dict)
                    or technical_metrics.get("status") != "available"
                    or technical_metrics.get("temporal_sample_evidence") != "sufficient"
                ):
                        raise DeliveryPackageError(
                            f"Platform export manifest is stale or incomplete for {export_path.name}"
                        )
                expected_hash = export_manifest.get("output_sha256")
                if not isinstance(expected_hash, str) or expected_hash.lower() != _sha256(export_path):
                    raise DeliveryPackageError(
                        f"Platform export manifest is stale for {export_path.name}"
                    )
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
    summary_reports = review_summary.get("reports")
    required_reports = ("production_story", "generation", "seed_dance_baseline_comparison")
    if not isinstance(summary_reports, dict):
        raise DeliveryPackageError(
            "Delivery review summary is missing its core report statuses"
        )
    missing_or_failed = [
        name for name in required_reports if summary_reports.get(name) != "passed"
    ]
    if missing_or_failed:
        raise DeliveryPackageError(
            "Core delivery reviews are missing or not passed: " + ", ".join(missing_or_failed)
        )
    report_missing_or_failed = [
        name for name in required_reports
        if not isinstance(reports, dict)
        or not isinstance(reports.get(name), dict)
        or reports[name].get("status") != "passed"
    ]
    if report_missing_or_failed:
        raise DeliveryPackageError(
            "Core delivery report evidence is missing or not passed: "
            + ", ".join(report_missing_or_failed)
        )

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
    final_technical_metrics = final_composition.get("final_technical_metrics")
    if (
        not isinstance(final_technical_metrics, dict)
        or final_technical_metrics.get("status") != "available"
        or final_technical_metrics.get("temporal_sample_evidence") != "sufficient"
    ):
        raise DeliveryPackageError(
            "Final composition technical evidence is missing or insufficient; delivery is blocked"
        )
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
    if cover_report.get("status") == "ready":
        from src.services.cover_quality_audit import audit_cover
        cover_quality = audit_cover(
            cover_path,
            expected_width=int(cover_report.get("width") or 768),
            expected_height=int(cover_report.get("height") or 1344),
        )
        cover_report["quality_audit"] = cover_quality
        if cover_quality.get("status") != "passed":
            raise DeliveryPackageError("Generated cover failed the mobile publishability quality gate")
    # Dynamic project audits are part of the signed delivery evidence. Persist
    # them before collecting review files so a package cannot omit the exact
    # continuity/rhythm evidence used by the approval decision.
    for audit_key in ("continuity_audit", "rhythm_audit"):
        audit_report = reports.get(audit_key)
        if isinstance(audit_report, dict):
            _write_json_atomic(root / "reviews" / f"{audit_key}.json", audit_report)
    # The report supplied to this export call is the approval decision for the
    # exact final video. Persist it even when the caller did not previously
    # create the conventional final-video sidecar; otherwise a valid in-memory
    # approval could produce a package with no final composition evidence.
    _write_json_atomic(root / "reviews" / "final_composition.json", final_composition)
    files = _collect_files(project, root, reports)

    project_metadata = delivery_root / "project_metadata.json"
    generation_evidence = _delivery_generation_evidence(reports)
    topic_brief = {}
    topic_brief_path = root / "topic_brief.json"
    if topic_brief_path.is_file():
        try:
            loaded_brief = json.loads(topic_brief_path.read_text(encoding="utf-8"))
            if isinstance(loaded_brief, dict):
                topic_brief = loaded_brief
        except (OSError, ValueError):
            topic_brief = {}
    market_signals = {}
    market_signals_path = root / "market_signals.json"
    if market_signals_path.is_file():
        try:
            loaded_signals = json.loads(market_signals_path.read_text(encoding="utf-8"))
            if isinstance(loaded_signals, dict):
                market_signals = loaded_signals
        except (OSError, ValueError):
            market_signals = {}
    _write_json_atomic(project_metadata, {
        "project_id": getattr(project, "id", None),
        "name": getattr(project, "name", ""),
        "theme": getattr(project, "theme", None),
        "outline": getattr(project, "outline", None),
        "script": getattr(project, "script", None),
        "topic_brief": topic_brief,
        "market_signals": market_signals,
        "generation_evidence": generation_evidence,
    })
    files.append((project_metadata, "metadata/project.json"))
    if cover_report.get("status") == "ready":
        files.append((cover_path, "cover/cover.jpg"))
    platform_cover_reports = {}
    export_root = root / "exports"
    if export_root.is_dir():
        for export_path in sorted(export_root.iterdir()):
            if not export_path.is_file() or export_path.suffix.lower() not in {".mp4", ".mov"}:
                continue
            preset = export_path.stem
            width, height = 768, 1344
            manifest_path_for_export = export_root / f"{preset}.json"
            try:
                export_manifest = json.loads(manifest_path_for_export.read_text(encoding="utf-8"))
                width = int(export_manifest.get("width") or width)
                height = int(export_manifest.get("height") or height)
            except (OSError, ValueError, TypeError):
                pass
            platform_cover_path = delivery_root / "covers" / f"{preset}.jpg"
            platform_cover = generate_cover(export_path, platform_cover_path, width=width, height=height)
            platform_cover_reports[preset] = platform_cover
            if platform_cover.get("status") == "ready":
                files.append((platform_cover_path, f"covers/{preset}.jpg"))
    cover_metadata = delivery_root / "cover_metadata.json"
    _write_json_atomic(cover_metadata, cover_report)
    files.append((cover_metadata, "metadata/cover.json"))
    platform_cover_metadata = delivery_root / "platform_cover_metadata.json"
    _write_json_atomic(platform_cover_metadata, platform_cover_reports)
    files.append((platform_cover_metadata, "metadata/platform_covers.json"))

    # Keep a compact, signed index of the exact review artifacts shipped in
    # this package. The ZIP may contain historical reports for auditability;
    # this index makes the evidence used for the current delivery explicit.
    review_files = []
    for source, archive_name in files:
        if archive_name.startswith("reviews/") and archive_name.endswith(".json"):
            review_files.append({
                "path": archive_name,
                "size": source.stat().st_size,
                "sha256": _sha256(source),
            })
    critical_reports = {
        name: {
            "kind": report.get("kind"),
            "status": report.get("status"),
        }
        for name, report in (reports or {}).items()
        if isinstance(report, dict)
        and (
            name in {"generation", "final_composition", "continuity_audit", "rhythm_audit", "story_room_quality"}
            or report.get("kind") == "sequence_boundary_continuity"
        )
    }
    review_index = delivery_root / "review_index.json"
    _write_json_atomic(review_index, {
        "schema_version": 1,
        "final_video_sha256": _sha256(final_path),
        "critical_reports": critical_reports,
        "review_files": review_files,
        "quality_summary_status": review_summary.get("status"),
    })
    files.append((review_index, "metadata/review_index.json"))

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
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": getattr(project, "id", None),
        "project_name": getattr(project, "name", ""),
        "status": "ready",
        "quality_summary": review_summary,
        "report_statuses": report_statuses,
        "cover": cover_report,
        "platform_covers": platform_cover_reports,
        "generation_evidence": generation_evidence,
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
