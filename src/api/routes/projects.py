"""
项目管理 API 路由

提供项目的 CRUD 操作和剧本生成功能
"""

from fastapi import APIRouter, HTTPException, status, Query, Depends, UploadFile, File
from typing import Optional
from pathlib import Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import shutil
import json
import os
from datetime import datetime, timedelta, timezone

from src.api.schemas import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    GenerateScriptRequest,
    RegenerateSceneRequest,
    RepairQueueAutoRunRequest,
    RepairQueueAutoRunResponse,
    RepairSceneRequest,
    MessageResponse,
    ProductionTaskResponse,
    SpatialAssetFreezeRequest,
    SpatialAssetPackResponse,
    VisualStyleFreezeRequest,
    VisualStyleAssetPackResponse,
    WorkflowProfileFreezeRequest,
    WorkflowProfileResponse,
    HumanReviewDecisionRequest,
)
from src.api.dependencies import get_current_user, require_project_access
from src.services.project_manager import ProjectManager, get_project_manager
from src.services.script_generator import ScriptGenerator, ScriptParseError, get_script_generator
from src.services.task_orchestrator import TaskOrchestrator, get_task_orchestrator
from src.services.production_readiness import ProductionReadinessService
from src.services.spatial_control_assets import SpatialControlAssetService
from src.services.visual_style_assets import VisualStyleAssetService
from src.services.production_workflow_profile import ProductionWorkflowProfileService
from src.services.quality_loop import build_quality_loop_plan
from src.services.repair_queue import repair_execution_mode
from src.services.repair_plan import build_repair_execution_plan
from src.services.generation_quality_scorecard import build_generation_quality_scorecard
from src.services.generation_review import file_hash, require_passed
from src.services.story_room_quality import StoryRoomQualityService
from src.services.delivery_package import DeliveryPackageError, build_delivery_package, verify_delivery_package
from src.services.topic_brief import TopicBriefService
from src.services.platform_export import PLATFORM_EXPORT_PRESETS, PlatformExportError, export_platform_video
from src.services.repair_budget import RepairBudget
from src.services.repair_cycle import RepairCycleStore
from src.services.human_review import HumanReviewStore
from src.services.continuity_audit import ContinuityAuditService
from src.services.rhythm_audit import RhythmAuditService
from src.services.episode_style_consistency import EpisodeStyleConsistencyService
from src.services.character_identity_consistency import CharacterIdentityConsistencyService
from src.services.dialogue_delivery_audit import DialogueDeliveryAuditService
from src.services.generation_context_audit import GenerationContextAuditService
from src.services.atomic_video_motion_audit import AtomicVideoMotionAuditService
from src.services.first_frame_consistency_audit import FirstFrameConsistencyAuditService
from src.database.session import get_db_session
from src.database.models import Character, Project, ProjectStatus, Scene
from src.services.llm_service import get_llm_service
from src.config import settings
from src.services.generation_provider import (
    _seedance_api_format,
    _seedance_duration_bounds,
    _seedance_model,
    _seedance_model_is_10,
    _seedance_model_is_25,
    _seedance_model_supports_first_last_frame,
    _seedance_supported_resolutions,
)
from src.utils.logger import get_logger
from src.utils.storage import storage_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["项目管理"], dependencies=[Depends(require_project_access)])


