from pathlib import Path

import pytest

from src.services.occlusion_removal import (
    MaskCandidate,
    MaskSource,
    OcclusionRemovalError,
    OcclusionRemovalService,
    RemovalBackend,
)


def test_mask_candidate_rejects_invalid_normalized_values():
    candidate = MaskCandidate(
        source=MaskSource.OCR_TEXT,
        confidence=0.9,
        x=0.0,
        y=0.8,
        width=1.2,
        height=0.1,
    )

    with pytest.raises(ValueError):
        candidate.validate()


def test_build_plan_defaults_to_quality_first_policy(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")
    monkeypatch.setattr("src.services.occlusion_removal.settings.OCCLUSION_REMOVAL_BACKEND", "auto_video_inpaint")
    monkeypatch.setattr("src.services.occlusion_removal.settings.OCCLUSION_MIN_QUALITY_SCORE", 0.92)

    service = OcclusionRemovalService()
    plan = service.build_plan(str(video))

    assert plan.backend == RemovalBackend.AUTO_VIDEO_INPAINT
    assert plan.require_temporal_consistency is True
    assert plan.preserve_faces is True
    assert plan.preserve_edges is True
    assert plan.min_quality_score == 0.92
    assert plan.detector == "subtitle_band_heuristic"
    assert len(plan.mask_candidates) == 1


def test_manual_mask_without_candidates_requires_review(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")
    monkeypatch.setattr("src.services.occlusion_removal.settings.OCCLUSION_REMOVAL_BACKEND", "manual_mask")

    service = OcclusionRemovalService()

    with pytest.raises(OcclusionRemovalError):
        service.run(str(video), str(tmp_path / "out"))

    assert (tmp_path / "out" / "occlusion_removal_plan.json").exists()
    assert (tmp_path / "out" / "occlusion_detection_report.json").exists()
    assert (tmp_path / "out" / "occlusion_masks.json").exists()
    assert (tmp_path / "out" / "occlusion_quality_report.json").exists()


def test_unconfigured_auto_backend_fails_clearly(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")
    monkeypatch.setattr("src.services.occlusion_removal.settings.OCCLUSION_REMOVAL_BACKEND", "auto_video_inpaint")
    monkeypatch.setattr("src.services.occlusion_removal.settings.AUTO_VIDEO_INPAINT_COMMAND", "")

    service = OcclusionRemovalService()

    with pytest.raises(OcclusionRemovalError, match="not configured"):
        service.run(
            str(video),
            str(tmp_path / "out"),
            mask_candidates=[
                MaskCandidate(
                    source=MaskSource.OCR_TEXT,
                    confidence=0.95,
                    x=0.05,
                    y=0.82,
                    width=0.9,
                    height=0.12,
                )
            ],
        )


def test_low_confidence_candidates_require_review(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")
    monkeypatch.setattr("src.services.occlusion_removal.settings.OCCLUSION_REMOVAL_BACKEND", "auto_video_inpaint")
    monkeypatch.setattr("src.services.occlusion_removal.settings.OCCLUSION_AUTO_MASK_MIN_CONFIDENCE", 0.65)

    service = OcclusionRemovalService()
    plan = service.build_plan(
        str(video),
        [
            MaskCandidate(
                source=MaskSource.STATIC_WATERMARK,
                confidence=0.4,
                x=0.74,
                y=0.04,
                width=0.2,
                height=0.08,
            )
        ],
    )

    assert plan.needs_manual_review is True
    assert "low_confidence_mask" in [reason.value for reason in plan.review_reasons]
