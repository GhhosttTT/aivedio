"""Tests for the stat-keyed video metrics cache."""

import os

import pytest

from src.services import video_quality_metrics
from src.services.video_quality_metrics import video_candidate_metrics


@pytest.fixture(autouse=True)
def clear_metrics_cache():
    video_quality_metrics.clear_video_candidate_metrics_cache()
    yield
    video_quality_metrics.clear_video_candidate_metrics_cache()


@pytest.fixture()
def fake_compute(monkeypatch):
    calls = []

    def fake(path, max_samples=None):
        calls.append((str(path), max_samples))
        return {
            "status": "available",
            "path": str(path),
            "technical_score": 4.2,
            "motion_energy": 1.5,
        }

    monkeypatch.setattr(
        "src.services.video_quality_metrics._compute_video_candidate_metrics",
        fake,
    )
    return calls


def test_repeated_metrics_reuse_cached_analysis(tmp_path, fake_compute):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")

    first = video_candidate_metrics(clip)
    second = video_candidate_metrics(clip)

    assert len(fake_compute) == 1
    assert first["path"] == str(clip)
    assert second == first


def test_cache_hits_are_isolated_from_caller_mutation(tmp_path, fake_compute):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")

    first = video_candidate_metrics(clip)
    first["technical_score"] = 0.0
    first["extra"] = "caller-only"

    second = video_candidate_metrics(clip)
    assert second["technical_score"] == 4.2
    assert "extra" not in second


def test_cache_invalidates_when_file_signature_changes(tmp_path, fake_compute):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    video_candidate_metrics(clip)
    stat = clip.stat()

    clip.write_bytes(b"other")  # different size
    video_candidate_metrics(clip)
    assert len(fake_compute) == 2

    os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    video_candidate_metrics(clip)
    assert len(fake_compute) == 3


def test_different_sample_budget_is_a_separate_entry(tmp_path, fake_compute):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")

    video_candidate_metrics(clip, max_samples=8)
    video_candidate_metrics(clip, max_samples=8)
    video_candidate_metrics(clip)
    video_candidate_metrics(clip, max_samples=24)

    assert len(fake_compute) == 3


def test_unavailable_results_are_not_cached(tmp_path, monkeypatch):
    calls = []

    def failing_compute(path, max_samples=None):
        calls.append(str(path))
        return {
            "status": "unavailable",
            "path": str(path),
            "technical_score": None,
            "error": "decode failed",
        }

    monkeypatch.setattr(
        "src.services.video_quality_metrics._compute_video_candidate_metrics",
        failing_compute,
    )
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"not-a-video")

    first = video_candidate_metrics(clip)
    second = video_candidate_metrics(clip)

    assert len(calls) == 2
    assert first["status"] == "unavailable"
    assert second["error"] == "decode failed"