def _video_version_signature(path: Path) -> str | None:
    """Return a cheap version marker for invalidating media-based reviews."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"

class SeedDanceBaselineRequest(BaseModel):
    baseline_path: str
    candidate_path: Optional[str] = None


class ProductionOptions(BaseModel):
    """Per-run video engine overrides; omitted fields keep environment defaults."""
    provider: Optional[str] = None
    request_mode: Optional[str] = None
    multi_shot: Optional[bool] = None
    sequence_level_multi_shot: Optional[bool] = None
    native_audio: Optional[bool] = None
    draft: Optional[bool] = None
    draft_task_id: Optional[str] = None
    model: Optional[str] = None
    resolution: Optional[str] = None
    output_format: Optional[str] = None
    return_last_frame: Optional[bool] = None
    camera_fixed: Optional[bool] = None
    watermark: Optional[bool] = None
    duration_seconds: Optional[float] = None
    add_bgm: bool = False
    bgm_path: Optional[str] = None
    bgm_volume: float = Field(0.3, ge=0.0, le=1.0)


class TopicBriefRequest(BaseModel):
    audience: str = Field(..., min_length=2, max_length=240)
    platform: str = Field(..., min_length=2, max_length=240)
    genre: str = Field(..., min_length=2, max_length=240)
    hook_type: str = Field(..., min_length=2, max_length=240)
    region: str = Field(..., min_length=2, max_length=240)
    policy_notes: str = Field("", max_length=240)


class MarketSignalsRequest(BaseModel):
    comparables: list[dict | str] = Field(..., min_length=1, max_length=12)
    differentiation: str = Field("", max_length=500)
    success_metric: str = Field("", max_length=500)
    notes: str = Field("", max_length=500)


def _normalized_production_options(options: ProductionOptions) -> dict:
    """Validate and normalize per-run controls before reserving a task."""
    request_mode = options.request_mode.strip().lower() if isinstance(options.request_mode, str) else options.request_mode
    resolution = options.resolution.strip().lower() if isinstance(options.resolution, str) else options.resolution
    output_format = options.output_format.strip().lower() if isinstance(options.output_format, str) else options.output_format
    valid_modes = {
        "reference", "reference_to_video", "auto", "multi_shot", "seedance_2_5", "2.5",
        "first_frame", "first_last_frame", "edit", "extend",
    }
    if request_mode is not None and request_mode not in valid_modes:
        raise HTTPException(
            status_code=422,
            detail=(
                "request_mode must be one of reference, reference_to_video, auto, multi_shot, "
                "seedance_2_5, 2.5, first_frame, first_last_frame, edit, or extend"
            ),
        )
    if resolution is not None and resolution not in {"480p", "720p", "1080p", "4k"}:
        raise HTTPException(status_code=422, detail="resolution must be one of 480p, 720p, 1080p, or 4k")
    configured_provider = (
        options.provider.strip().lower()
        if isinstance(options.provider, str) and options.provider.strip()
        else str(os.getenv("GENERATION_PROVIDER") or getattr(settings, "GENERATION_PROVIDER", "") or "").strip().lower()
    )
    configured_model = _seedance_model(model=options.model).strip().lower()
    configured_endpoint = str(
        os.getenv("SEEDANCE_ENDPOINT")
        or getattr(settings, "SEEDANCE_ENDPOINT", "")
        or ""
    ).strip()
    native_ark = _seedance_api_format(configured_endpoint) in {
        "ark", "ark_v3", "volcengine", "volcengine_v3",
    }
    if configured_provider == "seedance_api" and native_ark:
        supported_resolutions = _seedance_supported_resolutions(configured_model)
        if resolution is not None and resolution not in supported_resolutions:
            limit_hint = " Native Seedance 2.5 supports up to 1080p." if _seedance_model_is_25(configured_model) else ""
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{configured_model} does not support {resolution}; use one of "
                    f"{', '.join(sorted(supported_resolutions))}.{limit_hint}"
                ),
            )
        if (
            request_mode in {"edit", "extend"}
            and _seedance_model_is_10(configured_model)
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Native Seedance model {configured_model} does not support "
                    f"{request_mode} tasks; use Seedance 2.0 or 2.5."
                ),
            )
        if request_mode == "auto" and not _seedance_model_is_25(configured_model):
            raise HTTPException(
                status_code=422,
                detail="Native Seedance omni_reference_task_type=auto requires Seedance 2.5.",
            )
        if request_mode == "first_frame" and not (
            _seedance_model_is_10(configured_model) or _seedance_model_is_25(configured_model)
        ):
            raise HTTPException(
                status_code=422,
                detail="Native Seedance explicit first_frame mode requires Seedance 1.0 or 2.5.",
            )
        if request_mode == "first_last_frame" and not _seedance_model_supports_first_last_frame(configured_model):
            raise HTTPException(
                status_code=422,
                detail=f"Native Seedance first_last_frame mode is not supported by {configured_model}.",
            )
        if (
            request_mode in {"first_frame", "first_last_frame"}
            and _seedance_model_is_25(configured_model)
            and not options.draft
        ):
            raise HTTPException(
                status_code=422,
                detail="Seedance 2.5 first_frame/first_last_frame mode requires draft=true; promote the Draft task for final output.",
            )
        if options.duration_seconds is not None:
            minimum_duration, maximum_duration = _seedance_duration_bounds(configured_model, request_mode)
            if not minimum_duration <= options.duration_seconds <= maximum_duration:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{configured_model} duration must be between "
                        f"{minimum_duration} and {maximum_duration} seconds."
                    ),
                    )
            if (
                _seedance_model_is_25(configured_model)
                and request_mode in {"edit", "extend"}
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Native Seedance 2.5 edit/extend tasks require automatic duration (-1); clear duration_seconds.",
                )
    if (
        resolution == "4k"
        and configured_provider == "seedance_api"
        and native_ark
        and _seedance_model_is_25(configured_model)
    ):
        raise HTTPException(
            status_code=422,
            detail="Seedance 2.5 native Ark supports up to 1080p; use 1080p or configure a 2.0/compatible 4K provider.",
        )
    if (
        output_format == "mov"
        and configured_provider == "seedance_api"
        and native_ark
        and not _seedance_model_is_25(configured_model)
    ):
        raise HTTPException(
            status_code=422,
            detail="Native Ark MOV output requires Seedance 2.5; use MP4 for Seedance 2.0/1.0.",
        )
    if (
        (options.draft or options.draft_task_id)
        and configured_provider == "seedance_api"
        and native_ark
        and not _seedance_model_is_25(configured_model)
    ):
        raise HTTPException(
            status_code=422,
            detail="Native Ark Draft generation and promotion require Seedance 2.5; choose a 2.5 model.",
        )
    if output_format is not None and output_format not in {"mp4", "mov"}:
        raise HTTPException(status_code=422, detail="output_format must be mp4 or mov")
    if options.duration_seconds is not None and not 1 <= options.duration_seconds <= 30:
        raise HTTPException(status_code=422, detail="duration_seconds must be between 1 and 30")
    if options.multi_shot and request_mode in {"edit", "extend"}:
        raise HTTPException(status_code=422, detail="multi_shot cannot be combined with edit or extend mode")
    if options.sequence_level_multi_shot and not (options.multi_shot or request_mode in {"multi_shot", "seedance_2_5", "2.5"}):
        raise HTTPException(status_code=422, detail="sequence_level_multi_shot requires multi_shot mode")
    if options.sequence_level_multi_shot and request_mode in {"edit", "extend"}:
        raise HTTPException(status_code=422, detail="sequence_level_multi_shot cannot be combined with edit or extend mode")
    if options.draft and options.draft_task_id:
        raise HTTPException(status_code=422, detail="draft and draft_task_id cannot be used together")
    return {
        "resolution": resolution,
        "output_format": output_format,
        "return_last_frame": options.return_last_frame,
        "camera_fixed": options.camera_fixed,
        "watermark": options.watermark,
        "duration_seconds": options.duration_seconds,
        "sequence_level_multi_shot": options.sequence_level_multi_shot,
    }


def _draft_expired(created_at: object, expires_at: object = None, *, now: datetime | None = None) -> bool:
    """Seedance Draft tasks are promotable for seven days after creation."""
    def parse_time(raw: object) -> datetime | None:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        if not isinstance(raw, str):
            return None
        try:
            value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    reference = now or datetime.now(timezone.utc)
    explicit_expiry = parse_time(expires_at)
    if explicit_expiry is not None:
        return reference >= explicit_expiry
    value = parse_time(created_at)
    if value is None:
        return False
    return reference - value > timedelta(days=7)


@router.post("/workflow-profile/freeze", response_model=WorkflowProfileResponse)
async def freeze_workflow_profile(
    request: WorkflowProfileFreezeRequest,
    current_user=Depends(get_current_user),
):
    try:
        profile = ProductionWorkflowProfileService().freeze_profile(
            capabilities=request.capabilities,
            notes=request.notes or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return WorkflowProfileResponse(status=profile["status"], profile=profile)


def _production_error_status(message: str) -> int:
    if "正在制作" in message or "IN_PRODUCTION" in message:
        return status.HTTP_409_CONFLICT
    if (
        "Production video engine is not ready" in message
        or "Short-drama production requires" in message
        or "项目不存在" in message
        or "项目没有分镜" in message
        or "分镜不存在" in message
        or "不支持的返工动作" in message
        or "返工需要" in message
        or "workflow profile" in message
        or "workflow_profile" in message
        or "生产 workflow profile" in message
        or "请先" in message
        or "短剧" in message
        or "not ready" in message
    ):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_500_INTERNAL_SERVER_ERROR


@router.post("/{project_id}/seed-dance-baseline")
async def compare_seed_dance_baseline(
    project_id: int,
    request: SeedDanceBaselineRequest,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.database.models import Project
    from src.services.generation_review import write_report
    from src.utils.storage import storage_manager

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    candidate = Path(request.candidate_path or project.final_video_path or "")
    baseline = Path(request.baseline_path)
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="Candidate video does not exist; generate the project video first")
    if not baseline.is_file():
        raise HTTPException(status_code=400, detail="Seed Dance baseline video does not exist")

    review_root = storage_manager.get_project_path(project_id) / "reviews"
    from scripts.compare_video_baseline import compare
    report = compare(candidate, baseline, artifact_dir=review_root)
    report["candidate_video_path"] = str(candidate)
    report["baseline_video_path"] = str(baseline)
    report["candidate_signature"] = _video_version_signature(candidate)
    report["baseline_signature"] = _video_version_signature(baseline)
    report["candidate_sha256"] = file_hash(candidate)
    report["baseline_sha256"] = file_hash(baseline)
    write_report(review_root / "seed_dance_baseline_comparison.json", report)
    return report


@router.post("/{project_id}/seed-dance-baseline/upload")
async def upload_seed_dance_baseline(
    project_id: int,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.database.models import Project
    from src.services.generation_review import write_report
    from src.utils.storage import storage_manager
    from scripts.compare_video_baseline import compare

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    candidate = Path(project.final_video_path or "")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="Candidate video does not exist; generate the project video first")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Baseline must be a video file")

    from scripts.compare_video_baseline import compare

    review_root = storage_manager.get_project_path(project_id) / "reviews"
    baseline_dir = review_root / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline = baseline_dir / f"seed_dance_baseline{suffix}"
    with baseline.open("wb") as stream:
        shutil.copyfileobj(file.file, stream)
    if baseline.stat().st_size <= 0:
        baseline.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Baseline video is empty")

    report = compare(candidate, baseline, artifact_dir=review_root)
    report["candidate_video_path"] = str(candidate)
    report["baseline_video_path"] = str(baseline)
    report["uploaded_baseline_path"] = str(baseline)
    report["candidate_signature"] = _video_version_signature(candidate)
    report["baseline_signature"] = _video_version_signature(baseline)
    report["candidate_sha256"] = file_hash(candidate)
    report["baseline_sha256"] = file_hash(baseline)
    write_report(review_root / "seed_dance_baseline_comparison.json", report)
    return report



@router.get("/video-engine/preflight")
async def get_video_engine_preflight(current_user=Depends(get_current_user)):
    from src.services.video_engine_preflight import preflight_production_video_engine
    return preflight_production_video_engine()


@router.get("/{project_id}/generation-review")
async def get_generation_review(
    project_id: int,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    import json
    from src.database.models import Project
    from src.utils.storage import storage_manager
    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    root = storage_manager.get_project_path(project_id) / "reviews"
    reports = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*.json"))
        if path.name != "human_decisions.json"
    }
    project_root = storage_manager.get_project_path(project_id)
    for path in sorted(project_root.rglob("*.quality.json")):
        try:
            key = "quality_" + "_".join(path.relative_to(project_root).with_suffix("").parts)
            reports[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            logger.warning("Cannot read quality report: {}", path)
    final_video_path = getattr(project, "final_video_path", None)
    if final_video_path:
        composition_report_path = Path(final_video_path).with_suffix(".composition_review.json")
        try:
            if composition_report_path.is_file():
                reports["final_composition"] = json.loads(composition_report_path.read_text(encoding="utf-8"))
            else:
                # A final file without its matching review is not auditable.
                # Keep this synthetic report in the response so every delivery
                # surface fails closed instead of treating missing evidence as
                # an implicit pass.
                reports["final_composition"] = {
                    "kind": "final_composition",
                    "status": "needs_review",
                    "video_path": str(final_video_path),
                    "error": "Final composition review evidence is missing.",
                }
        except (OSError, TypeError, ValueError):
            logger.warning("Cannot read composition quality report: {}", composition_report_path)
            reports["final_composition"] = {
                "kind": "final_composition",
                "status": "needs_review",
                "video_path": str(final_video_path),
                "error": "Final composition review evidence could not be read.",
            }
    from src.tasks.review_tasks import (
        current_story,
        generation_signature,
        validate_generation_review_coverage,
        validate_generation_review_evidence,
        validate_story_review_coverage,
    )
    from src.tasks.composition_tasks import composition_input_signature
    from src.services.task_recovery import load_production_video_options
    from src.services.generation_review import fingerprint, write_report
    continuity_report = ContinuityAuditService().audit(project, getattr(project, "scenes", []) or []).to_dict()
    if continuity_report.get("status") != "not_applicable":
        reports["continuity_audit"] = continuity_report
    rhythm_report = RhythmAuditService().audit(project, getattr(project, "scenes", []) or []).to_dict()
    if rhythm_report.get("status") != "not_applicable":
        reports["rhythm_audit"] = rhythm_report
    audit_scenes = sorted(getattr(project, "scenes", []) or [], key=lambda scene: scene.scene_number)
    audit_input_hash = fingerprint({
        "project_id": project_id,
        "scenes": [
            {
                "scene_number": scene.scene_number,
                "visual_description": getattr(scene, "visual_description", None),
                "dialogue": getattr(scene, "dialogue", None),
                "character_name": getattr(scene, "character_name", None),
                "location": getattr(scene, "location", None),
                "audio_duration": getattr(scene, "audio_duration", None),
                "image_signature": _video_version_signature(Path(scene.image_path)) if getattr(scene, "image_path", None) else None,
                "video_signature": _video_version_signature(Path(scene.video_path)) if getattr(scene, "video_path", None) else None,
            }
            for scene in audit_scenes
        ],
    })
    style_report = EpisodeStyleConsistencyService().audit(project, audit_scenes).to_dict()
    if style_report.get("status") != "not_applicable":
        style_report["input_hash"] = audit_input_hash
        style_report["evidence_schema_version"] = 1
        reports["episode_style_consistency"] = style_report
        write_report(root / "episode_style_consistency.json", style_report)
    identity_report = CharacterIdentityConsistencyService().audit(audit_scenes, reports).to_dict()
    if identity_report.get("status") != "not_applicable":
        identity_report["input_hash"] = audit_input_hash
        identity_report["evidence_schema_version"] = 1
        reports["character_identity_consistency"] = identity_report
        write_report(root / "character_identity_consistency.json", identity_report)
    dialogue_report = DialogueDeliveryAuditService().audit(audit_scenes).to_dict()
    if dialogue_report.get("status") != "not_applicable":
        dialogue_report["input_hash"] = audit_input_hash
        dialogue_report["evidence_schema_version"] = 1
        reports["dialogue_delivery_audit"] = dialogue_report
        write_report(root / "dialogue_delivery_audit.json", dialogue_report)
    context_report = GenerationContextAuditService().audit(audit_scenes, reports).to_dict()
    if context_report.get("status") != "not_applicable":
        context_report["input_hash"] = audit_input_hash
        context_report["evidence_schema_version"] = 1
        reports["generation_context_audit"] = context_report
        write_report(root / "generation_context_audit.json", context_report)
    motion_report = AtomicVideoMotionAuditService().audit(audit_scenes).to_dict()
    if motion_report.get("status") != "not_applicable":
        motion_report["input_hash"] = audit_input_hash
        motion_report["evidence_schema_version"] = 1
        reports["atomic_video_motion_audit"] = motion_report
        write_report(root / "atomic_video_motion_audit.json", motion_report)
    first_frame_report = FirstFrameConsistencyAuditService().audit(audit_scenes).to_dict()
    if first_frame_report.get("status") != "not_applicable":
        first_frame_report["input_hash"] = audit_input_hash
        first_frame_report["evidence_schema_version"] = 1
        reports["first_frame_consistency_audit"] = first_frame_report
        write_report(root / "first_frame_consistency_audit.json", first_frame_report)
    story_room_report = StoryRoomQualityService().evaluate(project, audit_scenes).to_dict()
    # The readiness gate owns story-room rewrite actions. Keep the report for
    # reproducibility, but do not enqueue the same actions a second time in the
    # media-generation repair queue.
    story_room_report["repair_queue"] = []
    story_room_report["input_hash"] = audit_input_hash
    story_room_report["evidence_schema_version"] = 1
    reports["story_room_quality"] = story_room_report
    write_report(root / "story_room_quality.json", story_room_report)
    for audit_key in (
        "continuity_audit",
        "rhythm_audit",
        "episode_style_consistency",
        "character_identity_consistency",
        "dialogue_delivery_audit",
        "generation_context_audit",
        "atomic_video_motion_audit",
        "first_frame_consistency_audit",
    ):
        audit_report = reports.get(audit_key)
        if isinstance(audit_report, dict):
            audit_report["input_hash"] = audit_input_hash
            audit_report["evidence_schema_version"] = 1
            write_report(root / f"{audit_key}.json", audit_report)
    human_decisions = HumanReviewStore(project_id).apply(reports)
    for name in ("production_story", "generation"):
        report = reports.get(name)
        if report and report.get("status") == "passed":
            try:
                scenes = sorted(project.scenes, key=lambda scene: scene.scene_number)
                expected = fingerprint(current_story(project, scenes)) if name == "production_story" else generation_signature(project, scenes)
                if report.get("input_hash") != expected:
                    report["status"] = "stale"
            except (OSError, TypeError, ValueError):
                report["status"] = "stale"
    story_report = reports.get("production_story")
    if isinstance(story_report, dict) and story_report.get("status") == "passed":
        coverage = validate_story_review_coverage(story_report, audit_scenes)
        story_report["scene_coverage"] = coverage
        if not coverage["passed"]:
            story_report["status"] = "needs_review"
            story_report["error"] = (
                "Story review does not cover every scene: "
                f"missing={coverage['missing']}, duplicate={coverage['duplicate']}, "
                f"unexpected={coverage['unexpected']}"
            )
    generation_report = reports.get("generation")
    if isinstance(generation_report, dict) and generation_report.get("status") == "passed":
        coverage = validate_generation_review_coverage(generation_report, audit_scenes)
        generation_report["scene_coverage"] = coverage
        if not coverage["passed"]:
            generation_report["status"] = "needs_review"
            generation_report["error"] = (
                "Generation review does not cover every scene: "
                f"missing={coverage['missing']}, duplicate={coverage['duplicate']}, "
                f"unexpected={coverage['unexpected']}, not_passed={coverage['not_passed']}"
            )
        evidence = validate_generation_review_evidence(generation_report, audit_scenes)
        generation_report["evidence"] = evidence
        if not evidence["passed"]:
            generation_report["status"] = "needs_review"
            generation_report["error"] = (
                "Generation review evidence is missing or stale: "
                f"missing={evidence['missing']}, invalid={evidence['invalid']}"
            )
    baseline_report = reports.get("seed_dance_baseline_comparison")
    if isinstance(baseline_report, dict) and baseline_report.get("status") == "passed":
        candidate_path = Path(
            baseline_report.get("candidate_video_path")
            or getattr(project, "final_video_path", None)
            or ""
        )
        baseline_path = Path(baseline_report.get("baseline_video_path") or "")
        active_candidate = str(getattr(project, "final_video_path", None) or "")
        gates = baseline_report.get("gates")
        score = baseline_report.get("score")
        minimum_score = baseline_report.get("min_score")
        required_baseline_gates = {
            "sufficient_temporal_samples",
            "duration_close",
            "fps_close",
            "pixel_format_not_lower",
            "resolution_not_lower",
            "aspect_ratio_close",
            "motion_not_static",
            "sharpness_not_collapsed",
            "exposure_close",
            "brightness_stable",
            "no_prolonged_static_run",
            "no_prolonged_black_run",
            "black_frame_ratio_acceptable",
            "no_temporal_exposure_jumps",
            "stable_motion_cadence",
            "no_temporal_visual_resets",
            "no_extreme_temporal_visual_reset",
            "audio_presence_matches",
            "audio_duration_close",
            "audio_signal_usable",
            "audio_not_clipped",
            "audio_start_aligned",
            "audio_level_close",
            "audio_rms_close",
            "visual_structure_reference_available",
            "visual_structure_not_diverged",
        }
        report_evidence_invalid = (
            baseline_report.get("kind") != "seed_dance_baseline_comparison"
            or not isinstance(gates, dict)
            or not required_baseline_gates.issubset(gates)
            or any(gates.get(name) is not True for name in required_baseline_gates)
            or not isinstance(score, (int, float))
            or not isinstance(minimum_score, (int, float))
            or score < minimum_score
        )
        if (
            report_evidence_invalid
            or not active_candidate
            or str(candidate_path.resolve()) != str(Path(active_candidate).resolve())
            or not baseline_report.get("candidate_signature")
            or _video_version_signature(candidate_path) != baseline_report.get("candidate_signature")
            or not baseline_report.get("baseline_signature")
            or _video_version_signature(baseline_path) != baseline_report.get("baseline_signature")
            or not baseline_report.get("candidate_sha256")
            or file_hash(candidate_path) != baseline_report.get("candidate_sha256")
            or not baseline_report.get("baseline_sha256")
            or file_hash(baseline_path) != baseline_report.get("baseline_sha256")
        ):
            baseline_report["status"] = "stale"
    final_composition = reports.get("final_composition")
    manual_final_approval = (
        isinstance(final_composition, dict)
        and final_composition.get("status") in {"needs_review", "review_unavailable"}
        and isinstance(final_composition.get("human_decision"), dict)
        and final_composition["human_decision"].get("decision") == "approved"
    )
    if isinstance(final_composition, dict) and (
        final_composition.get("status") == "passed" or manual_final_approval
    ):
        active_final_path = Path(getattr(project, "final_video_path", None) or "")
        reviewed_final_path = Path(final_composition.get("video_path") or "")
        final_technical_metrics = final_composition.get("final_technical_metrics")
        production_options = load_production_video_options(project_id) or {}
        expected_composition_input = composition_input_signature(
            project,
            audit_scenes,
            add_bgm=bool(production_options.get("add_bgm")),
            bgm_path=production_options.get("bgm_path"),
            bgm_volume=float(production_options.get("bgm_volume", 0.3)),
        )
        if (
            not active_final_path.is_file()
            or not isinstance(final_technical_metrics, dict)
            or final_technical_metrics.get("status") != "available"
            or final_technical_metrics.get("temporal_sample_evidence") != "sufficient"
            or not final_composition.get("video_signature")
            or not isinstance(final_composition.get("video_sha256"), str)
            or final_composition.get("video_sha256") != file_hash(active_final_path)
            or final_composition.get("composition_input_signature") != expected_composition_input
            or str(reviewed_final_path.resolve()) != str(active_final_path.resolve())
            or _video_version_signature(active_final_path) != final_composition.get("video_signature")
        ):
            final_composition["status"] = "stale"
    summary = _generation_review_summary(reports, repair_output=root)
    summary["repair_cycles"] = RepairCycleStore(project_id).recent(5)
    return {"project_id": project_id, "reports": reports, "summary": summary, "human_decisions": human_decisions}


@router.post("/{project_id}/human-review")
async def record_human_review(
    project_id: int,
    request: HumanReviewDecisionRequest,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    review = await get_generation_review(project_id, current_user, db_session)
    report = review["reports"].get(request.report_key)
    if not isinstance(report, dict):
        raise HTTPException(status_code=404, detail="审核报告不存在")
    try:
        decision = HumanReviewStore(project_id).record(
            request.report_key,
            request.decision,
            request.note,
            report,
            getattr(current_user, "id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"project_id": project_id, "decision": decision}


@router.post("/{project_id}/delivery-package")
async def create_delivery_package(
    project_id: int,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """Export the approved final video together with reproducible QA evidence."""
    from src.utils.storage import storage_manager

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    review = await get_generation_review(project_id, current_user, db_session)
    try:
        return build_delivery_package(
            project,
            storage_manager.get_project_path(project_id),
            review["reports"],
            review["summary"],
        )
    except DeliveryPackageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{project_id}/delivery-package/verify")
async def verify_project_delivery_package(
    project_id: int,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """Verify the published delivery ZIP and its embedded evidence hashes."""
    from src.utils.storage import storage_manager

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    package_path = storage_manager.get_project_path(project_id) / "delivery" / "delivery_package.zip"
    result = verify_delivery_package(package_path)
    if result.get("status") != "passed":
        raise HTTPException(status_code=409, detail=result)
    return result


@router.get("/{project_id}/platform-export-presets")
def list_platform_export_presets(project_id: int, current_user=Depends(get_current_user), db_session: Session = Depends(get_db_session)):
    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"presets": [{"id": key, **value} for key, value in PLATFORM_EXPORT_PRESETS.items()]}


@router.post("/{project_id}/platform-export/{preset}")
async def create_platform_export(
    project_id: int,
    preset: str,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.utils.storage import storage_manager

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    review = await get_generation_review(project_id, current_user, db_session)
    if review["summary"].get("status") != "ready":
        raise HTTPException(status_code=409, detail="质量审核尚未 ready，不能导出平台版本")
    try:
        return export_platform_video(
            project.final_video_path,
            storage_manager.get_project_path(project_id),
            preset,
            approval_report=review["reports"].get("final_composition"),
        )
    except PlatformExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{project_id}/topic-brief")
def get_topic_brief(project_id: int, current_user=Depends(get_current_user), db_session: Session = Depends(get_db_session)):
    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return TopicBriefService().check(project_id)


@router.put("/{project_id}/topic-brief")
def update_topic_brief(
    project_id: int,
    request: TopicBriefRequest,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.status == ProjectStatus.IN_PRODUCTION:
        raise HTTPException(status_code=409, detail="项目正在制作，不能修改选题定位")
    try:
        return TopicBriefService().save(project_id, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{project_id}/topic-brief/market-signals")
def get_market_signals(project_id: int, current_user=Depends(get_current_user), db_session: Session = Depends(get_db_session)):
    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return TopicBriefService().market_score(project_id)


@router.put("/{project_id}/topic-brief/market-signals")
def update_market_signals(
    project_id: int,
    request: MarketSignalsRequest,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.status == ProjectStatus.IN_PRODUCTION:
        raise HTTPException(status_code=409, detail="项目正在制作，不能修改市场证据")
    try:
        return TopicBriefService().save_market_signals(project_id, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{project_id}/production-readiness")
async def get_production_readiness(
    project_id: int,
    include_engine_preflight: bool = Query(True, description="是否执行视频引擎预检"),
    provider_override: Optional[str] = Query(None, description="本次生产使用的视频 provider 覆盖"),
    model_override: Optional[str] = Query(None, description="本次生产使用的 Seedance 模型覆盖"),
    request_mode_override: Optional[str] = Query(None, description="本次生产使用的视频任务模式覆盖"),
    resolution_override: Optional[str] = Query(None, description="本次生产使用的输出分辨率覆盖"),
    output_format_override: Optional[str] = Query(None, description="本次生产使用的输出格式覆盖"),
    duration_override: Optional[float] = Query(None, description="本次生产使用的时长覆盖"),
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.database.models import Project

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    readiness_kwargs = {"include_engine_preflight": include_engine_preflight}
    if provider_override and provider_override.strip():
        readiness_kwargs["provider_override"] = provider_override.strip().lower()
    if model_override and model_override.strip():
        readiness_kwargs["model_override"] = model_override.strip()
    if request_mode_override and request_mode_override.strip():
        readiness_kwargs["request_mode_override"] = request_mode_override.strip().lower()
    if resolution_override and resolution_override.strip():
        readiness_kwargs["resolution_override"] = resolution_override.strip().lower()
    if output_format_override and output_format_override.strip():
        readiness_kwargs["output_format_override"] = output_format_override.strip().lower()
    if duration_override is not None:
        readiness_kwargs["duration_override"] = duration_override
    return ProductionReadinessService(db_session).build_report(project_id, **readiness_kwargs)


@router.post("/{project_id}/freeze-spatial-plan", response_model=SpatialAssetPackResponse)
async def freeze_spatial_plan(
    project_id: int,
    request: SpatialAssetFreezeRequest,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.database.models import Project

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    scenes = (
        db_session.query(Scene)
        .filter(Scene.project_id == project_id)
        .order_by(Scene.scene_number)
        .all()
    )
    if not scenes:
        raise HTTPException(status_code=409, detail="请先生成分镜再冻结空间计划")
    characters = db_session.query(Character).filter(Character.project_id == project_id).all()
    asset_pack = SpatialControlAssetService().freeze_project_pack(
        project=project,
        scenes=scenes,
        characters=characters,
        notes=request.notes or "",
    )
    return SpatialAssetPackResponse(
        project_id=project_id,
        status=asset_pack["status"],
        asset_pack=asset_pack,
    )


@router.post("/{project_id}/freeze-visual-style", response_model=VisualStyleAssetPackResponse)
async def freeze_visual_style(
    project_id: int,
    request: VisualStyleFreezeRequest,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.database.models import Project

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    scenes = (
        db_session.query(Scene)
        .filter(Scene.project_id == project_id)
        .order_by(Scene.scene_number)
        .all()
    )
    if not scenes:
        raise HTTPException(status_code=409, detail="请先生成分镜再冻结视觉风格")
    asset_pack = VisualStyleAssetService().freeze_project_style(
        project=project,
        scenes=scenes,
        style_prompt=request.style_prompt,
        negative_prompt=request.negative_prompt,
        notes=request.notes or "",
    )
    return VisualStyleAssetPackResponse(
        project_id=project_id,
        status=asset_pack["status"],
        asset_pack=asset_pack,
    )


def _generation_review_summary(reports: dict, repair_output: Path | None = None) -> dict:
    action_items = []
    statuses = {name: _effective_review_status(report) for name, report in reports.items() if isinstance(report, dict)}
    stale = sorted(name for name, status_value in statuses.items() if status_value == "stale")
    if stale:
        action_items.append("Story or media changed; rerun the stale reviews before composing.")

    complexity = reports.get("shot_complexity", {}) if isinstance(reports.get("shot_complexity"), dict) else {}
    complexity_summary = complexity.get("summary", {}) if isinstance(complexity.get("summary"), dict) else {}
    needs_split = int(complexity_summary.get("needs_split") or 0)
    warn = int(complexity_summary.get("warn") or 0)
    if needs_split:
        action_items.append("Split or simplify scenes marked needs_split in shot_complexity.json before GPU generation.")
    elif warn:
        action_items.append("Review warning scenes in shot_complexity.json; keep one action and static camera.")

    production_story = statuses.get("production_story")
    generation = statuses.get("generation")
    baseline = statuses.get("seed_dance_baseline_comparison")
    composition = statuses.get("final_composition")
    if production_story != "passed":
        action_items.append("Run production story review before generating final assets.")
    if generation != "passed":
        action_items.append("Run sampled-frame generation review before final composition.")
    if baseline != "passed":
        action_items.append("Run Seed Dance baseline comparison before claiming replacement quality.")
    if composition is not None and composition != "passed":
        action_items.append("Review the final composition quality gate before delivering the video.")
    continuity = statuses.get("continuity_audit")
    if continuity == "needs_review":
        action_items.append("Resolve hard adjacent-shot continuity conflicts before final composition.")
    elif continuity == "warn":
        action_items.append("Review adjacent-shot continuity warnings before delivery.")
    rhythm = statuses.get("rhythm_audit")
    if rhythm == "needs_review":
        action_items.append("Resolve episode rhythm and dialogue timing conflicts before final composition.")
    elif rhythm == "warn":
        action_items.append("Review episode rhythm warnings before delivery.")
    style_consistency = statuses.get("episode_style_consistency")
    if style_consistency == "needs_review":
        action_items.append("Resolve cross-shot visual style drift before final composition.")
    elif style_consistency == "warn":
        action_items.append("Review cross-shot visual style drift before delivery.")
    identity_consistency = statuses.get("character_identity_consistency")
    if identity_consistency == "needs_review":
        action_items.append("Resolve cross-shot character identity drift before final composition.")
    dialogue_delivery = statuses.get("dialogue_delivery_audit")
    if dialogue_delivery == "needs_review":
        action_items.append("Resolve dialogue audio and subtitle timing delivery issues before final composition.")
    generation_context = statuses.get("generation_context_audit")
    if generation_context == "needs_review":
        action_items.append("Resolve Provider generation-context drift before final composition.")
    atomic_motion = statuses.get("atomic_video_motion_audit")
    if atomic_motion == "needs_review":
        action_items.append("Resolve atomic clip motion, freeze, black-frame, or sharpness failures before composition.")
    first_frame = statuses.get("first_frame_consistency_audit")
    if first_frame == "needs_review":
        action_items.append("Resolve locked-keyframe to opening-frame drift before final composition.")

    boundary_reports = [
        report for report in reports.values()
        if isinstance(report, dict) and report.get("kind") == "sequence_boundary_continuity"
    ]
    boundary_failed = any(
        report.get("status") != "available"
        or int(report.get("severe_transition_count") or 0) > 0
        or int(report.get("severe_style_transition_count") or 0) > 0
        or int(report.get("geometry_mismatch_count") or 0) > 0
        or int(report.get("fps_mismatch_count") or 0) > 0
        or int(report.get("pixel_format_mismatch_count") or 0) > 0
        for report in boundary_reports
    )
    if boundary_failed:
        action_items.append("Resolve multi-shot sequence boundary continuity failures before delivery.")
    timeline_reports = [
        report for report in reports.values()
        if isinstance(report, dict) and report.get("kind") == "sequence_timeline_audit"
    ]
    timeline_failed = any(report.get("status") != "passed" for report in timeline_reports)
    if timeline_failed:
        action_items.append("Resolve multi-shot sequence timeline duration drift before delivery.")

    final_human_review_required = composition is not None
    final_human_review_decision = None
    if final_human_review_required:
        composition_report = reports.get("final_composition", {})
        human_decision = composition_report.get("human_decision")
        if isinstance(human_decision, dict):
            final_human_review_decision = human_decision.get("decision")
        if final_human_review_decision != "approved":
            action_items.append("Complete the final episode human review and approve it before delivery.")

    repair_queue = _repair_queue_summary(reports)
    repair_plan = build_repair_execution_plan(repair_output or Path("storage/validation"), repair_queue["items"])
    scorecard = build_generation_quality_scorecard(reports)
    if repair_queue["total"]:
        action_items.append(f"Repair queue has {repair_queue['total']} targeted actions from failed generation reports.")

    blocking = bool(
        stale or needs_split or production_story != "passed" or generation != "passed"
        or baseline != "passed" or (composition is not None and composition != "passed")
        or continuity == "needs_review"
        or rhythm == "needs_review"
        or style_consistency == "needs_review"
        or identity_consistency == "needs_review"
        or dialogue_delivery == "needs_review"
        or generation_context == "needs_review"
        or atomic_motion == "needs_review"
        or first_frame == "needs_review"
        or boundary_failed
        or timeline_failed
        or (final_human_review_required and final_human_review_decision != "approved")
    )
    return {
        "status": "blocked" if blocking else "ready",
        "reports": statuses,
        "stale_reports": stale,
        "shot_complexity": {
            "status": complexity.get("status"),
            "needs_split": needs_split,
            "warn": warn,
        },
        "repair_queue": repair_queue,
        "repair_execution_plan": repair_plan,
        "sequence_boundary": {
            "status": "blocked" if boundary_failed else ("passed" if boundary_reports else "not_applicable"),
            "reports": len(boundary_reports),
        },
        "sequence_timeline": {
            "status": "blocked" if timeline_failed else ("passed" if timeline_reports else "not_applicable"),
            "reports": len(timeline_reports),
        },
        "quality_scorecard": scorecard,
        "action_items": action_items,
        "human_final_review_required": final_human_review_required,
        "human_final_review_status": (
            final_human_review_decision if final_human_review_required else "not_applicable"
        ),
        "human_approved_reports": sorted(
            name for name, report in reports.items()
            if isinstance(report, dict)
            and isinstance(report.get("human_decision"), dict)
            and report["human_decision"].get("decision") == "approved"
        ),
    }


def _effective_review_status(report: dict) -> str | None:
    status_value = report.get("status")
    # Story-room failures describe missing structural beats, not subjective
    # presentation preferences. A human may acknowledge them, but cannot
    # turn an incomplete story contract into a production-ready one.
    if report.get("kind") in {
        "story_room_quality",
        "seed_dance_baseline_comparison",
    } and status_value != "passed":
        return status_value
    # A human can resolve a subjective visual disagreement, but cannot waive
    # missing/stale per-scene evidence or incomplete coverage.
    for evidence_key in ("scene_coverage", "evidence"):
        evidence = report.get(evidence_key)
        if isinstance(evidence, dict) and evidence.get("passed") is False:
            return status_value
    decision = report.get("human_decision")
    if (
        status_value in {"needs_review", "review_unavailable"}
        and isinstance(decision, dict)
        and decision.get("decision") == "approved"
    ):
        return "passed"
    return status_value


def _repair_queue_summary(reports: dict) -> dict:
    items = []
    actions = {}
    execution = {"auto": 0, "setup_required": 0, "manual": 0}
    for name, report in reports.items():
        if not isinstance(report, dict):
            continue
        for item in report.get("repair_queue") or []:
            if not isinstance(item, dict):
                continue
            copied = dict(item)
            copied["source_report"] = name
            items.append(copied)
            action = copied.get("action") or "unknown"
            actions[action] = actions.get(action, 0) + 1
            mode = copied.get("execution") or "manual"
            execution[mode] = execution.get(mode, 0) + 1
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (priority_rank.get(item.get("priority"), 9), item.get("stage") or "", item.get("action") or ""))
    return {
        "total": len(items),
        "actions": actions,
        "execution": execution,
        "auto_actions": [item for item in items if item.get("execution") == "auto"][:10],
        "setup_required": [item for item in items if item.get("execution") == "setup_required"][:10],
        "manual_actions": [item for item in items if item.get("execution") not in {"auto", "setup_required"}][:10],
        "items": items[:20],
    }


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate,
    current_user = Depends(get_current_user),
    db_session: Session = Depends(get_db_session)
):
    """
    创建新项目

    Args:
        project: 项目创建请求
        current_user: 当前用户
        db_session: 数据库会话

    Returns:
        创建的项目信息

    Raises:
        HTTPException: 创建失败时抛出
    """
    try:
        logger.info(f"创建项目: {project.name}")

        project_manager = ProjectManager(db_session)
        db_project = project_manager.create_project(
            name=project.name,
            description=project.description,
            theme=project.theme,
            outline=project.outline,
            user_id=current_user.id
        )

        logger.info(f"项目创建成功: id={db_project.id}, name={db_project.name}")
        return db_project

    except ValueError as e:
        logger.warning(f"项目创建失败（输入验证）: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"项目创建失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建项目时发生错误"
        )


def _draft_evidence_status(project) -> dict:
    """Expose whether every scene has a current Seedance Draft to promote."""
    missing: list[int] = []
    expired: list[int] = []
    for scene in sorted(project.scenes or [], key=lambda item: item.scene_number):
        video_path = Path(scene.video_path) if scene.video_path else None
        provider_path = video_path.with_suffix(".provider.json") if video_path else None
        metadata = {}
        if provider_path and provider_path.is_file():
            try:
                loaded = json.loads(provider_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    metadata = loaded
            except (OSError, ValueError):
                metadata = {}
        try:
            current_hash = file_hash(video_path) if video_path and video_path.is_file() else None
        except (OSError, ValueError):
            current_hash = None
        valid = bool(
            metadata.get("provider_name") == "seedance_api"
            and metadata.get("requested_draft") is True
            and isinstance(metadata.get("provider_task_id"), str)
            and metadata.get("provider_task_id", "").strip()
            and current_hash
            and metadata.get("video_sha256") == current_hash
        )
        if not valid:
            missing.append(int(scene.scene_number))
        elif _draft_expired(metadata.get("provider_created_at"), metadata.get("provider_expires_at")):
            expired.append(int(scene.scene_number))
    return {
        "draft_ready": bool(project.scenes) and not missing and not expired,
        "draft_missing_scenes": missing,
        "draft_expired_scenes": expired,
    }


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, db_session: Session = Depends(get_db_session)):
    """
    获取项目详情

    Args:
        project_id: 项目 ID

    Returns:
        项目详细信息

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    try:
        logger.info(f"获取项目详情: project_id={project_id}")

        project_manager = ProjectManager(db_session)
        db_project = project_manager.get_project(project_id)

        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )

        return ProjectResponse.model_validate(db_project).model_copy(
            update=_draft_evidence_status(db_project)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取项目详情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取项目详情时发生错误"
        )


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: int, project: ProjectUpdate, db_session: Session = Depends(get_db_session)):
    """
    更新项目信息

    Args:
        project_id: 项目 ID
        project: 项目更新请求

    Returns:
        更新后的项目信息

    Raises:
        HTTPException: 项目不存在或更新失败时抛出
    """
    try:
        logger.info(f"更新项目: project_id={project_id}")

        project_manager = ProjectManager(db_session)

        # 构建更新数据（只包含非 None 的字段）
        update_data = {}
        if project.name is not None:
            update_data["name"] = project.name
        if project.description is not None:
            update_data["description"] = project.description
        if project.theme is not None:
            update_data["theme"] = project.theme
        if project.outline is not None:
            update_data["outline"] = project.outline
        if project.status is not None:
            raise ValueError("生产状态由任务系统管理")

        db_project = project_manager.update_project(project_id, **update_data)

        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )

        logger.info(f"项目更新成功: project_id={project_id}")
        return db_project

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"项目更新失败（输入验证）: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"项目更新失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新项目时发生错误"
        )


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(project_id: int, db_session: Session = Depends(get_db_session)):
    """
    删除项目

    Args:
        project_id: 项目 ID

    Returns:
        删除成功消息

    Raises:
        HTTPException: 项目不存在或删除失败时抛出
    """
    try:
        logger.info(f"删除项目: project_id={project_id}")

        project_manager = ProjectManager(db_session)
        success = project_manager.delete_project(project_id)

        if not success:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )

        logger.info(f"项目删除成功: project_id={project_id}")
        return MessageResponse(
            message="项目删除成功",
            detail=f"项目 {project_id} 及其关联文件已删除"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"项目删除失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除项目时发生错误"
        )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    status_filter: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session)
):
    """
    列出项目

    Args:
        status_filter: 状态过滤（可选）
        page: 页码（从 1 开始）
        page_size: 每页数量

    Returns:
        项目列表和分页信息
    """
    try:
        logger.info(f"列出项目: status={status_filter}, page={page}, page_size={page_size}")

        project_manager = ProjectManager(db_session)

        total = project_manager.count_projects(status=status_filter, user_id=current_user.id)
        projects = project_manager.list_projects(
            status=status_filter,
            limit=page_size,
            offset=(page - 1) * page_size,
            user_id=current_user.id,
        )

        return ProjectListResponse(
            total=total,
            page=page,
            page_size=page_size,
            projects=projects
        )

    except Exception as e:
        logger.error(f"列出项目失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="列出项目时发生错误"
        )


