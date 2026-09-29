"""Project-level visual style contracts for consistent short-drama output."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.config import settings
from src.database.models import Project, Scene
from src.utils.storage import storage_manager


class VisualStyleAssetService:
    VERSION = 1
    PLATFORM_AESTHETIC_PROMPT = (
        "Platform aesthetic contract: premium mobile drama, natural skin, clean light, phone-readable face."
    )
    PLATFORM_AESTHETIC_NEGATIVE = (
        "cheap filter look, plastic skin, waxy face, muddy light, oversaturated color, crushed shadows, blown highlights, "
        "tiny unreadable face, flat background, noisy upscale artifacts, visible face repair scar"
    )
    PROFILE_AESTHETIC_PROMPTS = {
        "seed_dance_reference": (
            "Seed Dance reference target: high-end vertical short-drama frame, photorealistic Asian drama cast, "
            "stable face geometry, natural pores and skin tone, styled but believable wardrobe, controlled practical lighting, "
            "premium set dressing, restrained commercial color grade, phone-readable eyes and expression, no AI gloss"
        ),
        "ultra": (
            "Ultra local generation target: photorealistic short-drama still, natural skin detail, clean lens contrast, "
            "premium wardrobe detail, controlled highlights, strong subject-background separation"
        ),
        "high_quality": (
            "High quality short-drama target: clean commercial lighting, readable expression, stable wardrobe, natural skin"
        ),
    }
    PROFILE_AESTHETIC_NEGATIVES = {
        "seed_dance_reference": (
            "AI generated gloss, wax museum face, same-face casting, unstable facial geometry, over-beautified influencer skin, "
            "plastic texture, cheap app filter, messy wardrobe, low-budget set dressing, poster-like overprocessing"
        ),
        "ultra": (
            "AI gloss, plastic skin, cheap beauty filter, unstable face shape, low-budget wardrobe, noisy upscale artifacts"
        ),
        "high_quality": "plastic skin, cheap filter, unstable face, muddy light",
    }
    IMAGE_AESTHETIC_FEATURES = (
        "skin_texture",
        "lighting_quality",
        "color_grade",
        "phone_readability",
        "background_separation",
        "production_polish",
        "style_consistency",
        "repair_artifacts_absent",
    )
    VIDEO_AESTHETIC_FEATURES = (
        "skin_texture_stability",
        "lighting_consistency",
        "color_grade_consistency",
        "phone_readability",
        "motion_smoothness",
        "background_stability",
        "artifact_absence",
    )
    SHOT_AESTHETIC_PROFILES = {
        "close_up": {
            "prompt": (
                "Shot aesthetic profile close_up: premium phone-readable face, clean catchlights, natural pores, "
                "subtle facial asymmetry, soft commercial key light, uncluttered background falloff"
            ),
            "negative": (
                "tiny face, dead eyes, waxy close-up, airbrushed skin, distorted eyes, harsh nose shadow, "
                "face cropped by frame edge"
            ),
            "review_focus": ["skin_texture", "phone_readability", "repair_artifacts_absent"],
        },
        "two_shot": {
            "prompt": (
                "Shot aesthetic profile two_shot: both actors readable on a vertical phone frame, separated faces, "
                "clear eyelines, balanced over-shoulder or frame-left frame-right blocking, distinct wardrobe silhouettes"
            ),
            "negative": (
                "merged bodies, copied face geometry, same-face casting, crossed eyelines, one actor hidden, "
                "crowded two-shot composition"
            ),
            "review_focus": ["phone_readability", "background_separation", "production_polish"],
        },
        "full_body": {
            "prompt": (
                "Shot aesthetic profile full_body: head-to-toe silhouette, natural body proportion, readable hands, "
                "clean floor contact, wardrobe shape preserved, premium set depth"
            ),
            "negative": (
                "broken legs, floating feet, fused fingers, cropped shoes, distorted body proportion, limp pose"
            ),
            "review_focus": ["visual_integrity", "production_polish", "background_separation"],
        },
        "establishing": {
            "prompt": (
                "Shot aesthetic profile establishing: premium short-drama location value, clean production-designed set, "
                "layered foreground and background, coherent practical lighting, subject remains readable"
            ),
            "negative": (
                "empty generic background, low-budget set, dirty clutter, flat wall, random strangers, unreadable subject"
            ),
            "review_focus": ["lighting_quality", "color_grade", "background_separation"],
        },
        "prop_interaction": {
            "prompt": (
                "Shot aesthetic profile prop_interaction: important prop visible and attractive, natural hand-object contact, "
                "clear gesture, readable fingers, prop color and position preserved"
            ),
            "negative": (
                "disappearing prop, floating object, broken fingers, fused fingers, unclear hand contact, changing prop"
            ),
            "review_focus": ["visual_integrity", "phone_readability", "production_polish"],
        },
        "reaction": {
            "prompt": (
                "Shot aesthetic profile reaction: expressive but natural short-drama reaction, readable eyes, controlled emotion, "
                "subtle head angle, clean face light, stable wardrobe"
            ),
            "negative": (
                "flat acting still, dead eyes, exaggerated cartoon expression, unreadable emotion, random gesture"
            ),
            "review_focus": ["skin_texture", "phone_readability", "production_polish"],
        },
    }

    def freeze_project_style(
        self,
        project: Project,
        scenes: Iterable[Scene],
        *,
        style_prompt: str | None = None,
        negative_prompt: str | None = None,
        notes: str = "",
    ) -> dict:
        current = self.build_current_manifest(project, scenes)
        manifest = {
            **current,
            "status": "frozen",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "style_prompt": style_prompt.strip() if style_prompt and style_prompt.strip() else current["style_prompt"],
            "negative_prompt": negative_prompt.strip() if negative_prompt and negative_prompt.strip() else current["negative_prompt"],
            "notes": notes,
        }
        path = self._path(project.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def validate_project_style(self, project: Project, scenes: Iterable[Scene]) -> dict:
        path = self._path(project.id)
        current = self.build_current_manifest(project, scenes)
        if not path.is_file():
            return {"status": "missing", "path": str(path), "current": current}
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": "invalid", "path": str(path), "error": str(exc), "current": current}
        stale = []
        for key in ("source_hash", "scene_style_hash"):
            if manifest.get(key) != current.get(key):
                stale.append(key)
        if not str(manifest.get("style_prompt") or "").strip():
            stale.append("style_prompt")
        if not str(manifest.get("negative_prompt") or "").strip():
            stale.append("negative_prompt")
        return {
            "status": "valid" if manifest.get("status") == "frozen" and not stale else "stale",
            "path": str(path),
            "stale": sorted(set(stale)),
            "manifest": manifest,
            "current": current,
        }

    def style_prompt_for_project(self, project_id: int) -> str:
        manifest = self._read_manifest(project_id)
        return str(manifest.get("style_prompt") or "").strip()

    def negative_prompt_for_project(self, project_id: int) -> str:
        manifest = self._read_manifest(project_id)
        return str(manifest.get("negative_prompt") or "").strip()

    def generation_prompt_for_project(self, project_id: int) -> str:
        prompt = self._append_sentence(self.style_prompt_for_project(project_id), self.PLATFORM_AESTHETIC_PROMPT)
        return self._append_sentence(prompt, self._profile_prompt())

    def generation_negative_for_project(self, project_id: int) -> str:
        negative = self._append_sentence(self.negative_prompt_for_project(project_id), self.PLATFORM_AESTHETIC_NEGATIVE)
        return self._append_sentence(negative, self._profile_negative_prompt())

    def platform_aesthetic_contract(self, project_id: int | None = None) -> dict:
        style_prompt = self.style_prompt_for_project(project_id) if project_id is not None else ""
        negative_prompt = self.negative_prompt_for_project(project_id) if project_id is not None else ""
        return {
            "version": 1,
            "quality_profile": self._quality_profile(),
            "style_prompt": style_prompt,
            "prompt": self.generation_prompt_for_project(project_id) if project_id is not None else self.PLATFORM_AESTHETIC_PROMPT,
            "negative_prompt": self.generation_negative_for_project(project_id) if project_id is not None else self.PLATFORM_AESTHETIC_NEGATIVE,
            "profile_prompt": self._profile_prompt(),
            "profile_negative_prompt": self._profile_negative_prompt(),
            "image_features": list(self.IMAGE_AESTHETIC_FEATURES),
            "video_features": list(self.VIDEO_AESTHETIC_FEATURES),
            "review_instruction": (
                "Score platform polish from concrete visual evidence: natural skin, commercial light, consistent color, "
                "phone readability, background separation, motion stability, and absence of repair artifacts."
            ),
            "negative_style_prompt": negative_prompt,
        }

    def shot_aesthetic_profile(self, scene: Scene | dict | None = None, *, visible_count: int | None = None) -> dict:
        """Return shot-scale visual constraints for production short-drama generation."""
        text = self._scene_text(scene)
        profile_id = self._shot_profile_id(text, visible_count)
        profile = self.SHOT_AESTHETIC_PROFILES[profile_id]
        return {
            "id": profile_id,
            "prompt": profile["prompt"],
            "negative_prompt": profile["negative"],
            "review_focus": list(profile["review_focus"]),
        }

    def build_current_manifest(self, project: Project, scenes: Iterable[Scene]) -> dict:
        scene_items = [
            {
                "scene_number": scene.scene_number,
                "visual_description": scene.visual_description or "",
                "location": getattr(scene, "location", "") or "",
                "time_period": getattr(scene, "time_period", "") or "",
            }
            for scene in sorted(list(scenes), key=lambda item: item.scene_number)
        ]
        source = {
            "project_id": project.id,
            "theme": project.theme or "",
            "outline": project.outline or "",
            "scene_count": len(scene_items),
        }
        style_source = {
            **source,
            "locations": sorted({item["location"] for item in scene_items if item["location"]}),
            "time_periods": sorted({item["time_period"] for item in scene_items if item["time_period"]}),
            "scene_descriptions": [item["visual_description"] for item in scene_items],
        }
        return {
            "version": self.VERSION,
            "project_id": project.id,
            "source_hash": self._hash(source),
            "scene_style_hash": self._hash(style_source),
            "style_prompt": self._default_style_prompt(project, scene_items),
            "negative_prompt": self._default_negative_prompt(),
            "scene_count": len(scene_items),
        }

    def _default_style_prompt(self, project: Project, scenes: list[dict]) -> str:
        theme = (project.theme or project.description or "modern urban short-drama").strip()
        locations = [item["location"] for item in scenes if item.get("location")]
        location_hint = ", ".join(sorted(set(locations))[:3]) or "consistent modern short-drama locations"
        return (
            f"Project visual style bible: {theme}; vertical mobile short-drama look; "
            f"consistent color grade across all scenes; clean natural skin texture; "
            f"commercial but believable lighting; restrained cinematic contrast; "
            f"phone-screen readable faces and emotions; coherent wardrobe colors; "
            f"locations stay visually consistent: {location_hint}."
        )

    @staticmethod
    def _default_negative_prompt() -> str:
        return (
            "style drift between shots, random color grade, inconsistent lighting, cheap filter look, "
            "over-smoothed plastic skin, over-saturated colors, muddy shadows, blown highlights, "
            "random text, logo, watermark, inconsistent set decoration"
        )

    def _read_manifest(self, project_id: int) -> dict:
        path = self._path(project_id)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) and data.get("status") == "frozen" else {}

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

    @staticmethod
    def _scene_text(scene: Scene | dict | None) -> str:
        if scene is None:
            return ""
        if isinstance(scene, dict):
            values = [
                scene.get("visual_description"),
                scene.get("description"),
                scene.get("image_prompt"),
                scene.get("dialogue"),
                scene.get("shot_role"),
            ]
        else:
            values = [
                getattr(scene, "visual_description", ""),
                getattr(scene, "image_prompt", ""),
                getattr(scene, "dialogue", ""),
            ]
        return " ".join(str(value or "") for value in values).lower()

    def _shot_profile_id(self, text: str, visible_count: int | None) -> str:
        if self._contains_any(text, ("close-up", "close up", "特写", "脸部", "眼神", "哭泣", "凝视")):
            return "close_up"
        if visible_count is not None and visible_count >= 2:
            return "two_shot"
        if self._contains_any(text, ("two-shot", "two shot", "双人", "对峙", "面对面")):
            return "two_shot"
        if self._contains_any(text, ("full body", "head-to-toe", "全身", "从头到脚")):
            return "full_body"
        if self._contains_any(text, ("手机", "信", "纸条", "钥匙", "照片", "杯", "phone", "letter", "note", "key", "photo", "cup")):
            return "prop_interaction"
        if self._contains_any(text, ("哭", "笑", "怒", "震惊", "愣住", "沉默", "reaction", "smile", "cry", "angry", "shock", "stare")):
            return "reaction"
        if self._contains_any(text, ("wide", "全景", "街景", "房间", "办公室", "豪宅", "location", "room", "office")):
            return "establishing"
        return "reaction"

    @staticmethod
    def _contains_any(text: str, terms: Iterable[str]) -> bool:
        return any(term.lower() in text for term in terms)

    @staticmethod
    def _quality_profile() -> str:
        return settings.GENERATION_QUALITY_PROFILE.strip().lower()

    def _profile_prompt(self) -> str:
        return self.PROFILE_AESTHETIC_PROMPTS.get(self._quality_profile(), "")

    def _profile_negative_prompt(self) -> str:
        return self.PROFILE_AESTHETIC_NEGATIVES.get(self._quality_profile(), "")

    def _path(self, project_id: int) -> Path:
        return storage_manager.get_project_path(project_id) / "style" / "visual_style_asset_pack.json"

    @staticmethod
    def _hash(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
