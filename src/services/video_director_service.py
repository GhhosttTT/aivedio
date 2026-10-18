"""Director-level planning for short-drama video clips.

This layer turns an atomic scene into a concrete motion contract before it is
sent to the underlying video model. The goal is to keep business logic stable
while the actual video engine can change from SVD to ComfyUI/Wan/AnimateDiff or
an external provider.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


NO_DIALOGUE_MARKERS = {"", "无", "无对白", "没有对白", "none", "null", "n/a", "na", "-"}


@dataclass(frozen=True)
class VideoShotPlan:
    shot_role: str
    action_intensity: str
    target_duration_seconds: float
    fps: int
    num_frames: int
    motion_bucket_id: int
    noise_aug_strength: float
    director_prompt: str
    end_frame_prompt: str
    negative_prompt: str
    notes: list[str]
    spatial_plan: dict | None = None

    def as_dict(self) -> dict:
        return {
            "shot_role": self.shot_role,
            "action_intensity": self.action_intensity,
            "target_duration_seconds": self.target_duration_seconds,
            "fps": self.fps,
            "num_frames": self.num_frames,
            "motion_bucket_id": self.motion_bucket_id,
            "noise_aug_strength": self.noise_aug_strength,
            "director_prompt": self.director_prompt,
            "end_frame_prompt": self.end_frame_prompt,
            "negative_prompt": self.negative_prompt,
            "notes": list(self.notes),
            "spatial_plan": self.spatial_plan or {},
        }


class VideoDirectorService:
    """Plans model-facing motion and continuity constraints per atomic scene."""

    ACTION_TERMS = (
        "走", "跑", "追", "打", "撞", "摔", "推", "拉", "转身", "递", "拿起", "放下",
        "knock", "run", "walk", "push", "pull", "turn", "fight", "chase", "hand",
    )
    EMOTION_TERMS = (
        "哭", "笑", "愣", "惊", "怒", "尴尬", "羞", "沉默", "看着", "凝视",
        "smile", "cry", "stare", "hesitate", "shock", "angry", "embarrassed",
    )
    PROP_TERMS = (
        "杯", "咖啡", "手机", "信", "纸条", "门", "钥匙", "照片", "latte", "phone",
        "letter", "note", "door", "cup",
    )

    def plan_scene(self, scene, project_id: int | None = None, visible_characters: Iterable[dict] = ()) -> VideoShotPlan:
        visual = (scene.visual_description or "").strip()
        prompt = (scene.image_prompt or visual).strip()
        dialogue = (scene.dialogue or "").strip()
        visible = list(visible_characters or [])
        visual_style = self._visual_style_prompt(project_id)
        shot_aesthetic = self._shot_aesthetic_profile(scene, visible_count=len(visible))
        if shot_aesthetic.get("prompt"):
            visual_style = self._append_sentence(visual_style, shot_aesthetic["prompt"])
        shot_role = self._shot_role(visual, prompt, dialogue)
        action_intensity = self._action_intensity(visual, prompt)
        duration = self._target_duration(dialogue, shot_role)
        fps = max(8, int(settings.GENERATION_VIDEO_MODEL_FPS))
        audio_duration = getattr(scene, "audio_duration", None)
        if dialogue.lower() not in NO_DIALOGUE_MARKERS and isinstance(audio_duration, (int, float)):
            if not math.isfinite(audio_duration) or audio_duration < 0:
                raise ValueError("Dialogue audio duration must be finite and nonnegative")
            if audio_duration > 0:
                required = audio_duration + 0.3
                capacity = min(float(settings.GENERATION_VIDEO_MAX_SECONDS), int(settings.GENERATION_VIDEO_MAX_FRAMES) / fps)
                if required > capacity:
                    raise ValueError(
                        f"Dialogue needs {required:.2f}s including reaction room but this shot supports {capacity:.2f}s; "
                        "split the dialogue into atomic shots or configure a longer video workflow"
                    )
                duration = min(capacity, max(duration, required))
        num_frames = max(8, min(int(settings.GENERATION_VIDEO_MAX_FRAMES), math.ceil(duration * fps)))
        motion, noise = self._motion_params(shot_role, action_intensity)
        spatial_plan = self._spatial_plan(prompt or visual, shot_role, visible)
        director_prompt = self._director_prompt(
            prompt or visual,
            shot_role,
            action_intensity,
            visible,
            spatial_plan,
            visual_style,
            dialogue=dialogue,
        )
        end_frame_prompt = self._end_frame_prompt(prompt or visual, shot_role, action_intensity, visible, spatial_plan, visual_style)
        negative_prompt = self._negative_prompt(project_id, shot_aesthetic)
        notes = [
            "single continuous shot",
            "preserve the source keyframe identity and layout",
            "avoid introducing new people, props, or scene changes",
        ]
        if project_id is not None:
            notes.append(f"project_id={project_id}")
        if isinstance(audio_duration, (int, float)) and audio_duration > 0:
            notes.append(f"timed to measured dialogue audio: {audio_duration:.3f}s")
        return VideoShotPlan(
            shot_role=shot_role,
            action_intensity=action_intensity,
            target_duration_seconds=duration,
            fps=fps,
            num_frames=num_frames,
            motion_bucket_id=motion,
            noise_aug_strength=noise,
            director_prompt=director_prompt,
            end_frame_prompt=end_frame_prompt,
            negative_prompt=negative_prompt,
            notes=notes,
            spatial_plan=spatial_plan,
        )

    def normalize_clip(
        self,
        input_path: str,
        output_path: str,
        target_duration: float | None = None,
        preserve_audio: bool = False,
        preserve_provider_quality: bool = False,
    ) -> str:
        """Convert generated clips to production preview settings when possible."""
        if not settings.GENERATION_VIDEO_POSTPROCESS:
            return input_path
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            logger.warning("ffmpeg/ffprobe unavailable; skip video postprocess")
            return input_path
        source = Path(input_path)
        if not source.is_file() or source.stat().st_size <= 0:
            return input_path
        try:
            duration = self._probe_duration(source)
        except Exception as exc:
            logger.warning("Cannot probe generated clip {}; skip postprocess: {}", source, exc)
            return input_path
        if duration <= 0:
            return input_path
        source_pixel_format = None
        source_geometry = None
        if preserve_provider_quality:
            try:
                source_pixel_format = self._probe_pixel_format(source)
            except Exception as exc:
                logger.debug("Cannot probe generated clip pixel format {}; using compatible encoding: {}", source, exc)
            try:
                source_geometry = self._probe_geometry(source)
            except Exception as exc:
                logger.debug("Cannot probe generated clip geometry {}; using configured output geometry: {}", source, exc)
        high_bit_depth = bool(source_pixel_format and re.search(r"(?:p|yuv)\d{2}le$", source_pixel_format.lower()))
        high_chroma = bool(
            preserve_provider_quality
            and source_pixel_format
            and "yuv444" in source_pixel_format.lower()
        )
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_geometry and source_geometry[0] > 0 and source_geometry[1] > 0:
            width, height = source_geometry[:2]
        else:
            width = int(settings.GENERATION_WIDTH)
            height = int(settings.GENERATION_HEIGHT)
        if preserve_provider_quality and source_geometry:
            # A provider's resolution/aspect ratio/fps are part of its output
            # contract. Do not silently downscale a 1080p/4K Seedance clip to
            # the local ComfyUI canvas during the normalization pass.
            filters = ["setsar=1"]
        else:
            if str(getattr(settings, "GENERATION_VIDEO_FRAME_FIT_MODE", "cover")).strip().lower() == "contain":
                filters = [
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                    "setsar=1",
                    f"fps={int(settings.GENERATION_VIDEO_OUTPUT_FPS)}",
                ]
            else:
                # Cover-fill prevents the local SVD landscape fallback from
                # becoming a portrait video with black bars. The crop is
                # centered so the keyframe's central actor remains readable.
                filters = [
                    f"scale={width}:{height}:force_original_aspect_ratio=increase",
                    f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2",
                    "setsar=1",
                    f"fps={int(settings.GENERATION_VIDEO_OUTPUT_FPS)}",
                ]
        minimum = target_duration or settings.GENERATION_VIDEO_TARGET_SECONDS
        if duration < minimum:
            shortage = minimum - duration
            if shortage > max(0.0, settings.GENERATION_VIDEO_MAX_FREEZE_SECONDS):
                raise ValueError(
                    f"Generated clip is {shortage:.3f}s too short; regenerate a longer clip instead of freezing the last frame"
                )
            filters.append(f"tpad=stop_mode=clone:stop_duration={shortage:.3f}")
        output_pixel_format = (
            "yuv420p10le" if high_bit_depth
            else "yuv444p" if high_chroma
            else "yuv420p"
        )
        filters.append(f"format={output_pixel_format}")
        command = [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vf", ",".join(filters),
            "-map", "0:v:0",
        ]
        if preserve_audio:
            command.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "192k"])
        else:
            command.append("-an")
        video_codec = "libx265" if high_bit_depth else "libx264"
        pixel_format = output_pixel_format
        command.extend([
            "-c:v", video_codec, "-preset", "slow", "-crf", "18",
            "-pix_fmt", pixel_format, "-movflags", "+faststart",
        ])
        if high_bit_depth:
            command.extend(["-tag:v", "hvc1"])
        command.append(str(destination))
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
            return str(destination)
        except Exception as exc:
            logger.warning("Video postprocess failed for {}; keep original: {}", source, exc)
            # ffmpeg may leave a truncated file when encoding fails. Never let
            # that artifact shadow the valid source on retry or recovery.
            try:
                destination.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                logger.debug("Cannot remove failed normalized clip {}: {}", destination, cleanup_exc)
            return input_path

    @staticmethod
    def _contains_any(text: str, terms: Iterable[str]) -> bool:
        lower = text.lower()
        return any(term.lower() in lower for term in terms)

    def _shot_role(self, visual: str, prompt: str, dialogue: str) -> str:
        text = f"{visual} {prompt}"
        if self._contains_any(text, self.ACTION_TERMS):
            return "action"
        if self._contains_any(text, self.PROP_TERMS):
            return "prop_interaction"
        if self._contains_any(text, self.EMOTION_TERMS):
            return "emotion_reaction"
        if dialogue.strip().lower() not in NO_DIALOGUE_MARKERS:
            return "dialogue_reaction"
        return "establishing"

    def _action_intensity(self, visual: str, prompt: str) -> str:
        text = f"{visual} {prompt}"
        if self._contains_any(text, ("跑", "追", "打", "撞", "摔", "fight", "chase", "run")):
            return "high"
        if self._contains_any(text, self.ACTION_TERMS):
            return "medium"
        return "low"

    def _target_duration(self, dialogue: str, shot_role: str) -> float:
        base = float(settings.GENERATION_VIDEO_TARGET_SECONDS)
        if dialogue.strip().lower() in NO_DIALOGUE_MARKERS:
            return max(2.8, min(float(settings.GENERATION_VIDEO_MAX_SECONDS), base))
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", dialogue))
        latin_words = len(re.findall(r"[A-Za-z0-9']+", dialogue))
        speech_seconds = chinese_chars / 4.2 + latin_words / 2.4
        role_padding = 0.8 if shot_role in {"emotion_reaction", "dialogue_reaction"} else 0.5
        return round(max(base, min(float(settings.GENERATION_VIDEO_MAX_SECONDS), speech_seconds + role_padding)), 2)

    def _motion_params(self, shot_role: str, action_intensity: str) -> tuple[int, float]:
        if action_intensity == "high":
            return 150, 0.035
        if shot_role == "prop_interaction":
            return 118, 0.018
        if shot_role in {"emotion_reaction", "dialogue_reaction"}:
            return 92, 0.012
        if shot_role == "establishing":
            return 105, 0.015
        return 127, 0.02

    def _spatial_plan(self, prompt: str, shot_role: str, visible_characters: list[dict]) -> dict:
        text = prompt.lower()
        names = [str(item.get("name") or f"character {index + 1}") for index, item in enumerate(visible_characters)]
        if any(term in text for term in ("close-up", "close up", "特写", "脸部", "face")):
            shot_scale = "close-up"
        elif len(names) >= 2 or any(term in text for term in ("two-shot", "two shot", "对峙", "面对面")):
            shot_scale = "medium two-shot"
        elif shot_role == "establishing" or any(term in text for term in ("wide", "全景", "街景", "room", "location")):
            shot_scale = "wide establishing shot"
        else:
            shot_scale = "medium shot"

        if any(term in text for term in ("俯拍", "overhead", "top-down")):
            camera_angle = "slight overhead angle"
        elif any(term in text for term in ("低角度", "low angle")):
            camera_angle = "low eye-line angle"
        elif any(term in text for term in ("侧脸", "profile", "side")):
            camera_angle = "stable side angle"
        else:
            camera_angle = "eye-level angle"

        slots = ["frame left", "frame right", "center", "background left", "background right"]
        if len(names) == 1:
            positions = {names[0]: "center foreground"}
        else:
            positions = {name: slots[index % len(slots)] for index, name in enumerate(names)}
        prop_focus = self._prop_focus(prompt)
        axis = "keep a fixed 180-degree screen direction; do not flip left/right positions"
        continuity = (
            f"{shot_scale}, {camera_angle}; "
            + ", ".join(f"{name} at {position}" for name, position in positions.items())
            + (f"; prop focus: {prop_focus}" if prop_focus else "")
            + f"; {axis}."
        )
        control_references = {
            "pose_reference_prompt": (
                f"Pose control for {shot_scale}: "
                + ", ".join(f"{name} {position}" for name, position in positions.items())
                + "; one readable short-drama action beat; stable limbs and eye lines."
            ),
            "depth_reference_prompt": (
                f"Depth control: {shot_scale}, foreground subject separation, stable room geometry"
                + (f", prop {prop_focus} remains visible" if prop_focus else "")
                + "."
            ),
            "camera_reference_prompt": f"Camera control: {camera_angle}; {axis}",
        }
        return {
            "shot_scale": shot_scale,
            "camera_angle": camera_angle,
            "camera_axis": axis,
            "character_positions": positions,
            "prop_focus": prop_focus,
            "continuity_prompt": continuity,
            "control_references": control_references,
        }

    def _prop_focus(self, prompt: str) -> str:
        for term in self.PROP_TERMS:
            if term.lower() in prompt.lower():
                return term
        return ""

    def _director_prompt(
        self,
        prompt: str,
        shot_role: str,
        action_intensity: str,
        visible_characters: list[dict],
        spatial_plan: dict,
        visual_style: str = "",
        dialogue: str = "",
    ) -> str:
        identity = self._identity_prompt(visible_characters)
        role_guidance = {
            "action": "Make the action readable as one continuous movement with clear start, middle, and end.",
            "prop_interaction": "Keep hands and the important prop visible; do not change the prop type, color, or position abruptly.",
            "emotion_reaction": "Use subtle facial expression and head movement; preserve face structure and wardrobe.",
            "dialogue_reaction": "Use natural breathing, small eye movement, and restrained reaction timing.",
            "establishing": "Use gentle cinematic camera drift while keeping the location stable.",
        }.get(shot_role, "Use natural short-drama motion.")
        camera_guidance = {
            "action": "controlled tracking or pan that follows the action without a cut",
            "prop_interaction": "stable medium camera with a restrained push-in on the prop",
            "emotion_reaction": "locked or very slow push-in that preserves the eyeline",
            "dialogue_reaction": "gentle conversational push-in with stable face framing",
            "establishing": "slow cinematic drift with stable horizon and room geometry",
        }.get(shot_role, "subtle cinematic camera movement without a cut")
        spoken_line = str(dialogue or "").strip()
        if spoken_line and spoken_line.lower() not in NO_DIALOGUE_MARKERS:
            dialogue_guidance = (
                f"Dialogue and lip sync: deliver the exact spoken line \"{spoken_line[:240]}\"; "
                "mouth movement starts and stops with the line, natural pauses and restrained facial acting, "
                "keep the speaking character's eyeline readable."
            )
        else:
            dialogue_guidance = "Dialogue and lip sync: no spoken dialogue; keep mouths relaxed and do not invent speech."
        spatial = f" Spatial continuity contract: {spatial_plan.get('continuity_prompt', '')}"
        return (
            f"Subject and setting: {prompt}. Action and performance: {role_guidance} "
            f"Shot role: {shot_role}. Motion intensity: {action_intensity}. "
            f"Camera direction: {camera_guidance}. "
            f"{dialogue_guidance} "
            f"Timing: one readable atomic beat with a clear beginning, development, and settled ending; "
            f"continuous real-time motion, no jump cut, no time-lapse."
            f"{identity}{spatial} Style and finish: {visual_style} "
            f"Continuity constraints: cinematic short-drama clip, stable identity, stable background, "
            f"stable wardrobe and props, no new people."
        )

    def _end_frame_prompt(self, prompt: str, shot_role: str, action_intensity: str, visible_characters: list[dict], spatial_plan: dict, visual_style: str = "") -> str:
        identity = self._identity_prompt(visible_characters, prefix=" Keep identity anchors unchanged")
        ending = {
            "action": "the action has just completed, body pose naturally settled, readable result of the movement",
            "prop_interaction": "the important prop remains visible after the hand interaction, hands separated clearly",
            "emotion_reaction": "the face holds the final emotional reaction, subtle eyes and head position changed",
            "dialogue_reaction": "the character finishes the reaction beat, natural breathing and attentive eye line",
            "establishing": "the same location after a gentle camera drift, stable layout and atmosphere",
        }.get(shot_role, "the same shot at the end of one short-drama beat")
        return (
            f"{prompt}. End frame: {ending}. Motion intensity was {action_intensity}."
            f"{identity} Preserve spatial contract: {spatial_plan.get('continuity_prompt', '')} "
            f"{visual_style} Same scene, same wardrobe, same props, no new people, cinematic short-drama keyframe."
        )

    def _negative_prompt(self, project_id: int | None = None, shot_aesthetic: dict | None = None) -> str:
        base = settings.GENERATION_QUALITY_NEGATIVE_APPEND
        if project_id is not None:
            try:
                from src.services.visual_style_assets import VisualStyleAssetService
                style_negative = VisualStyleAssetService().generation_negative_for_project(project_id)
                if style_negative:
                    base = f"{base}, {style_negative}" if base else style_negative
            except Exception:
                pass
        video_terms = (
            "face morphing, identity drift, duplicated character, new stranger, flicker, warped body, "
            "melting hands, changing clothes, changing room, disappearing prop, unreadable action, "
            "random camera jump, slideshow, still image only"
        )
        if isinstance(shot_aesthetic, dict) and shot_aesthetic.get("negative_prompt"):
            video_terms = f"{video_terms}, {shot_aesthetic['negative_prompt']}"
        return f"{base}, {video_terms}" if base else video_terms

    def _visual_style_prompt(self, project_id: int | None) -> str:
        if project_id is None:
            return ""
        try:
            from src.services.visual_style_assets import VisualStyleAssetService
            return VisualStyleAssetService().generation_prompt_for_project(project_id)
        except Exception:
            return ""

    def _shot_aesthetic_profile(self, scene, visible_count: int | None = None) -> dict:
        try:
            from src.services.visual_style_assets import VisualStyleAssetService
            return VisualStyleAssetService().shot_aesthetic_profile(scene, visible_count=visible_count)
        except Exception:
            return {}

    @staticmethod
    def _append_sentence(base: str | None, addition: str | None) -> str:
        base = str(base or "").strip()
        addition = str(addition or "").strip()
        if not addition:
            return base
        if not base:
            return addition
        if addition.lower() in base.lower():
            return base
        return base.rstrip(" .") + ". " + addition

    def _identity_prompt(self, visible_characters: list[dict], prefix: str = " Visible character identity anchors") -> str:
        if not visible_characters:
            return ""
        anchors = "; ".join(
            f"{item.get('name', 'character')}: {item.get('appearance', '')}"
            for item in visible_characters
        )
        turnaround_items = []
        for item in visible_characters:
            reference = item.get("turnaround_reference")
            if not isinstance(reference, dict):
                continue
            view = reference.get("view")
            control_prompt = reference.get("control_prompt")
            if view and control_prompt:
                turnaround_items.append(
                    f"{item.get('name', 'character')} {view} reference locked: {control_prompt}"
                )
        specs = [
            item.get("identity_spec") for item in visible_characters
            if isinstance(item.get("identity_spec"), dict)
        ]
        contrast = ""
        if len(specs) >= 2:
            from src.services.character_identity_service import CharacterIdentityService
            contrast = CharacterIdentityService().identity_contrast_prompt(specs)
        turnaround = " Turnaround reference contract: " + "; ".join(turnaround_items) + "." if turnaround_items else ""
        return f"{prefix}: {anchors}." + turnaround + (f" {contrast}" if contrast else "")

    @staticmethod
    def _probe_duration(path: Path) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())

    @staticmethod
    def _probe_pixel_format(path: Path) -> str:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=pix_fmt", "-of", "default=nw=1:nk=1", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    @staticmethod
    def _probe_geometry(path: Path) -> tuple[int, int, float | None]:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate",
                "-of", "csv=p=0:s=,", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        values = [item.strip() for item in result.stdout.strip().split(",")]
        if len(values) < 2:
            raise ValueError("ffprobe returned incomplete video geometry")
        width = int(values[0])
        height = int(values[1])
        fps = None
        if len(values) >= 3 and values[2] and values[2] != "0/0":
            numerator, denominator = values[2].split("/", 1)
            if float(denominator):
                fps = float(numerator) / float(denominator)
        return width, height, fps


_video_director_instance: VideoDirectorService | None = None


def get_video_director_service() -> VideoDirectorService:
    global _video_director_instance
    if _video_director_instance is None:
        _video_director_instance = VideoDirectorService()
    return _video_director_instance