@router.post("/{project_id}/generate-script", response_model=ProjectResponse)
def generate_script(project_id: int, request: GenerateScriptRequest, db_session: Session = Depends(get_db_session)):
    """
    生成剧本

    Args:
        project_id: 项目 ID
        request: 剧本生成请求

    Returns:
        更新后的项目信息（包含角色和分镜）

    Raises:
        HTTPException: 项目不存在或生成失败时抛出
    """
    try:
        logger.info(f"生成剧本: project_id={project_id}")

        project_manager = ProjectManager(db_session)
        script_generator = ScriptGenerator(db_session)

        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )

        # 使用请求中的主题和大纲，如果没有提供或为空字符串则使用项目中的
        theme = request.theme.strip() if request.theme and request.theme.strip() else db_project.theme
        outline = request.outline.strip() if request.outline and request.outline.strip() else db_project.outline

        # 如果仍然没有theme和outline，抛出错误
        if not theme and not outline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="主题(theme)和大纲(outline)至少需要提供一个。请在项目设置中添加主题或大纲。"
            )

        # 生成剧本（使用增强版参数）
        logger.info(f"开始生成剧本: project_id={project_id}")
        script_generator.generate_script(
            project_id=project_id,
            theme=theme,
            outline=outline,
            num_scenes=request.num_scenes,
            num_characters=request.num_characters,
            style=request.style,
            num_chapters=request.num_chapters,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )

        # 更新项目状态
        project_manager.update_project(project_id, status="script_generated")

        # 返回更新后的项目信息
        db_project = project_manager.get_project(project_id)
        logger.info(f"剧本生成成功: project_id={project_id}, characters={len(db_project.characters)}, scenes={len(db_project.scenes)}")

        return db_project

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"剧本生成失败（输入验证）: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        error_msg = str(e)
        # 使用%s而不是f-string避免JSON中的花括号导致KeyError
        logger.error("剧本生成失败: %s", error_msg, exc_info=True)

        # 检查是否是LLM服务相关错误
        if "llama-cpp-python" in error_msg or "LLM 服务初始化失败" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="剧本生成功能需要LLM服务,但当前未配置。请手动创建剧本或联系管理员配置LLM服务。"
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"剧本生成失败: {error_msg}"
        )


