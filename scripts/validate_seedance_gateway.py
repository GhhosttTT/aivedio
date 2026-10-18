"""Validate the configured Seedance request without spending a generation.

Dry-run is the default. Use ``--live`` only when a real provider request is
intended and the output path is ready to receive the downloaded video.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Support both ``python3 scripts/validate_seedance_gateway.py`` and
# ``python3 -m scripts.validate_seedance_gateway`` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.generation_provider import (
    GenerationProviderError,
    SeedanceApiProvider,
    VideoGenerationRequest,
)
from src.config import settings
from src.services.video_quality_metrics import video_candidate_metrics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", default="A cinematic short-drama reaction shot")
    parser.add_argument("--output", default="storage/smoke/seedance.mp4")
    parser.add_argument("--reference-image", action="append", default=[])
    parser.add_argument("--end-image", help="Optional last-frame image")
    parser.add_argument("--reference-video", action="append", default=[])
    parser.add_argument("--reference-audio", action="append", default=[])
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument(
        "--aspect-ratio", choices=("9:16", "16:9", "1:1", "adaptive"), default="9:16",
        help="Output framing; the mobile short-drama default is 9:16",
    )
    parser.add_argument(
        "--mode",
        choices=("reference", "reference_to_video", "auto", "multi_shot", "edit", "extend"),
        help="Seedance task mode; auto is supported by native Seedance 2.5",
    )
    parser.add_argument(
        "--model",
        help="Optional per-run Seedance model override, for example doubao-seedance-2-5-260628",
    )
    parser.add_argument("--api-format", choices=("legacy", "ark_v3"), help="Request contract to validate")
    parser.add_argument("--resolution", choices=("480p", "720p", "1080p", "4k"))
    parser.add_argument("--output-format", choices=("mp4", "mov"))
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--draft-task-id")
    parser.add_argument("--return-last-frame", action="store_true")
    parser.add_argument("--camera-fixed", action="store_true")
    parser.add_argument("--watermark", action="store_true")
    parser.add_argument("--generate-audio", action="store_true")
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument("--live", action="store_true", help="Submit a real generation request")
    execution.add_argument(
        "--dry-run", action="store_true",
        help="Validate and print the request without submitting it (the default)",
    )
    parser.add_argument(
        "--skip-output-validation", action="store_true",
        help="With --live, skip ffprobe/OpenCV validation of the downloaded artifact",
    )
    return parser


def _validate_files(paths: list[str], kind: str) -> None:
    missing = [path for path in paths if not Path(path).is_file()]
    if missing:
        raise ValueError(f"{kind} reference file(s) do not exist: {', '.join(missing)}")


def _payload_summary(payload: dict) -> dict:
    summary = {}
    if "content" in payload:
        summary["content"] = [
            {
                "type": item.get("type"),
                "role": item.get("role"),
                "text_characters": len(item.get("text", "")) if item.get("type") == "text" else None,
                "is_data_url": any(
                    isinstance(value, dict) and str(value.get("url", "")).startswith("data:")
                    for value in (item.get("image_url", {}), item.get("video_url", {}), item.get("audio_url", {}))
                ),
            }
            for item in payload["content"]
        ]
    for key in ("image_urls", "video_urls", "audio_urls"):
        if key not in payload:
            continue
        values = payload.get(key) or []
        summary[key] = [
            {"is_data_url": str(value).startswith("data:"), "characters": len(str(value))}
            for value in values
        ]
    for key in ("model", "prompt", "duration", "resolution", "ratio", "aspect_ratio", "generate_audio", "multi_shot", "shot_plan", "omni_reference_task_type", "callback_url"):
        if key in payload:
            value = payload[key]
            summary[key] = {"keys": list(value) if isinstance(value, dict) else value} if key == "shot_plan" else value
    return summary


def _validate_live_output(
    result_path: str,
    request: VideoGenerationRequest,
    *,
    expected_duration: float | None = None,
) -> dict:
    """Verify that a live provider result is a usable video artifact."""
    metrics = video_candidate_metrics(result_path)
    if metrics.get("status") != "available":
        raise GenerationProviderError(
            "Seedance returned an unreadable video artifact: "
            f"{metrics.get('error') or result_path}"
        )
    if float(metrics.get("duration_seconds") or 0) <= 0:
        raise GenerationProviderError("Seedance returned a video with no measurable duration")
    requested_duration = float(
        request.duration_seconds if expected_duration is None else expected_duration
        or 0
    )
    actual_duration = float(metrics["duration_seconds"])
    if requested_duration > 0:
        duration_tolerance = max(0.35, requested_duration * 0.08)
        if abs(actual_duration - requested_duration) > duration_tolerance:
            raise GenerationProviderError(
                "Seedance result duration is out of sync: "
                f"requested {requested_duration:.3f}s, got {actual_duration:.3f}s"
            )
    if int(metrics.get("width") or 0) <= 0 or int(metrics.get("height") or 0) <= 0:
        raise GenerationProviderError("Seedance returned a video with invalid geometry")
    _validate_temporal_quality(metrics)
    audio_expected = bool(request.generate_audio or request.reference_audios)
    if audio_expected:
        if not metrics.get("audio_present"):
            raise GenerationProviderError("Seedance result is missing the requested audio stream")
        if metrics.get("audio_signal_status") != "usable":
            raise GenerationProviderError(
                "Seedance result audio signal is not usable: "
                f"{metrics.get('audio_signal_status') or 'unavailable'}"
            )
    return metrics


def _validate_temporal_quality(metrics: dict) -> None:
    """Reject provider artifacts that are technically playable but unsafe to publish."""
    static_seconds = float(metrics.get("max_static_run_seconds") or 0.0)
    motion_energy = float(metrics.get("motion_energy") or 0.0)
    if (
        static_seconds > float(settings.GENERATION_VIDEO_MAX_STATIC_RUN_SECONDS)
        and motion_energy < 0.4
    ):
        raise GenerationProviderError(
            "Seedance returned a frozen/static video run: "
            f"{static_seconds:.3f}s with motion_energy={motion_energy:.3f}"
        )
    black_seconds = float(metrics.get("max_black_run_seconds") or 0.0)
    if black_seconds > float(settings.GENERATION_VIDEO_MAX_BLACK_SECONDS):
        raise GenerationProviderError(
            "Seedance returned a black-frame run: "
            f"{black_seconds:.3f}s exceeds {settings.GENERATION_VIDEO_MAX_BLACK_SECONDS:.3f}s"
        )
    brightness_step = float(metrics.get("brightness_step_p95") or 0.0)
    if brightness_step > float(settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95):
        raise GenerationProviderError(
            "Seedance returned temporal exposure jumps: "
            f"brightness_step_p95={brightness_step:.3f}, "
            f"limit={settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95:.3f}"
        )
    motion_jitter = float(metrics.get("motion_jitter_ratio") or 0.0)
    if motion_jitter > float(settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO):
        raise GenerationProviderError(
            "Seedance returned unstable motion cadence: "
            f"motion_jitter_ratio={motion_jitter:.3f}, "
            f"limit={settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO:.3f}"
        )


def _run(args: argparse.Namespace) -> int:
    try:
        _validate_files(args.reference_image, "image")
        if args.end_image:
            _validate_files([args.end_image], "end image")
        _validate_files(args.reference_video, "video")
        _validate_files(args.reference_audio, "audio")
        if args.mode:
            os.environ["SEEDANCE_REQUEST_MODE"] = args.mode
        if args.api_format:
            os.environ["SEEDANCE_API_FORMAT"] = args.api_format
        provider = SeedanceApiProvider()
        request = VideoGenerationRequest(
            prompt=args.prompt,
            output_path=args.output,
            reference_images=args.reference_image or None,
            end_image=args.end_image,
            reference_videos=args.reference_video or None,
            reference_audios=args.reference_audio or None,
            generate_audio=args.generate_audio,
            multi_shot=args.mode == "multi_shot",
            request_mode=args.mode,
            model=args.model,
            resolution=args.resolution,
            output_format=args.output_format,
            draft=args.draft,
            draft_task_id=args.draft_task_id,
            return_last_frame=args.return_last_frame,
            camera_fixed=args.camera_fixed,
            watermark=args.watermark,
            duration_seconds=args.duration,
            aspect_ratio=args.aspect_ratio,
            shot_plan={"mode": args.mode} if args.mode == "multi_shot" else None,
        )
        payload = provider._video_payload(request)
        live = bool(args.live and not args.dry_run)
        print(json.dumps({
            "configured": bool(provider.endpoint and provider.api_key),
            "endpoint": provider.endpoint or None,
            "live": live,
            "payload": _payload_summary(payload),
        }, ensure_ascii=False, indent=2))
        if not live:
            return 0
        if not provider.endpoint or not provider.api_key:
            raise GenerationProviderError("Seedance endpoint/key is not configured; refusing live request")
        result = provider.generate_video(request)
        output = {"status": "completed", "output_path": result.output_path}
        if not args.skip_output_validation:
            expected_duration = request.duration_seconds
            expected_duration_fn = getattr(provider, "_expected_provider_duration", None)
            if callable(expected_duration_fn):
                provider_duration = expected_duration_fn(request)
                # ``None`` means the model chooses the duration (not the
                # request default), so represent it as an explicit disabled
                # gate for the standalone artifact validator.
                expected_duration = 0.0 if provider_duration is None else provider_duration
            output["artifact_validation"] = _validate_live_output(
                result.output_path,
                request,
                expected_duration=expected_duration,
            )
        else:
            output["artifact_validation"] = {"status": "skipped"}
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (GenerationProviderError, OSError, ValueError) as exc:
        print(f"Seedance validation failed: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    previous_mode = os.environ.get("SEEDANCE_REQUEST_MODE")
    previous_api_format = os.environ.get("SEEDANCE_API_FORMAT")
    try:
        return _run(args)
    finally:
        if previous_mode is None:
            os.environ.pop("SEEDANCE_REQUEST_MODE", None)
        else:
            os.environ["SEEDANCE_REQUEST_MODE"] = previous_mode
        if previous_api_format is None:
            os.environ.pop("SEEDANCE_API_FORMAT", None)
        else:
            os.environ["SEEDANCE_API_FORMAT"] = previous_api_format


if __name__ == "__main__":
    raise SystemExit(main())
