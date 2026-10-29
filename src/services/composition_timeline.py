"""One media clock for video cuts, local audio pre-laps, and subtitle cues."""

from dataclasses import dataclass
import math

from src.config import settings


@dataclass(frozen=True)
class SceneTiming:
    video_start: float
    audio_start: float
    end: float
    video_overlap: float
    audio_overlap: float


def transition_audio_overlap(plan: dict) -> float:
    transition = plan.get("transition", {})
    if plan.get("audio_strategy") == "dialogue_pre_lap":
        requested = float(settings.GENERATION_VIDEO_DIALOGUE_PRELAP_SECONDS)
    elif transition.get("video") == "crossfade":
        requested = float(transition.get("duration_seconds", 0.0) or 0.0)
    else:
        requested = 0.001
    if not math.isfinite(requested):
        raise ValueError("Audio transition duration must be finite")
    return max(0.001, min(0.12, requested))


def build_composition_timeline(
    durations: list[float], editing_plan: list[dict] | None = None
) -> list[SceneTiming]:
    if any(not math.isfinite(duration) or duration <= 0 for duration in durations):
        raise ValueError("Scene timeline duration must be finite and positive")
    if editing_plan and len(editing_plan) != len(durations):
        raise ValueError("Editing plan must contain one entry per scene")
    result = []
    for index, duration in enumerate(durations):
        video_overlap = audio_overlap = 0.0
        if editing_plan and index:
            plan = editing_plan[index]
            transition = plan.get("transition", {})
            requested = float(transition.get("duration_seconds", 0.0) or 0.0)
            if not math.isfinite(requested):
                raise ValueError("Video transition duration must be finite")
            # Match the renderer's short xfade for a hard cut, but never let
            # either fade consume more media than the adjacent shots contain.
            video_overlap = min(
                max(0.001, requested if transition.get("video") == "crossfade" else 0.001),
                0.12,
                durations[index - 1],
                duration,
            )
            audio_overlap = max(
                video_overlap,
                min(
                    transition_audio_overlap(plan),
                    durations[index - 1],
                    duration,
                ),
            )
        previous_end = result[-1].end if result else 0.0
        video_start = previous_end - video_overlap
        result.append(
            SceneTiming(
                video_start=video_start,
                audio_start=previous_end - audio_overlap,
                end=video_start + duration,
                video_overlap=video_overlap,
                audio_overlap=audio_overlap,
            )
        )
    return result