@router.post("/{project_id}/repair-script", response_model=ProjectResponse)
def repair_script(project_id: int, db_session: Session = Depends(get_db_session)):
    """Rewrite the current script from story-room evidence before visual generation."""
    project = db_session.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")
    if project.status == ProjectStatus.IN_PRODUCTION:
        raise HTTPException(status_code=409, detail="项目正在制作，请等待当前任务结束")
    scenes = db_session.query(Scene).filter(Scene.project_id == project_id).order_by(Scene.scene_number).all()
    if not scenes:
        raise HTTPException(status_code=400, detail="没有可供重写的分镜")

    try:
        from src.utils.storage import storage_manager
        parsed_script = json.loads(project.script) if project.script else {}
        if not isinstance(parsed_script, dict):
            parsed_script = {}
        if not parsed_script.get("characters"):
            parsed_script["characters"] = [
                {"name": character.name, "description": character.description}
                for character in project.characters
            ]
        if not parsed_script.get("scenes"):
            parsed_script["scenes"] = [
                {
                    "scene_number": scene.scene_number,
                    "description": scene.visual_description,
                    "dialogue": scene.dialogue,
                    "speaker": scene.character_name,
                }
                for scene in scenes
            ]
        if not parsed_script.get("scenes"):
            raise ScriptParseError("当前项目没有结构化剧本分镜")

        review_path = storage_manager.get_project_path(project_id) / "reviews" / "production_story.json"
        if review_path.is_file():
            failed_review = json.loads(review_path.read_text(encoding="utf-8"))
        else:
            story_report = StoryRoomQualityService().evaluate(
                project,
                scenes,
                {scene["scene_number"]: scene for scene in parsed_script["scenes"]},
            ).to_dict()
            failed_review = {
                "status": "needs_review",
                "review": {
                    "issues": [{
                        "reason": "story-room gate missing: " + ", ".join(story_report["missing"]),
                        "scene_number": 1,
                    }],
                },
            }
        generator = ScriptGenerator(db_session)
        repaired_script, reviewed = generator.repair_script_for_review(
            project=project,
            parsed_script=parsed_script,
            failed_review=failed_review,
            review_path=review_path,
            max_attempts=3,
        )
        require_passed(reviewed)
        generator._save_script_to_db(project, repaired_script)
        project.script = json.dumps(repaired_script, ensure_ascii=False)
        project.status = ProjectStatus.SCRIPT_GENERATED
        db_session.commit()
        return project
    except HTTPException:
        raise
    except (ScriptParseError, ValueError) as exc:
        db_session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db_session.rollback()
        logger.error(f"重写剧本失败: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="重写剧本失败，请检查 LLM 和故事审核服务配置") from exc


@router.post("/{project_id}/regenerate-scene", response_model=ProjectResponse)
def regenerate_scene(project_id: int, request: RegenerateSceneRequest, db_session: Session = Depends(get_db_session)):
    """
    重新生成指定分镜

    Args:
        project_id: 项目 ID
        request: 重新生成分镜请求

    Returns:
        更新后的项目信息

    Raises:
        HTTPException: 项目不存在或分镜不存在时抛出
    """
    try:
        logger.info(f"重新生成分镜: project_id={project_id}, scene_number={request.scene_number}")

        project_manager = ProjectManager(db_session)
        script_generator = ScriptGenerator(db_session)

        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )

        # 重新生成分镜
        script_generator.regenerate_scene(project_id, request.scene_number, request.new_description)

        # 返回更新后的项目信息
        db_project = project_manager.get_project(project_id)
        logger.info(f"分镜重新生成成功: project_id={project_id}, scene_number={request.scene_number}")

        return db_project

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"分镜重新生成失败（输入验证）: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"分镜重新生成失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分镜重新生成失败: {e}"
        )


