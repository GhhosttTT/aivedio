"""Deterministic cross-shot continuity contracts for video generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class SequenceShot:
    scene_number: int
    role: str
    character_name: str
    visual_summary: str
    dialogue: str
    duration_seconds: float | None
    has_keyframe: bool
    has_video: bool


@dataclass(frozen=True)
class SequenceContext:
    sequence_id: str
    current: SequenceShot
    previous: SequenceShot | None
    next: SequenceShot | None
    continuity_contract: tuple[str, ...]
    sequence_shots: tuple[SequenceShot, ...] = ()

    def as_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "current": asdict(self.current),
            "previous": asdict(self.previous) if self.previous else None,
            "next": asdict(self.next) if self.next else None,
            "continuity_contract": list(self.continuity_contract),
            "sequence_shots": [asdict(shot) for shot in self.sequence_shots],
        }


@dataclass(frozen=True)
class SequenceSegment:
    """One scene's time range inside a sequence-level generated video."""

    scene_number: int
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return round(max(0.0, self.end_seconds - self.start_seconds), 3)

    def as_dict(self) -> dict:
        return {
            "scene_number": self.scene_number,
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "duration_seconds": self.duration_seconds,
        }


def build_sequence_context(
    scenes: Iterable[object],
    current_scene_number: int,
    sequence_id: str | None = None,
) -> SequenceContext:
    """Build bounded previous/current/next context around one scene."""
    ordered = sorted(
        (_to_sequence_shot(scene) for scene in scenes),
        key=lambda shot: shot.scene_number,
    )
    current_index = next(
        (index for index, shot in enumerate(ordered) if shot.scene_number == current_scene_number),
        None,
    )
    if current_index is None:
        raise ValueError(f"Scene {current_scene_number} is not present in sequence")
    current = ordered[current_index]
    previous = ordered[current_index - 1] if current_index > 0 else None
    following = ordered[current_index + 1] if current_index + 1 < len(ordered) else None

    contract = [
        "preserve character identity, wardrobe, and visual style across adjacent shots",
        "keep the current shot as one continuous action beat",
    ]
    if previous:
        contract.append(f"continue naturally from scene {previous.scene_number} without an unexplained reset")
    if following:
        contract.append(f"end with readable composition that can cut into scene {following.scene_number}")
    if previous and current.character_name and previous.character_name == current.character_name:
        contract.append("match the speaking character's screen direction and eyeline")
    if previous and previous.has_video:
        contract.append("use the previous shot as motion and pacing guidance, not as a new character source")

    return SequenceContext(
        sequence_id=sequence_id or "sequence",
        current=current,
        previous=previous,
        next=following,
        continuity_contract=tuple(contract),
        sequence_shots=tuple(ordered),
    )


def build_sequence_timeline(
    scenes: Iterable[object],
    *,
    max_duration_seconds: float = 30.0,
    default_scene_duration_seconds: float = 4.0,
    minimum_scene_duration_seconds: float = 1.0,
) -> list[SequenceSegment]:
    """Allocate a bounded, deterministic timeline for one sequence request.

    Dialogue duration is the strongest signal. Remaining scenes use a stable
    short-drama default, and the complete timeline is proportionally compressed
    when it exceeds the provider's maximum instead of silently overflowing the
    requested 30-second task.
    """
    if not math.isfinite(max_duration_seconds) or max_duration_seconds <= 0:
        raise ValueError("max_duration_seconds must be positive")
    if (
        not math.isfinite(default_scene_duration_seconds)
        or not math.isfinite(minimum_scene_duration_seconds)
        or default_scene_duration_seconds <= 0
        or minimum_scene_duration_seconds <= 0
    ):
        raise ValueError("scene durations must be positive")
    shots = sorted((_to_sequence_shot(scene) for scene in scenes), key=lambda item: item.scene_number)
    if not shots:
        raise ValueError("At least one scene is required for a sequence timeline")
    durations: list[float] = []
    for shot in shots:
        try:
            measured = float(shot.duration_seconds) if shot.duration_seconds is not None else 0.0
        except (TypeError, ValueError):
            measured = 0.0
        if not math.isfinite(measured):
            raise ValueError(f"Scene {shot.scene_number} duration must be finite")
        duration = measured + 0.3 if measured > 0 else default_scene_duration_seconds
        durations.append(max(minimum_scene_duration_seconds, duration))
    total = sum(durations)
    if total > max_duration_seconds:
        scale = max_duration_seconds / total
        durations = [max(minimum_scene_duration_seconds, value * scale) for value in durations]
        # Re-normalize after minimum floors so the final boundary never exceeds
        # the provider limit.
        floored_total = sum(durations)
        if floored_total > max_duration_seconds:
            scale = max_duration_seconds / floored_total
            durations = [value * scale for value in durations]
    segments: list[SequenceSegment] = []
    cursor = 0.0
    for index, (shot, duration) in enumerate(zip(shots, durations)):
        end = max_duration_seconds if index == len(shots) - 1 and sum(durations) >= max_duration_seconds else cursor + duration
        segments.append(SequenceSegment(shot.scene_number, round(cursor, 3), round(end, 3)))
        cursor = end
    return segments


def _to_sequence_shot(scene: object) -> SequenceShot:
    scene_number = getattr(scene, "scene_number", None)
    if isinstance(scene_number, bool) or not isinstance(scene_number, int) or scene_number <= 0:
        raise ValueError("Scene number must be a positive integer")
    visual = str(getattr(scene, "visual_description", None) or getattr(scene, "image_prompt", None) or "").strip()
    return SequenceShot(
        scene_number=scene_number,
        role=str(getattr(scene, "shot_role", None) or "story_shot"),
        character_name=str(getattr(scene, "character_name", None) or "").strip(),
        visual_summary=visual[:280],
        dialogue=str(getattr(scene, "dialogue", None) or "").strip()[:180],
        duration_seconds=getattr(scene, "audio_duration", None),
        has_keyframe=bool(getattr(scene, "image_path", None)),
        has_video=bool(getattr(scene, "video_path", None)),
    )
