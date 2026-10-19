"""Episode-level dialogue audio and subtitle timing delivery audit."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from src.utils.media_quality_paths import (
    existing_audio_quality_report_path,
    existing_subtitle_quality_report_path,
)


_TIMECODE = re.compile(
    r"(?P<start>\d{1,2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})[,.](?P<millis>\d{3})"
    r"\s+-->\s+"
    r"(?P<end>\d{1,2}):(?P<end_minutes>\d{2}):(?P<end_seconds>\d{2})[,.](?P<end_millis>\d{3})"
)


@dataclass(frozen=True)
class DialogueDeliveryAuditReport:
    status: str
    dialogue_scene_count: int
    checked_scene_count: int
    cues_count: int
    issues: list[dict[str, Any]]
    scenes: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "dialogue_delivery_audit",
            "status": self.status,
            "dialogue_scene_count": self.dialogue_scene_count,
            "checked_scene_count": self.checked_scene_count,
            "cues_count": self.cues_count,
            "issue_count": len(self.issues),
            "issues": self.issues,
            "scenes": self.scenes,
            "repair_queue": self._repair_queue(),
        }

    def _repair_queue(self) -> list[dict[str, Any]]:
        if not self.issues:
            return []
        scene_numbers = sorted({
            issue["scene_number"]
            for issue in self.issues
            if isinstance(issue.get("scene_number"), int)
        })
        return [{
            "priority": "high" if self.status == "needs_review" else "medium",
            "stage": "audio",
            "action": "refine_dialogue_audio_delivery",
            "execution": "auto",
            "scene_number": scene_numbers[0] if len(scene_numbers) == 1 else None,
            "reason": "; ".join(issue["code"] for issue in self.issues[:3]),
            "recommendation": "Regenerate dialogue audio, retime subtitles, and rerun the final composition audio gate.",
        }]


class DialogueDeliveryAuditService:
    """Fail closed only once a project has at least one rendered dialogue asset."""

    END_TOLERANCE_SECONDS = 0.25

    def audit(self, scenes: list) -> DialogueDeliveryAuditReport:
        ordered = sorted(scenes or [], key=lambda scene: scene.scene_number)
        dialogue_scenes = [scene for scene in ordered if str(getattr(scene, "dialogue", "") or "").strip()]
        if not dialogue_scenes:
            return DialogueDeliveryAuditReport("not_applicable", 0, 0, 0, [], [])
        has_any_asset = any(
            getattr(scene, "audio_path", None) or getattr(scene, "subtitle_path", None)
            for scene in dialogue_scenes
        )
        if not has_any_asset:
            return DialogueDeliveryAuditReport("not_applicable", len(dialogue_scenes), 0, 0, [], [])

        issues: list[dict[str, Any]] = []
        scene_reports: list[dict[str, Any]] = []
        cues_count = 0
        checked = 0
        voice_by_speaker: dict[str, str] = {}
        voice_scene_by_speaker: dict[str, int] = {}
        for scene in dialogue_scenes:
            number = scene.scene_number
            audio_path = Path(str(getattr(scene, "audio_path", "") or ""))
            subtitle_path = Path(str(getattr(scene, "subtitle_path", "") or ""))
            audio_duration = self._positive_float(getattr(scene, "audio_duration", None))
            report = {
                "scene_number": number,
                "audio_present": audio_path.is_file(),
                "subtitle_present": subtitle_path.is_file(),
                "audio_duration_seconds": audio_duration,
                "subtitle_cues": 0,
            }
            checked += 1
            voice_report = self._read_voice_report(audio_path)
            if audio_path.is_file() and voice_report is None:
                issues.append(self._issue(
                    number,
                    "missing_voice_identity_evidence",
                    "Dialogue audio is present but its voice identity quality report is missing or invalid.",
                ))
            if audio_path.is_file() and voice_report is not None:
                self._audit_audio_evidence(
                    number,
                    scene.dialogue,
                    audio_path,
                    audio_duration,
                    voice_report,
                    issues,
                )
            if voice_report:
                voice_identity = voice_report.get("voice_identity")
                if isinstance(voice_identity, dict):
                    speaker = str(
                        voice_identity.get("requested_speaker")
                        or getattr(scene, "character_name", None)
                        or voice_identity.get("speaker")
                        or "default"
                    ).strip() or "default"
                    voice_id = str(voice_identity.get("voice_id") or "").strip()
                    if voice_id:
                        report["speaker"] = speaker
                        report["voice_id"] = voice_id
                        previous_voice = voice_by_speaker.get(speaker)
                        if previous_voice and previous_voice != voice_id:
                            issues.append(self._issue(
                                number,
                                "inconsistent_voice_identity",
                                f"Speaker {speaker} uses voice {voice_id}, but scene "
                                f"{voice_scene_by_speaker[speaker]} uses {previous_voice}.",
                            ))
                        else:
                            voice_by_speaker[speaker] = voice_id
                            voice_scene_by_speaker[speaker] = number
            if not audio_path.is_file():
                issues.append(self._issue(number, "missing_dialogue_audio", "Dialogue scene has no readable audio asset."))
            if audio_duration is None:
                issues.append(self._issue(number, "missing_audio_duration", "Dialogue audio duration is missing or invalid."))
            if not subtitle_path.is_file():
                issues.append(self._issue(number, "missing_subtitles", "Dialogue scene has no readable subtitle asset."))
                scene_reports.append(report)
                continue
            subtitle_quality = self._read_subtitle_report(subtitle_path)
            if subtitle_quality is None:
                issues.append(self._issue(
                    number,
                    "missing_subtitle_quality_evidence",
                    "Subtitle is present but its quality sidecar is missing or invalid.",
                ))
            cues = self._parse_srt(subtitle_path)
            report["subtitle_cues"] = len(cues)
            cues_count += len(cues)
            if subtitle_quality is not None:
                if subtitle_quality.get("status") != "passed":
                    issues.append(self._issue(
                        number,
                        "subtitle_quality_gate_failed",
                        "Subtitle quality gate did not pass.",
                    ))
                expected_text = subtitle_quality.get("expected_text")
                if not isinstance(expected_text, str) or self._normalize_text(expected_text) != self._normalize_text(scene.dialogue):
                    issues.append(self._issue(
                        number,
                        "stale_subtitle_dialogue_evidence",
                        "Subtitle quality evidence is bound to different dialogue text.",
                    ))
                try:
                    subtitle_hash = hashlib.sha256(subtitle_path.read_bytes()).hexdigest()
                except OSError:
                    subtitle_hash = None
                if subtitle_quality.get("subtitle_sha256") != subtitle_hash:
                    issues.append(self._issue(
                        number,
                        "stale_subtitle_file_evidence",
                        "Subtitle quality evidence does not match the current subtitle file.",
                    ))
            if not cues:
                issues.append(self._issue(number, "empty_subtitles", "Subtitle file contains no timed dialogue cues."))
                scene_reports.append(report)
                continue
            for previous, current in zip(cues, cues[1:]):
                if current["start"] < previous["end"]:
                    issues.append(self._issue(number, "overlapping_subtitles", "Subtitle cues overlap and can obscure dialogue timing."))
                    break
            if audio_duration is not None and cues[-1]["end"] > audio_duration + self.END_TOLERANCE_SECONDS:
                issues.append(self._issue(
                    number,
                    "subtitle_past_audio",
                    f"Last subtitle ends at {cues[-1]['end']:.2f}s, beyond audio duration {audio_duration:.2f}s.",
                ))
            report["first_cue_seconds"] = round(cues[0]["start"], 3)
            report["last_cue_seconds"] = round(cues[-1]["end"], 3)
            scene_reports.append(report)
        status = "needs_review" if any(issue["severity"] == "high" for issue in issues) else ("warn" if issues else "passed")
        return DialogueDeliveryAuditReport(status, len(dialogue_scenes), checked, cues_count, issues, scene_reports)

    def _read_voice_report(self, audio_path: Path) -> dict[str, Any] | None:
        if not audio_path.is_file():
            return None
        report_path = existing_audio_quality_report_path(audio_path)
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _read_subtitle_report(self, subtitle_path: Path) -> dict[str, Any] | None:
        report_path = existing_subtitle_quality_report_path(subtitle_path)
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _audit_audio_evidence(
        self,
        scene_number: int,
        dialogue: str,
        audio_path: Path,
        audio_duration: float | None,
        report: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> None:
        gate = report.get("dialogue_audio_quality_gate")
        if not isinstance(gate, dict) or gate.get("status") != "passed":
            issues.append(self._issue(
                scene_number,
                "dialogue_audio_quality_gate_failed",
                "Dialogue audio quality gate is missing or did not pass.",
            ))
        expected_fingerprint = hashlib.sha256(
            " ".join(str(dialogue or "").split()).encode("utf-8")
        ).hexdigest()
        if report.get("dialogue_fingerprint") != expected_fingerprint:
            issues.append(self._issue(
                scene_number,
                "stale_dialogue_audio_evidence",
                "Dialogue audio quality evidence is bound to different dialogue text.",
            ))
        try:
            audio_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
        except OSError:
            audio_hash = None
        if report.get("audio_sha256") != audio_hash:
            issues.append(self._issue(
                scene_number,
                "stale_dialogue_audio_file_evidence",
                "Dialogue audio quality evidence does not match the current audio file.",
            ))
        signal = report.get("audio_signal")
        if not isinstance(signal, dict) or signal.get("audio_signal_status") != "usable":
            issues.append(self._issue(
                scene_number,
                "unusable_dialogue_audio_signal",
                "Dialogue audio has no usable decoded signal evidence.",
            ))
        measured_duration = self._positive_float(report.get("duration_measured"))
        if audio_duration is not None and measured_duration is not None and abs(audio_duration - measured_duration) > self.END_TOLERANCE_SECONDS:
            issues.append(self._issue(
                scene_number,
                "stale_dialogue_audio_duration",
                f"Scene audio duration {audio_duration:.2f}s disagrees with measured report duration {measured_duration:.2f}s.",
            ))

    def _parse_srt(self, path: Path) -> list[dict[str, Any]]:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            return []
        cues = []
        for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            match = next(
                (candidate for line in lines if (candidate := _TIMECODE.search(line))),
                None,
            )
            if not match:
                continue
            try:
                start = self._seconds(match, "start")
                end = self._seconds(match, "end")
            except ValueError:
                continue
            cues.append({"start": start, "end": end})
        return sorted((cue for cue in cues if cue["end"] >= cue["start"]), key=lambda cue: cue["start"])

    def _seconds(self, match, prefix: str) -> float:
        if prefix == "start":
            hours = int(match.group("start"))
            minutes = int(match.group("minutes"))
            seconds = int(match.group("seconds"))
            millis = int(match.group("millis"))
        else:
            hours = int(match.group("end"))
            minutes = int(match.group("end_minutes"))
            seconds = int(match.group("end_seconds"))
            millis = int(match.group("end_millis"))
        if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
            raise ValueError("invalid SRT timecode range")
        return hours * 3600 + minutes * 60 + seconds + millis / 1000

    def _positive_float(self, value) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if result > 0 else None

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").lower())

    def _issue(self, scene_number: int, code: str, message: str) -> dict[str, Any]:
        return {
            "severity": "high",
            "code": code,
            "scene_number": scene_number,
            "message": message,
            "recommendation": "Regenerate dialogue audio and retime subtitles before delivery.",
        }