@router.post("/{project_id}/bgm")
async def upload_project_bgm(
    project_id: int,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    """Store a project-owned BGM asset for ducked final composition."""
    project = db_session.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.status == ProjectStatus.IN_PRODUCTION:
        raise HTTPException(status_code=409, detail="项目正在制作，不能修改背景音乐")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}:
        raise HTTPException(status_code=400, detail="BGM 仅支持 MP3、WAV、M4A、AAC 或 OGG")
    music_dir = storage_manager.get_project_path(project_id) / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    destination = music_dir / f"bgm{suffix}"
    with destination.open("wb") as stream:
        shutil.copyfileobj(file.file, stream)
    if destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="BGM 文件为空")
    return {
        "project_id": project_id,
        "bgm_path": str(destination),
        "filename": Path(file.filename or destination.name).name,
        "size": destination.stat().st_size,
    }


@router.post("/{project_id}/produce", response_model=ProductionTaskResponse)
async def produce_video(
    project_id: int,
    request: ProductionOptions | None = None,
    db_session: Session = Depends(get_db_session)
):
    """
    提交视频生产任务

    Args:
        project_id: 项目 ID

    Returns:
        生产任务信息

    Raises:
        HTTPException: 项目不存在或提交失败时抛出
    """
    try:
        logger.info(f"提交生产任务: project_id={project_id}")

        project_manager = ProjectManager(db_session)
        task_orchestrator = TaskOrchestrator(db_session)

        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )

        # 检查项目是否有分镜
        if not db_project.scenes:
            logger.warning(f"项目没有分镜: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="项目没有分镜，请先生成剧本"
            )

        # 创建生产任务
        options = request or ProductionOptions()
        if options.add_bgm:
            if not options.bgm_path:
                raise HTTPException(status_code=422, detail="启用背景音乐时必须先上传 BGM")
            bgm_candidate = Path(options.bgm_path).resolve()
            project_root = storage_manager.get_project_path(project_id).resolve()
            if (
                bgm_candidate.suffix.lower() not in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
                or not bgm_candidate.is_file()
                or not bgm_candidate.is_relative_to(project_root)
            ):
                raise HTTPException(status_code=422, detail="BGM 必须是当前项目已上传的音频文件")
        normalized_options = _normalized_production_options(options)
        provider = options.provider.strip() or None if isinstance(options.provider, str) else options.provider
        request_mode = options.request_mode.strip() or None if isinstance(options.request_mode, str) else options.request_mode
        celery_task_id = task_orchestrator.create_production_task(
            project_id,
            provider=provider,
            request_mode=request_mode,
            multi_shot=options.multi_shot,
            native_audio=options.native_audio,
            draft=options.draft,
            draft_task_id=options.draft_task_id,
            model=options.model,
            add_bgm=options.add_bgm,
            bgm_path=options.bgm_path,
            bgm_volume=options.bgm_volume,
            **normalized_options,
        )

        # 更新项目状态

        # 查询任务记录
        from src.database.models import Task as TaskModel
        task_record = db_session.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()

        if not task_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="任务记录创建失败"
            )

        logger.info(f"生产任务创建成功: task_id={task_record.id}, project_id={project_id}")

        return ProductionTaskResponse(
            task_id=task_record.celery_task_id,
            project_id=task_record.project_id,
            status=task_record.status.value,
            progress=task_record.progress,
            current_step=str(task_record.current_step),
            total_steps=task_record.total_steps,
            created_at=task_record.created_at,
            updated_at=task_record.updated_at,
            error_message=task_record.error_message
        )

    except HTTPException:
        raise
    except ValueError as e:
        detail = str(e)
        logger.warning(f"提交生产任务被阻断: {detail}")
        raise HTTPException(
            status_code=_production_error_status(detail),
            detail=detail,
        )
    except Exception as e:
        logger.error(f"提交生产任务失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="提交生产任务时发生错误"
        )


