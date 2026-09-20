"""Character identity planning and face-feature scoring.

This service is intentionally model-agnostic: it produces stable role anchors for
ComfyUI/Seedance-like workflows and a measurable rubric before any generator is
trusted with video.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


FACIAL_FIELDS = [
    "face_shape",
    "eyes",
    "eyebrows",
    "nose",
    "mouth",
    "jawline",
    "hair",
    "skin_tone",
    "distinctive_mark",
]


@dataclass(frozen=True)
class ChoiceBank:
    face_shape: tuple[str, ...] = (
        "long oval face with a narrow chin",
        "round face with soft cheeks",
        "square face with a broad forehead",
        "heart-shaped face with a pointed chin",
        "diamond face with high cheekbones",
        "rectangular face with a strong vertical proportion",
    )
    eyes: tuple[str, ...] = (
        "deep-set monolid dark brown eyes",
        "large double-eyelid amber eyes",
        "narrow almond black eyes",
        "slightly downturned hazel eyes",
        "sharp phoenix-shaped dark eyes",
        "round expressive grey-brown eyes",
    )
    eyebrows: tuple[str, ...] = (
        "straight thick brows",
        "arched thin brows",
        "soft natural brows",
        "short angled brows",
        "low flat brows",
        "defined sword-shaped brows",
    )
    nose: tuple[str, ...] = (
        "straight high nose bridge with a small tip",
        "low rounded nose bridge with a soft tip",
        "long narrow nose with defined nostrils",
        "short button nose",
        "slightly aquiline nose",
        "wide nose bridge with a blunt tip",
    )
    mouth: tuple[str, ...] = (
        "thin lips with a firm line",
        "full lips with a soft cupid bow",
        "small mouth with pale natural lips",
        "wide mouth with defined corners",
        "medium lips with a slight asymmetry",
        "heart-shaped lips with a clear upper bow",
    )
    jawline: tuple[str, ...] = (
        "soft rounded jawline",
        "sharp angular jawline",
        "wide square jaw",
        "slender tapered jaw",
        "short compact jaw",
        "long defined jaw",
    )
    hair: tuple[str, ...] = (
        "short black side-parted hair",
        "long dark brown straight hair with center part",
        "shoulder-length wavy chestnut hair",
        "messy black textured crop",
        "neat low ponytail with black hair",
        "short silver-grey bob",
    )
    skin_tone: tuple[str, ...] = (
        "fair warm skin tone",
        "light olive skin tone",
        "medium tan skin tone",
        "cool pale skin tone",
        "deep warm skin tone",
        "freckled light skin tone",
    )
    distinctive_mark: tuple[str, ...] = (
        "small mole under the left eye",
        "faint scar on the right eyebrow",
        "beauty mark near the upper lip",
        "single small ear cuff on the left ear",
        "subtle dimple on the right cheek",
        "no visible marks, clean face",
    )
    wardrobe: tuple[str, ...] = (
        "matte black trench coat over a white shirt",
        "cream knit cardigan with a dark green skirt",
        "navy suit with an open collar",
        "grey hoodie under a worn denim jacket",
        "burgundy silk blouse with black trousers",
        "beige utility jacket with a black turtleneck",
    )


LANGUAGE_HINTS = {
    "zh": "中文提示词优先锁定五官、发型、服装，再描述镜头。",
    "en": "English prompt prioritizes facial geometry, hair, wardrobe, then shot action.",
    "ja": "日本語プロンプトは顔立ち、髪型、衣装、動作の順で固定します。",
    "ko": "한국어 프롬프트는 얼굴 구조, 머리, 의상, 장면 동작 순서로 고정합니다.",
    "es": "El prompt en español fija primero rasgos faciales, cabello y vestuario.",
    "pt": "O prompt em portugues fixa rosto, cabelo, roupa e depois a acao.",
    "ar": "يثبت الوصف العربي ملامح الوجه والشعر والملابس قبل الحركة.",
    "id": "Prompt Indonesia mengunci wajah, rambut, busana, lalu aksi adegan.",
    "th": "พรอมป์ภาษาไทยล็อกใบหน้า ผม เสื้อผ้า แล้วจึงอธิบายการเคลื่อนไหว.",
    "vi": "Prompt tieng Viet co dinh khuon mat, toc, trang phuc roi den hanh dong.",
}


class CharacterIdentityService:
    def __init__(self, bank: ChoiceBank | None = None):
        self.bank = bank or ChoiceBank()

    @staticmethod
    def _seed_int(*parts: Any) -> int:
        raw = "|".join(str(part) for part in parts)
        return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)

    def _pick(self, field: str, base: int, offset: int, used: set[str]) -> str:
        values = getattr(self.bank, field)
        for step in range(len(values)):
            value = values[(base + offset + step) % len(values)]
            token = f"{field}:{value}"
            if token not in used:
                used.add(token)
                return value
        value = values[(base + offset) % len(values)]
        used.add(f"{field}:{value}")
        return value

    def build_identity_spec(
        self,
        name: str,
        role: str = "",
        personality: str = "",
        project_id: int | None = None,
        existing_specs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        existing_specs = existing_specs or []
        used = {
            f"{field}:{spec.get(field)}"
            for spec in existing_specs
            for field in FACIAL_FIELDS
            if spec.get(field)
        }
        base = self._seed_int(project_id or 0, name, role, personality)
        spec = {
            "version": 1,
            "name": name.strip(),
            "role": role.strip() or "short-drama character",
            "personality": personality.strip() or "clear dramatic motivation",
            "age_range": 18 + base % 22,
            "gender_presentation": "unspecified unless provided by script",
        }
        for index, field in enumerate(FACIAL_FIELDS):
            spec[field] = self._pick(field, base, index * 3, used)
        spec["wardrobe"] = self._pick("wardrobe", base, 31, used)
        spec["identity_anchor"] = self.identity_anchor(spec)
        spec["negative_identity"] = (
            "do not merge this character with another role, no face swapping, no random hair color, "
            "no changed eye shape, no changed nose bridge, no changed distinctive mark"
        )
        return spec

    @staticmethod
    def identity_anchor(spec: dict[str, Any]) -> str:
        return (
            f"{spec.get('name', 'Character')}: {spec.get('face_shape')}, {spec.get('eyes')}, "
            f"{spec.get('eyebrows')}, {spec.get('nose')}, {spec.get('mouth')}, "
            f"{spec.get('jawline')}, {spec.get('hair')}, {spec.get('skin_tone')}, "
            f"{spec.get('distinctive_mark')}, wearing {spec.get('wardrobe')}."
        )

    def prompt_pack(self, spec: dict[str, Any], languages: list[str] | None = None) -> dict[str, Any]:
        languages = languages or ["zh", "en", "ja", "ko", "es", "pt", "ar", "id", "th", "vi"]
        anchor = spec.get("identity_anchor") or self.identity_anchor(spec)
        prompts = {}
        for language in languages:
            code = language.lower().strip()
            prompts[code] = {
                "instruction": LANGUAGE_HINTS.get(code, LANGUAGE_HINTS["en"]),
                "reference_portrait": (
                    f"{anchor} Front-facing clean reference portrait, neutral expression, even light, "
                    "plain background, sharp facial landmarks, no dramatic pose."
                ),
                "scene_prefix": (
                    f"Preserve exact identity: {anchor} Expression and pose may change naturally; "
                    "facial geometry, hair, skin tone, mark and wardrobe stay consistent."
                ),
                "negative": spec.get("negative_identity", ""),
            }
        return {"version": 1, "languages": prompts}

    def distinctiveness_report(self, specs: list[dict[str, Any]]) -> dict[str, Any]:
        pairs = []
        for left_index, left in enumerate(specs):
            for right in specs[left_index + 1:]:
                shared = [
                    field for field in FACIAL_FIELDS + ["wardrobe"]
                    if left.get(field) and left.get(field) == right.get(field)
                ]
                total = len(FACIAL_FIELDS) + 1
                distance = round(1 - len(shared) / total, 2)
                pairs.append({
                    "left": left.get("name"),
                    "right": right.get("name"),
                    "distance": distance,
                    "shared_fields": shared,
                    "status": "passed" if distance >= 0.72 else "too_similar",
                })
        status = "passed" if all(pair["status"] == "passed" for pair in pairs) else "needs_revision"
        return {"status": status, "pairs": pairs}

    def identity_contrast_prompt(self, specs: list[dict[str, Any]], max_pairs: int = 4) -> str:
        specs = [spec for spec in specs if isinstance(spec, dict) and spec.get("name")]
        if len(specs) < 2:
            return ""
        contrasts = []
        for left_index, left in enumerate(specs):
            for right in specs[left_index + 1:]:
                differences = [
                    field for field in FACIAL_FIELDS + ["wardrobe"]
                    if left.get(field) and right.get(field) and left.get(field) != right.get(field)
                ][:2]
                if not differences:
                    contrasts.append(
                        f"{left.get('name')} and {right.get('name')} are at risk of same-face casting; regenerate one identity bible."
                    )
                    continue
                detail = ", ".join(
                    f"{field} differs"
                    for field in differences
                )
                contrasts.append(
                    f"{left.get('name')} must not look like {right.get('name')}: {detail}"
                )
                if len(contrasts) >= max_pairs:
                    break
            if len(contrasts) >= max_pairs:
                break
        return (
            "Identity contrast contract: distinct faces; "
            + " | ".join(contrasts)
            + ". No same-face cast."
        )

    def score_observed_spec(self, expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
        scores = {}
        total = 0
        for field in FACIAL_FIELDS + ["wardrobe"]:
            expected_value = str(expected.get(field, "")).strip().lower()
            observed_value = str(observed.get(field, "")).strip().lower()
            if not observed_value:
                score = 0
                evidence = "missing observed value"
            elif expected_value == observed_value:
                score = 5
                evidence = "exact structured match"
            elif expected_value and any(part in observed_value for part in expected_value.split()[:3]):
                score = 3
                evidence = "partial text overlap; needs visual review"
            else:
                score = 1
                evidence = f"expected '{expected.get(field)}', observed '{observed.get(field)}'"
            scores[field] = {"score": score, "evidence": evidence}
            total += score
        average = round(total / len(scores), 2)
        return {
            "status": "passed" if average >= 4 and min(item["score"] for item in scores.values()) >= 3 else "needs_review",
            "average": average,
            "scores": scores,
            "limitation": "Text scoring checks structured feature agreement; generated images still need VLM or human review.",
        }


def load_identity_spec(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and data.get("version") == 1:
        return data
    return None