@router.post("/{project_id}/promote-drafts", response_model=ProductionTaskResponse)
async def promote_seedance_drafts(
    project_id: int,
    db_session: Session = Depends(get_db_session),
):
    """Promote every saved Seedance Draft task to a final video task."""
    project = db_session.query(Project).filter(Project.id == project_id).first()
    if not project or not project.scenes:
        raise HTTPException(status_code=404, detail="项目不存在或没有分镜")
    if project.status == ProjectStatus.IN_PRODUCTION:
        raise HTTPException(status_code=409, detail="项目正在制作，请等待当前 Draft 提升任务结束")
    if project.status == ProjectStatus.COMPLETED and str(project.final_video_path or "").strip():
        raise HTTPException(status_code=409, detail="项目已完成，不能重复提升 Draft")
    draft_ids: dict[int, str] = {}
    draft_models: set[str] = set()
    draft_output_formats: set[str] = set()
    draft_watermarks: set[bool] = set()
    draft_return_last_frames: set[bool] = set()
    expired = []
    missing = []
    for scene in sorted(project.scenes, key=lambda item: item.scene_number):
        scene_video_path = Path(scene.video_path) if scene.video_path else None
        provider_path = Path(scene.video_path).with_suffix(".provider.json") if scene.video_path else None
        data = None
        if provider_path and provider_path.is_file():
            try:
                data = json.loads(provider_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
        task_id = data.get("provider_task_id") if isinstance(data, dict) else None
        is_draft = bool(data.get("requested_draft")) if isinstance(data, dict) else False
        if isinstance(task_id, str) and task_id.strip() and is_draft:
            if data.get("provider_name") != "seedance_api":
                missing.append(scene.scene_number)
                continue
            current_video_hash = (
                file_hash(scene_video_path)
                if scene_video_path and scene_video_path.is_file()
                else None
            )
            if not current_video_hash or data.get("video_sha256") != current_video_hash:
                missing.append(scene.scene_number)
                continue
            if isinstance(data, dict) and _draft_expired(
                data.get("provider_created_at"), data.get("provider_expires_at")
            ):
                expired.append(scene.scene_number)
            draft_ids[scene.id] = task_id.strip()
            requested_model = data.get("requested_model") if isinstance(data, dict) else None
            if isinstance(requested_model, str) and requested_model.strip():
                draft_models.add(requested_model.strip())
            requested_output_format = data.get("requested_output_format") if isinstance(data, dict) else None
            if isinstance(requested_output_format, str) and requested_output_format.strip():
                draft_output_formats.add(requested_output_format.strip().lower())
            requested_watermark = data.get("requested_watermark") if isinstance(data, dict) else None
            if isinstance(requested_watermark, bool):
                draft_watermarks.add(requested_watermark)
            requested_return_last_frame = data.get("requested_return_last_frame") if isinstance(data, dict) else None
            if isinstance(requested_return_last_frame, bool):
                draft_return_last_frames.add(requested_return_last_frame)
        else:
            missing.append(scene.scene_number)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"以下分镜没有可提升的 Draft 任务 ID: {', '.join(map(str, missing))}",
        )
    if expired:
        raise HTTPException(
            status_code=410,
            detail=f"以下分镜的 Seedance Draft 已超过 7 天有效期，无法提升: {', '.join(map(str, expired))}",
        )
    if len(draft_models) > 1:
        raise HTTPException(
            status_code=400,
            detail="Draft 分镜使用了多个 Seedance 模型，不能在同一个提升任务中混合提升",
        )
    if len(draft_output_formats) > 1:
        raise HTTPException(
            status_code=400,
            detail="Draft 分镜使用了多个输出格式，不能在同一个提升任务中混合提升",
        )
    if len(draft_watermarks) > 1:
        raise HTTPException(
            status_code=400,
            detail="Draft 分镜使用了不同的水印设置，不能在同一个提升任务中混合提升",
        )
    if len(draft_return_last_frames) > 1:
        raise HTTPException(
            status_code=400,
            detail="Draft 分镜使用了不同的尾帧设置，不能在同一个提升任务中混合提升",
        )
    draft_model = next(iter(draft_models), None)
    draft_output_format = next(iter(draft_output_formats), None)
    draft_watermark = next(iter(draft_watermarks), None)
    draft_return_last_frame = next(iter(draft_return_last_frames), None)
    try:
        orchestrator = TaskOrchestrator(db_session)
        celery_task_id = orchestrator.create_production_task(
            project_id,
            generate_images=False,
            generate_videos=True,
            generate_audios=False,
            generate_subtitles=False,
            provider="seedance_api",
            request_mode="reference",
            draft=False,
            draft_task_ids=draft_ids,
            model=draft_model,
            output_format=draft_output_format,
            watermark=draft_watermark,
            return_last_frame=draft_return_last_frame,
        )
        from src.database.models import Task as TaskModel
        task_record = db_session.query(TaskModel).filter(TaskModel.celery_task_id == celery_task_id).first()
        if not task_record:
            raise HTTPException(status_code=500, detail="Draft 提升任务记录创建失败")
        return ProductionTaskResponse(
            task_id=task_record.celery_task_id,
            project_id=task_record.project_id,
            status=task_record.status.value,
            progress=task_record.progress,
            current_step=str(task_record.current_step),
            total_steps=task_record.total_steps,
            created_at=task_record.created_at,
            updated_at=task_record.updated_at,
            error_message=task_record.error_message,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=_production_error_status(str(exc)), detail=str(exc))


@router.post("/{project_id}/regenerate-images", response_model=ProductionTaskResponse)
async def regenerate_images(
    project_id: int,
    db_session: Session = Depends(get_db_session)
):
    """
    重新生成图像（不重新生成剧本）

    当图像生成出错时，可以只重新生成图像而不需要重新生成剧本。
    此操作会清除所有已生成的图像，然后根据现有的剧本和分镜重新生成。

    Args:
        project_id: 项目 ID

    Returns:
        生产任务信息

    Raises:
        HTTPException: 项目不存在或提交失败时抛出
    """
    try:
        logger.info(f"重新生成图像: project_id={project_id}")

        project_manager = ProjectManager(db_session)
        task_orchestrator = TaskOrchestrator(db_session)

        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )

        # 检查项目是否有分镜
        if not db_project.scenes:
            logger.warning(f"项目没有分镜: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="项目没有分镜，请先生成剧本"
            )

        # 创建生产任务（只生成图像和视频）
        celery_task_id = task_orchestrator.create_production_task(project_id)

        # 更新项目状态

        # 查询任务记录
        from src.database.models import Task as TaskModel
        task_record = db_session.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()

        if not task_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="任务记录创建失败"
            )

        logger.info(f"重新生成图像任务创建成功: task_id={task_record.id}, project_id={project_id}")

        return ProductionTaskResponse(
            task_id=task_record.celery_task_id,
            project_id=task_record.project_id,
            status=task_record.status.value,
            progress=task_record.progress,
            current_step=str(task_record.current_step),
            total_steps=task_record.total_steps,
            created_at=task_record.created_at,
            updated_at=task_record.updated_at,
            error_message=task_record.error_message
        )

    except HTTPException:
        raise
    except ValueError as e:
        detail = str(e)
        logger.warning(f"重新生成图像被阻断: {detail}")
        raise HTTPException(
            status_code=_production_error_status(detail),
            detail=detail,
        )
    except Exception as e:
        logger.error(f"重新生成图像失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="重新生成图像时发生错误"
        )


@router.post("/{project_id}/repair-scene", response_model=ProductionTaskResponse)
async def repair_scene_generation(
    project_id: int,
    request: RepairSceneRequest,
    db_session: Session = Depends(get_db_session),
):
    try:
        task_orchestrator = TaskOrchestrator(db_session)
        celery_task_id = task_orchestrator.create_scene_repair_task(
            project_id,
            request.scene_number,
            request.action,
        )
        from src.database.models import Task as TaskModel
        task_record = db_session.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()
        if not task_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="返工任务记录创建失败",
            )
        return ProductionTaskResponse(
            task_id=task_record.celery_task_id,
            project_id=task_record.project_id,
            status=task_record.status.value,
            progress=task_record.progress,
            current_step=str(task_record.current_step),
            total_steps=task_record.total_steps,
            created_at=task_record.created_at,
            updated_at=task_record.updated_at,
            error_message=task_record.error_message,
        )
    except HTTPException:
        raise
    except ValueError as e:
        detail = str(e)
        logger.warning(f"返工任务被阻断: {detail}")
        raise HTTPException(status_code=_production_error_status(detail), detail=detail)
    except Exception as e:
        logger.error(f"创建返工任务失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建返工任务时发生错误",
        )


@router.post("/{project_id}/repair-queue/auto", response_model=RepairQueueAutoRunResponse)
async def run_auto_repair_queue(
    project_id: int,
    request: RepairQueueAutoRunRequest,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    if request.action and repair_execution_mode(request.action) != "auto":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"指定返修动作不可自动执行: {request.action}",
        )
    review = await get_generation_review(project_id, current_user, db_session)
    budget = RepairBudget(project_id)
    if review.get("summary", {}).get("status") in {"ready", "ready_for_seed_dance_candidate"}:
        budget.reset()
    loop_plan = build_quality_loop_plan(
        review.get("summary", {}), request.max_actions, request.action,
    )
    selected, exhausted = budget.filter(loop_plan["selected"])
    skipped = loop_plan["skipped"] + exhausted
    if request.dry_run:
        return RepairQueueAutoRunResponse(
            project_id=project_id,
            status="planned" if selected else ("manual_review_required" if exhausted else "no_auto_actions"),
            dry_run=True,
            submitted=[],
            skipped=skipped,
            considered=selected,
        )

    submitted = []
    task_orchestrator = TaskOrchestrator(db_session)
    from src.database.models import Task as TaskModel

    if selected:
        try:
            if len(selected) == 1:
                celery_task_id = task_orchestrator.create_scene_repair_task(
                    project_id, selected[0]["scene_number"], selected[0]["action"],
                )
            else:
                celery_task_id = task_orchestrator.create_repair_batch_task(project_id, selected)
            task_record = db_session.query(TaskModel).filter(
                TaskModel.celery_task_id == celery_task_id
            ).first()
            submitted.extend({
                **item, "task_id": celery_task_id,
                "status": task_record.status.value if task_record else "submitted",
            } for item in selected)
        except ValueError as exc:
            skipped.extend({**item, "reason": str(exc)} for item in selected)
        except Exception as exc:
            logger.error(f"自动返工任务创建失败: {exc}", exc_info=True)
            skipped.extend({**item, "reason": "task_submission_failed"} for item in selected)
        else:
            budget.record(selected)

    benign_skips = {"duplicate_action", "stage_already_selected", "scene_already_selected"}
    actionable_skips = [
        item for item in skipped
        if item.get("reason") not in benign_skips
    ]
    if submitted and actionable_skips:
        result_status = "partial"
    elif submitted:
        result_status = "submitted"
    elif selected:
        result_status = "blocked"
    elif exhausted:
        result_status = "manual_review_required"
    else:
        result_status = "no_auto_actions"
    cycle = RepairCycleStore(project_id).record(
        status=result_status,
        submitted=submitted,
        skipped=skipped,
        considered=selected,
    )
    return RepairQueueAutoRunResponse(
        project_id=project_id,
        status=result_status,
        dry_run=False,
        submitted=submitted,
        skipped=skipped,
        considered=selected,
        cycle_id=cycle["cycle_id"],
    )


@router.get("/{project_id}/quality-loop/plan")
async def get_quality_loop_plan(
    project_id: int,
    max_actions: int = Query(5, ge=1, le=20, description="本轮最多规划的自动返工任务数"),
    action: str | None = Query(None, min_length=1, max_length=100, description="只预览指定的自动返工动作"),
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    if action and repair_execution_mode(action) != "auto":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"指定返修动作不可自动执行: {action}",
        )
    review = await get_generation_review(project_id, current_user, db_session)
    summary = review.get("summary", {})
    return {
        "project_id": project_id,
        "summary_status": summary.get("status"),
        "quality_scorecard": summary.get("quality_scorecard", {}),
        "recent_cycles": RepairCycleStore(project_id).recent(5),
        "plan": build_quality_loop_plan(summary, max_actions, action),
    }


@router.get("/{project_id}/production-task")
def latest_production_task(project_id: int, db_session: Session = Depends(get_db_session)):
    from src.database.models import Task
    task = db_session.query(Task).filter(Task.project_id == project_id).order_by(Task.id.desc()).first()
    if task is None:
        return None
    import json
    from src.utils.storage import storage_manager
    result = TaskOrchestrator(db_session).get_task_status(task.celery_task_id)
    path = storage_manager.get_project_path(project_id) / "production_progress.json"
    if path.is_file():
        progress = json.loads(path.read_text(encoding="utf-8"))
        if progress.get("celery_task_id") == task.celery_task_id:
            result["live_step"] = progress
    return result


from src.api.schemas import SceneUpdate


@router.put("/{project_id}/scenes/{scene_number}", response_model=ProjectResponse)
def update_scene(project_id: int, scene_number: int, request: SceneUpdate, db_session: Session = Depends(get_db_session)):
    import json
    from src.database.models import Scene, Project
    project = db_session.query(Project).filter(Project.id == project_id).first()
    scene = db_session.query(Scene).filter(Scene.project_id == project_id, Scene.scene_number == scene_number).first()
    if not scene or not request.visual_description.strip():
        raise HTTPException(400, "分镜不存在或描述为空")
    scene.visual_description = request.visual_description.strip()
    scene.dialogue = request.dialogue
    scene.character_name = request.character_name
    scene.image_prompt = scene.image_path = scene.video_path = None
    scene.audio_path = scene.subtitle_path = None
    project.final_video_path = None
    project.status = ProjectStatus.SCRIPT_GENERATED
    if project.script:
        script = json.loads(project.script)
        for item in script.get("scenes", []):
            if item.get("scene_number") == scene_number:
                item.update(description=scene.visual_description, dialogue=scene.dialogue, speaker=scene.character_name)
        project.script = json.dumps(script, ensure_ascii=False)
    db_session.commit()
    return project
