import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { errorText, projectApi } from '../api/client';
import type { GenerationReviewSummary, QualityLoopPlan } from '../api/client';
import { ProjectImage, ProjectVideo } from './ProjectMedia';

const names: Record<string, string> = {
    story: '生成情节复审',
    production_story: '制作前情节复审',
    story_room_quality: '故事房质量证据',
    generation: '成片质量审核',
    final_composition: '最终合成质量',
    continuity_audit: '相邻分镜连续性',
    rhythm_audit: '整集节奏与对白时序',
    episode_style_consistency: '全集视觉风格一致性',
    character_identity_consistency: '角色跨镜头身份一致性',
    dialogue_delivery_audit: '对白音频与字幕交付',
    generation_context_audit: '生成上下文一致性',
    atomic_video_motion_audit: '原子镜头运动质量',
    first_frame_consistency_audit: '锁定关键帧首帧一致性',
    sequence_timeline_audit: '多镜头时间轴一致性',
    seed_dance_baseline_comparison: 'Seed Dance 对比验收',
    causal_logic: '因果逻辑',
    character_motivation: '角色动机',
    continuity: '连续性',
    filmability: '可拍性',
    story_match: '剧情匹配',
    composition: '构图',
    visual_integrity: '画面完整性',
    facial_identity: '面部身份',
    identity_consistency: '角色一致性',
    temporal_consistency: '时间连续性',
};

const statuses: Record<string, string> = {
    passed: '通过',
    needs_review: '需要复核',
    error: '审核出错',
    stale: '内容已变更，待重审',
    blocked: '被阻断',
    ready: '可继续',
};

const actionLabels: Record<string, string> = {
    'Story or media changed; rerun the stale reviews before composing.': '剧情或媒体已变更，需要重跑过期审核后再合成。',
    'Split or simplify scenes marked needs_split in shot_complexity.json before GPU generation.': '先拆分或简化需要拆分的分镜，再进入 GPU 生成。',
    'Review warning scenes in shot_complexity.json; keep one action and static camera.': '复核有警告的分镜，尽量保持一个动作和稳定镜头。',
    'Run production story review before generating final assets.': '生成最终资产前先运行制作前情节复审。',
    'Run sampled-frame generation review before final composition.': '最终合成前先运行抽帧成片质量审核。',
    'Run Seed Dance baseline comparison before claiming replacement quality.': '先完成 Seed Dance 基线对比，再判断是否达到替代质量。',
};

const repairActionLabels: Record<string, string> = {
    regenerate_character_identity: '重做角色身份/参考图',
    regenerate_keyframe_with_prop_constraints: '重做关键帧并强化手和道具约束',
    refine_prompt_composition: '优化构图、光线和提示词',
    refine_project_style_consistency: '按项目视觉圣经重做关键帧',
    refine_face_aesthetic_detail: '优化面部质感与商业审美',
    regenerate_keyframe_with_role_separation: '强化多角色身份区分后重做关键帧',
    lower_motion_and_regenerate_video: '降低运动强度后重做视频',
    increase_motion_and_regenerate_video: '增强运动表现后重做视频',
    regenerate_video_with_performance_direction: '强化表演、凝视和动作方向后重做视频',
    refine_video_commercial_aesthetic: '按商业短剧审美重做视频',
    refine_final_composition_finish: '重做最终合成精修',
    fix_video_output_contract: '按生产契约修复模型与输出规格',
    refine_dialogue_audio_delivery: '重做对白音频与字幕时序',
    split_scene: '拆分为更简单的原子镜头',
    refreeze_spatial_plan: '重新冻结空间计划',
    fix_workflow_profile: '修复 Workflow Profile',
    rewrite_short_drama_story_rhythm: '按建议重写短剧节奏',
    complete_topic_brief: '补齐选题定位',
    refine_topic_brief: '细化选题定位',
    start_local_reviewer: '启动 llama.cpp 视觉审核后重跑',
    manual_review: '人工复核',
    regenerate_keyframe_with_identity_lock: '按立体画册锁定身份重做关键帧',
};

const loopStatusLabels: Record<string, string> = {
    can_auto_repair: '可自动返工',
    setup_required: '需要先补配置',
    manual_review_required: '需要人工判断',
    ready: '可进入成片',
    blocked: '被阻断',
};

function labelAction(item: string) {
    return actionLabels[item] || item;
}

function labelRepairAction(action?: string) {
    return repairActionLabels[action || ''] || action || '未知动作';
}

const automaticRepairActions = new Set([
    'regenerate_keyframe_with_identity_lock',
    'regenerate_keyframe_with_role_separation',
    'regenerate_keyframe_with_prop_constraints',
    'refine_prompt_composition',
    'refine_project_style_consistency',
    'refine_face_aesthetic_detail',
    'lower_motion_and_regenerate_video',
    'increase_motion_and_regenerate_video',
    'regenerate_video_with_performance_direction',
    'refine_video_commercial_aesthetic',
    'refine_final_composition_finish',
    'refine_dialogue_audio_delivery',
]);

function executableRepair(action?: string, sceneNumber?: number) {
    return Boolean(sceneNumber && action && (automaticRepairActions.has(action) || action === 'fix_video_output_contract'));
}

function executableSetupRepair(action?: string, sceneNumber?: number) {
    return action === 'refreeze_spatial_plan'
        || action === 'fix_workflow_profile'
        || action === 'rewrite_short_drama_story_rhythm'
        || (action === 'fix_video_output_contract' && Boolean(sceneNumber));
}

function repairPlanCount(summary: GenerationReviewSummary) {
    const plan = summary.repair_execution_plan;
    return (plan?.auto?.length || 0) + (plan?.setup_required?.length || 0) + (plan?.manual?.length || 0);
}

function planLabel(bucket: string) {
    if (bucket === 'auto') return '可自动返修';
    if (bucket === 'setup_required') return '需要先配置';
    return '人工确认';
}

function reportTitle(key: string) {
    if (key.startsWith('scene_')) return `分镜 ${key.replace('scene_', '')} 抽帧审核`;
    return names[key] || key;
}

function Scores({review}: {review: any}) {
    if (!review) return null;
    return <>
        <div className="wb-fields">
            {Object.entries(review)
                .filter(([, value]: any) => typeof value?.score === 'number')
                .map(([key, value]: any) => <div key={key}>
                    <h3>{names[key] || key} · {value.score}/5</h3>
                    <p className="wb-muted">{value.evidence}</p>
                </div>)}
        </div>
        {review.issues?.map((issue: any, index: number) => <p key={index} className="wb-alert">
            {issue.severity} · 分镜 {issue.scene_number || '-'} · {issue.description || issue.message || issue.evidence || JSON.stringify(issue)}
        </p>)}
    </>;
}

function MediaLink({projectId, path, label}: {projectId: number; path?: string; label: string}) {
    const [url, setUrl] = useState('');
    const [failed, setFailed] = useState(false);
    useEffect(() => {
        let active = true;
        setUrl('');
        setFailed(false);
        if (!path) return;
        projectApi.mediaUrl(projectId, path)
            .then(link => { if (active) setUrl(link); })
            .catch(() => { if (active) setFailed(true); });
        return () => { active = false; };
    }, [projectId, path]);
    if (!path) return null;
    if (url) return <a className="wb-button" href={url} target="_blank" rel="noreferrer">{label}</a>;
    return <span className="wb-muted">{failed ? `${label}不可预览` : `${label}加载中`}</span>;
}

function SeedDanceComparison({projectId, report}: {projectId: number; report: any}) {
    if (report?.kind !== 'seed_dance_baseline_comparison') return null;
    const gates = Object.entries(report.gates || {});
    const differences = report.differences || {};
    const candidate = report.candidate || {};
    const baseline = report.baseline || {};
    const gateLabels: Record<string, string> = {
        visual_structure_reference_available: '画面结构证据可用',
        visual_structure_not_diverged: '画面结构未明显偏离',
        motion_not_static: '运动量未塌陷',
        sharpness_not_collapsed: '清晰度未塌陷',
        no_temporal_visual_resets: '无重复视觉跳变',
        no_extreme_temporal_visual_reset: '无极端视觉跳变',
    };
    return <div>
        <div className="wb-fields">
            <div><h3>时长差</h3><p className="wb-muted">{differences.duration_delta_seconds ?? '-'} 秒</p></div>
            <div><h3>运动量比例</h3><p className="wb-muted">{differences.motion_energy_ratio ?? '-'}</p></div>
            <div><h3>清晰度比例</h3><p className="wb-muted">{differences.sharpness_ratio ?? '-'}</p></div>
            <div><h3>画面结构相似度</h3><p className="wb-muted">{differences.visual_structure_similarity ?? '未生成'}{typeof differences.visual_structure_similarity === 'number' ? ' / 1' : ''}</p></div>
            <div><h3>候选规格</h3><p className="wb-muted">{candidate.width || '-'}x{candidate.height || '-'} · {candidate.fps || '-'} fps</p></div>
            <div><h3>基线规格</h3><p className="wb-muted">{baseline.width || '-'}x{baseline.height || '-'} · {baseline.fps || '-'} fps</p></div>
            <div><h3>候选内容指纹</h3><p className="wb-muted" title={report.candidate_sha256 || '未记录'}>{report.candidate_sha256 ? report.candidate_sha256.slice(0, 12) : '未记录'}</p></div>
            <div><h3>基线内容指纹</h3><p className="wb-muted" title={report.baseline_sha256 || '未记录'}>{report.baseline_sha256 ? report.baseline_sha256.slice(0, 12) : '未记录'}</p></div>
        </div>
        {gates.length > 0 && <div className="wb-grid compact">
            {gates.map(([key, passed]) => <div className="wb-kv" key={key}>
                <span>{gateLabels[key] || key}</span>
                <strong>{passed ? '通过' : '未通过'}</strong>
            </div>)}
        </div>}
        <div className="wb-row" style={{marginTop: 12}}>
            <MediaLink projectId={projectId} path={report.candidate_video_path} label="候选视频"/>
            <MediaLink projectId={projectId} path={report.baseline_video_path || report.uploaded_baseline_path} label="基线视频"/>
        </div>
        {report.contact_sheet_path && <figure className="wb-comparison-sheet">
            <ProjectImage projectId={projectId} path={report.contact_sheet_path} alt="Seed Dance 对照抽帧"/>
            <figcaption className="wb-muted">上排为候选视频，下排为 Seed Dance 基线视频。</figcaption>
        </figure>}
    </div>;
}

function SequenceBoundaryEvidence({report}: {report: any}) {
    if (report?.kind !== 'sequence_boundary_continuity') return null;
    const failed = report.status !== 'available'
        || Number(report.severe_transition_count || 0) > 0
        || Number(report.severe_style_transition_count || 0) > 0
        || Number(report.geometry_mismatch_count || 0) > 0
        || Number(report.fps_mismatch_count || 0) > 0
        || Number(report.pixel_format_mismatch_count || 0) > 0
        || Number(report.audio_format_mismatch_count || 0) > 0;
    const boundaries = Array.isArray(report.boundaries) ? report.boundaries : [];
    const boundaryIssues = boundaries.filter((boundary: any) => (
        boundary.severe_exposure_or_black_transition
        || boundary.severe_style_transition
        || boundary.geometry_match === false
        || boundary.fps_match === false
        || boundary.pixel_format_match === false
        || boundary.audio_format_match === false
    )).slice(0, 6);
    return <div className="wb-summary-actions" aria-label="多镜头边界连续性证据">
        <h4>多镜头边界连续性</h4>
        <p className={failed ? 'wb-alert' : 'wb-muted'}>
            {failed ? '边界证据未通过，禁止交付。' : `已检查 ${report.boundary_count || 0} 个镜头边界。`}
        </p>
        <div className="wb-grid compact">
            <div className="wb-kv"><span>严重转场</span><strong>{report.severe_transition_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>风格跳变</span><strong>{report.severe_style_transition_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>画幅不一致</span><strong>{report.geometry_mismatch_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>帧率不一致</span><strong>{report.fps_mismatch_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>像素格式不一致</span><strong>{report.pixel_format_mismatch_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>音频格式不一致</span><strong>{report.audio_format_mismatch_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>报告任务</span><strong>{report.sequence_task_id || '-'}</strong></div>
        </div>
        {boundaryIssues.length > 0 && <div className="wb-fields" aria-label="边界异常明细">
            {boundaryIssues.map((boundary: any) => {
                const issues = [
                    boundary.severe_exposure_or_black_transition && '曝光/黑帧跳变',
                    boundary.severe_style_transition && '色彩/对比度跳变',
                    boundary.geometry_match === false && '画幅',
                    boundary.fps_match === false && '帧率',
                    boundary.pixel_format_match === false && '像素格式',
                    boundary.audio_format_match === false && '音频格式',
                ].filter(Boolean).join('、');
                return <p key={boundary.boundary_index} className="wb-alert">边界 {boundary.boundary_index}：{issues}</p>;
            })}
        </div>}
    </div>;
}

function StoryRoomEvidence({report}: {report: any}) {
    if (report?.kind !== 'story_room_quality') return null;
    const beats = report.signals?.beat_contract || {};
    const progression = report.signals?.ordered_progression || {};
    const sceneList = (value: unknown) => Array.isArray(value) && value.length
        ? value.join('、')
        : '—';
    const beatLabels: Record<string, string> = {
        hook: '开场钩子',
        escalation: '冲突升级',
        reversal: '中段反转',
        payoff: '情绪回收',
        cliffhanger: '结尾悬念',
    };
    return <div className="wb-summary-actions" aria-label="故事房质量证据">
        <div className="wb-row wb-between">
            <h4>故事房质量证据</h4>
            <span className="wb-badge">{report.score ?? 0}/9</span>
        </div>
        <div className="wb-grid compact">
            {Object.entries(beatLabels).map(([key, label]) => {
                const beat = beats[key] || {};
                return <div className="wb-kv" key={key}>
                    <span>{label}</span><strong>{beat.detected ? '已检测' : '缺失'}</strong>
                </div>;
            })}
        </div>
        {report.missing?.length ? <p className="wb-alert">缺项：{report.missing.join('、')}</p> : <p className="wb-muted">关键节奏证据完整，输入哈希：{String(report.input_hash || '').slice(0, 12)}</p>}
        <div className="wb-grid compact" aria-label="节拍位置证据">
            <div className="wb-kv"><span>钩子分镜</span><strong>{sceneList(progression.hook_scenes)}</strong></div>
            <div className="wb-kv"><span>反转分镜</span><strong>{sceneList(progression.reversal_scenes)}</strong></div>
            <div className="wb-kv"><span>兑现/悬念分镜</span><strong>{sceneList(progression.payoff_or_cliffhanger_scenes)}</strong></div>
        </div>
        <p className={progression.detected ? 'wb-muted' : 'wb-alert'}>
            {progression.detected ? '节拍顺序有效：钩子 → 反转 → 兑现/悬念。' : '节拍顺序无效：需要把反转放在兑现或结尾悬念之前。'}
        </p>
    </div>;
}

function EpisodeStyleConsistencyEvidence({report}: {report: any}) {
    if (report?.kind !== 'episode_style_consistency') return null;
    const scenes = Array.isArray(report.scenes) ? report.scenes : [];
    const issues = Array.isArray(report.issues) ? report.issues : [];
    return <div className="wb-summary-actions" aria-label="全集视觉风格一致性证据">
        <div className="wb-row wb-between">
            <h4>全集视觉风格一致性</h4>
            <span className="wb-badge">{report.sampled_count || 0}/{report.scene_count || 0} 个关键帧</span>
        </div>
        <p className={issues.length ? 'wb-alert' : 'wb-muted'}>
            {issues.length ? `发现 ${issues.length} 项跨镜头风格漂移，建议先按视觉圣经返工。` : '曝光、饱和度、对比度、清晰度和画幅整体稳定。'}
        </p>
        {scenes.length > 0 && <div className="wb-grid compact">
            {scenes.slice(0, 8).map((scene: any) => <div className="wb-kv" key={scene.scene_number}>
                <span>分镜 {scene.scene_number}</span>
                <strong>{scene.width || '-'}×{scene.height || '-'} · {scene.brightness ?? '-'}亮度</strong>
            </div>)}
        </div>}
        {issues.slice(0, 6).map((issue: any, index: number) => <p className="wb-alert" key={`${issue.code}-${issue.scene_number}-${index}`}>
            分镜 {issue.scene_number || '-'} · {issue.code} · {issue.evidence || issue.recommendation}
        </p>)}
    </div>;
}

function CharacterIdentityConsistencyEvidence({report}: {report: any}) {
    if (report?.kind !== 'character_identity_consistency') return null;
    const observations = Array.isArray(report.observations) ? report.observations : [];
    const issues = Array.isArray(report.issues) ? report.issues : [];
    return <div className="wb-summary-actions" aria-label="角色跨镜头身份一致性证据">
        <div className="wb-row wb-between">
            <h4>角色跨镜头身份一致性</h4>
            <span className="wb-badge">{report.character_count || 0} 个角色 · {report.observation_count || 0} 次观察</span>
        </div>
        <p className={issues.length ? 'wb-alert' : 'wb-muted'}>
            {issues.length ? `发现 ${issues.length} 项身份漂移，需重新绑定角色身份资产。` : '已通过已有角色身份审核证据聚合。'}
        </p>
        {observations.slice(0, 10).map((observation: any) => <div className="wb-kv" key={`${observation.character}-${observation.scene_number}`}>
            <span>{observation.character} · 分镜 {observation.scene_number}</span>
            <strong>{observation.score}/5</strong>
        </div>)}
        {issues.slice(0, 6).map((issue: any, index: number) => <p className="wb-alert" key={`${issue.code}-${issue.character}-${index}`}>
            {issue.character || '角色'} · {issue.evidence || issue.recommendation}
        </p>)}
    </div>;
}

function DialogueDeliveryEvidence({report}: {report: any}) {
    if (report?.kind !== 'dialogue_delivery_audit') return null;
    const scenes = Array.isArray(report.scenes) ? report.scenes : [];
    const issues = Array.isArray(report.issues) ? report.issues : [];
    return <div className="wb-summary-actions" aria-label="对白音频与字幕交付证据">
        <div className="wb-row wb-between">
            <h4>对白音频与字幕交付</h4>
            <span className="wb-badge">{report.cues_count || 0} 条字幕 cue</span>
        </div>
        <p className={issues.length ? 'wb-alert' : 'wb-muted'}>
            {issues.length ? `发现 ${issues.length} 项对白交付问题，成片暂不可交付。` : `已检查 ${report.checked_scene_count || 0} 个对白镜头。`}
        </p>
        {scenes.slice(0, 8).map((scene: any) => <div className="wb-kv" key={scene.scene_number}>
            <span>分镜 {scene.scene_number}</span>
            <strong>{scene.audio_present ? '音频' : '缺音频'} · {scene.subtitle_cues || 0} cue</strong>
        </div>)}
        {issues.slice(0, 6).map((issue: any, index: number) => <p className="wb-alert" key={`${issue.code}-${issue.scene_number}-${index}`}>
            分镜 {issue.scene_number || '-'} · {issue.code} · {issue.message}
        </p>)}
    </div>;
}

function GenerationContextEvidence({report}: {report: any}) {
    if (report?.kind !== 'generation_context_audit') return null;
    const contexts = Array.isArray(report.contexts) ? report.contexts : [];
    const issues = Array.isArray(report.issues) ? report.issues : [];
    return <div className="wb-summary-actions" aria-label="生成上下文一致性证据">
        <div className="wb-row wb-between">
            <h4>生成上下文一致性</h4>
            <span className="wb-badge">{report.context_count || 0} 组上下文</span>
        </div>
        <p className={issues.length ? 'wb-alert' : 'wb-muted'}>
            {issues.length ? '发现镜头之间的 Provider、模型或输出契约漂移。' : `已核对 ${report.checked_scene_count || 0} 个镜头的生成上下文。`}
        </p>
        {contexts.slice(0, 8).map((context: any) => <div className="wb-kv" key={context.scene_number}>
            <span>分镜 {context.scene_number}</span>
            <strong>{context.provider_model || '-'} · {context.resolution || '-'} · {context.request_mode || '-'}</strong>
        </div>)}
        {issues.slice(0, 5).map((issue: any, index: number) => <p className="wb-alert" key={`${issue.code}-${index}`}>
            {issue.code} · {issue.evidence || issue.recommendation}
        </p>)}
    </div>;
}

function AtomicVideoMotionEvidence({report}: {report: any}) {
    if (report?.kind !== 'atomic_video_motion_audit') return null;
    const scenes = Array.isArray(report.scenes) ? report.scenes : [];
    const issues = Array.isArray(report.issues) ? report.issues : [];
    return <div className="wb-summary-actions" aria-label="原子镜头运动质量证据">
        <div className="wb-row wb-between">
            <h4>原子镜头运动质量</h4>
            <span className="wb-badge">已检查 {report.checked_scene_count || 0} 镜头</span>
        </div>
        <p className={issues.length ? 'wb-alert' : 'wb-muted'}>
            {issues.length ? `发现 ${issues.length} 项冻结、黑帧、抖动或技术分异常。` : '原子镜头运动与技术质量均在门禁范围内。'}
        </p>
        {scenes.slice(0, 8).map((scene: any) => <div className="wb-kv" key={scene.scene_number}>
            <span>分镜 {scene.scene_number}</span>
            <strong>技术分 {scene.technical_score ?? '-'} · 运动 {scene.motion_energy ?? '-'}</strong>
        </div>)}
        {issues.slice(0, 6).map((issue: any, index: number) => <p className="wb-alert" key={`${issue.code}-${issue.scene_number}-${index}`}>
            分镜 {issue.scene_number || '-'} · {issue.code} · {issue.message}
        </p>)}
    </div>;
}

function FirstFrameConsistencyEvidence({report}: {report: any}) {
    if (report?.kind !== 'first_frame_consistency_audit') return null;
    const scenes = Array.isArray(report.scenes) ? report.scenes : [];
    const issues = Array.isArray(report.issues) ? report.issues : [];
    return <div className="wb-summary-actions" aria-label="锁定关键帧首帧一致性证据">
        <div className="wb-row wb-between">
            <h4>锁定关键帧首帧一致性</h4>
            <span className="wb-badge">已检查 {report.checked_scene_count || 0} 镜头</span>
        </div>
        <p className={issues.length ? 'wb-alert' : 'wb-muted'}>
            {issues.length ? `发现 ${issues.length} 项首帧偏离或证据缺失，成片暂不可交付。` : '每个参考图生视频镜头的首帧均通过锁定关键帧门禁。'}
        </p>
        {scenes.slice(0, 8).map((scene: any) => <div className="wb-kv" key={scene.scene_number}>
            <span>分镜 {scene.scene_number}</span>
            <strong>{scene.status === 'available' ? `引用分 ${scene.score ?? '-'}/5` : scene.status || '缺失'}</strong>
        </div>)}
        {issues.slice(0, 6).map((issue: any, index: number) => <p className="wb-alert" key={`${issue.code}-${issue.scene_number}-${index}`}>
            分镜 {issue.scene_number || '-'} · {issue.code} · {issue.message}
        </p>)}
    </div>;
}

function SequenceTimelineEvidence({report}: {report: any}) {
    if (report?.kind !== 'sequence_timeline_audit') return null;
    const segments = Array.isArray(report.segments) ? report.segments : [];
    const issues = Array.isArray(report.issues) ? report.issues : [];
    return <div className="wb-summary-actions" aria-label="多镜头时间轴一致性证据">
        <div className="wb-row wb-between">
            <h4>多镜头时间轴一致性</h4>
            <span className="wb-badge">计划 {report.planned_count || 0} · 实际 {report.actual_count || 0}</span>
        </div>
        <p className={issues.length ? 'wb-alert' : 'wb-muted'}>
            {issues.length ? '分段后的实际时长与计划不一致，字幕和对白可能整体漂移。' : '多镜头分段时长与计划时间轴一致。'}
        </p>
        {segments.slice(0, 8).map((segment: any) => <div className="wb-kv" key={segment.scene_number}>
            <span>分镜 {segment.scene_number}</span>
            <strong>{segment.planned_duration_seconds ?? '-'}s → {segment.actual_duration_seconds ?? '-'}s</strong>
        </div>)}
        {issues.slice(0, 5).map((issue: any, index: number) => <p className="wb-alert" key={`${issue.code}-${index}`}>
            {issue.scene_number ? `分镜 ${issue.scene_number} · ` : ''}{issue.code} · {issue.message}
        </p>)}
    </div>;
}

function ProviderTrace({report}: {report: any}) {
    const metadata = report?.selected_provider_metadata || report?.provider_metadata || report?.final_video_review?.provider_metadata;
    if (!metadata || typeof metadata !== 'object') return null;
    const trace = {
        ...metadata,
        provider_model: metadata.provider_model || metadata.requested_model,
    };
    const fields = [
        ['provider_name', 'Provider'],
        ['provider_model', '实际模型'],
        ['provider_task_id', '远端任务 ID'],
        ['provider_status', '远端状态'],
        ['provider_created_at', '创建时间'],
        ['provider_expires_at', '过期时间'],
        ['provider_duration_seconds', '实际时长'],
    ].filter(([key]) => trace[key] !== undefined && trace[key] !== null && trace[key] !== '');
    if (!fields.length) return null;
    return <div className="wb-summary-actions" aria-label="远端生成追踪">
        <h4>远端生成追踪</h4>
        <div className="wb-grid compact">
            {fields.map(([key, label]) => <div className="wb-kv" key={key}>
                <span>{label}</span><strong>{String(trace[key])}</strong>
            </div>)}
        </div>
    </div>;
}

function OutputContractEvidence({report}: {report: any}) {
    const audit = report?.request_contract_audit || report?.final_video_review?.request_contract_audit;
    if (!audit || audit.status === 'not_applicable') return null;
    const failed = audit.status !== 'passed';
    return <div className="wb-summary-actions" aria-label="视频输出契约验收">
        <h4>视频输出契约验收</h4>
        <p className={failed ? 'wb-alert' : 'wb-muted'}>
            {failed ? '输出与请求契约不一致，已阻止接受。' : `已核对 ${audit.checked?.length || 0} 项输出契约。`}
        </p>
        {audit.issues?.map((issue: any, index: number) => <p className="wb-alert" key={index}>
            {issue.code} · {issue.message}
        </p>)}
    </div>;
}

function ReferenceAssetEvidence({report}: {report: any}) {
    const metadata = report?.selected_provider_metadata || report?.provider_metadata || report?.final_video_review?.provider_metadata;
    const assets = metadata?.request_contract?.reference_assets;
    if (!Array.isArray(assets) || !assets.length) return null;
    return <div className="wb-summary-actions" aria-label="参考资产绑定证据">
        <h4>参考资产绑定</h4>
        <p className="wb-muted">已记录实际发送给视频模型的参考素材及内容指纹。</p>
        <div className="wb-grid compact">
            {assets.map((asset: any, index: number) => <div className="wb-kv" key={`${asset.role || 'asset'}-${asset.index || index}`}>
                <span>{asset.role || 'reference'}{asset.index ? ` #${asset.index}` : ''}</span>
                <strong>{asset.kind || 'unknown'}{asset.sha256 ? ` · ${String(asset.sha256).slice(0, 12)}` : ''}</strong>
            </div>)}
        </div>
    </div>;
}

function GenerationRunEvidence({report}: {report: any}) {
    const evidence = report?.generation_run_evidence || report?.final_video_review?.generation_run_evidence;
    const attempts = evidence?.attempts;
    if (!evidence || !attempts) return null;
    const failed = evidence.status !== 'passed';
    return <div className="wb-summary-actions" aria-label="视频生成运行证据">
        <h4>视频生成运行证据</h4>
        <p className={failed ? 'wb-alert' : 'wb-muted'}>
            {failed ? '候选生成尚未形成可接受结果。' : '候选生成与提升结果已记录。'}
        </p>
        <div className="wb-grid compact">
            <div className="wb-kv"><span>候选尝试</span><strong>{attempts.candidate_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>生成成功</span><strong>{attempts.generated_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>质量通过</span><strong>{attempts.passed_count ?? '-'}</strong></div>
            <div className="wb-kv"><span>通过率</span><strong>{typeof attempts.pass_rate === 'number' ? `${Math.round(attempts.pass_rate * 100)}%` : '-'}</strong></div>
            <div className="wb-kv"><span>总耗时</span><strong>{attempts.elapsed_seconds_sum ?? '-'} 秒</strong></div>
            <div className="wb-kv"><span>最长单次</span><strong>{attempts.elapsed_seconds_max ?? '-'} 秒</strong></div>
        </div>
        {evidence.providers?.length ? <p className="wb-muted">Provider：{evidence.providers.join('、')}</p> : null}
        {evidence.provider_task_ids?.length ? <p className="wb-muted">任务：{evidence.provider_task_ids.join('、')}</p> : null}
        {evidence.video_sha256s?.length ? <p className="wb-muted">候选视频指纹：{evidence.video_sha256s.slice(0, 3).map((hash: string) => hash.slice(0, 12)).join('、')}</p> : null}
        {evidence.accepted_video_sha256 ? <p className="wb-muted" title={evidence.accepted_video_sha256}>最终验收视频指纹：{evidence.accepted_video_sha256.slice(0, 12)}</p> : null}
        {evidence.spatial_scene_contract_hashes?.length ? (
            <p className="wb-muted">空间 scene contract：{evidence.spatial_scene_contract_hashes.slice(0, 3).map((hash: string) => hash.slice(0, 12)).join('、')}</p>
        ) : null}
        {evidence.spatial_project_signatures?.length ? (
            <p className="wb-muted">空间项目签名：{evidence.spatial_project_signatures.slice(0, 2).map((hash: string) => hash.slice(0, 12)).join('、')}</p>
        ) : null}
    </div>;
}

function FinalCompositionEvidence({projectId, report}: {projectId: number; report: any}) {
    if (report?.stage !== 'final_composition') return null;
    const metrics = report.final_technical_metrics || {};
    const audioMix = report.audio_mix || {};
    const audioStrategy = audioMix.strategy === 'sidechain_ducking'
        ? '对白 ducking'
        : audioMix.strategy === 'music_only' ? '仅 BGM' : '无 BGM';
    return <div className="wb-summary-actions" aria-label="最终合成技术证据">
        <h4>最终合成技术证据</h4>
        <div className="wb-grid compact">
            <div className="wb-kv"><span>成片</span><MediaLink projectId={projectId} path={report.video_path} label="打开最终成片"/></div>
            <div className="wb-kv"><span>规格</span><strong>{metrics.width || '-'}×{metrics.height || '-'} · {metrics.fps || '-'} fps</strong></div>
            <div className="wb-kv"><span>时长</span><strong>{metrics.duration_seconds ?? '-'} 秒</strong></div>
            <div className="wb-kv"><span>音频</span><strong>{metrics.audio_quality_status || (metrics.audio_present ? '存在' : '未检测')}</strong></div>
            <div className="wb-kv"><span>响度</span><strong>{typeof metrics.audio_integrated_lufs === 'number' ? `${metrics.audio_integrated_lufs.toFixed(2)} LUFS · 峰值 ${typeof metrics.audio_true_peak_db === 'number' ? `${metrics.audio_true_peak_db.toFixed(2)} dBFS` : '-'}` : '未测量'}</strong></div>
            <div className="wb-kv"><span>混音策略</span><strong>{audioStrategy}</strong></div>
            <div className="wb-kv"><span>技术分</span><strong>{report.technical_score ?? metrics.technical_score ?? '-'}</strong></div>
        </div>
    </div>;
}

function VideoCandidateSelectionEvidence({projectId, report}: {projectId: number; report: any}) {
    if (report?.kind !== 'video_candidate_selection') return null;
    const candidates = Array.isArray(report.candidates) ? report.candidates : [];
    const componentLabels: Record<string, string> = {
        platform: '平台审美',
        review_average: '审核均分',
        technical: '技术质量',
        character_distinctiveness: '角色区分',
        performance: '表演表现',
        aesthetic: '视频审美',
        platform_reference: '基线参考',
        critical_floor: '关键短板',
    };
    const score = (value: unknown) => typeof value === 'number' ? value.toFixed(2) : '-';
    return <div className="wb-summary-actions" aria-label="视频候选选择证据">
        <h4>视频候选选择</h4>
        <p className="wb-muted">已按通过门禁、关键短板和多维质量分选择候选；分项分数用于复盘，不代表人工审美结论。</p>
        <div className="wb-grid compact">
            <div className="wb-kv"><span>候选数</span><strong>{candidates.length}</strong></div>
            <div className="wb-kv"><span>选中分数</span><strong>{score(report.selected_selection_score)}</strong></div>
            <div className="wb-kv"><span>选中关键短板</span><strong>{score(report.selected_critical_floor_score)}</strong></div>
        </div>
        {candidates.slice(0, 5).map((candidate: any, index: number) => {
            const selected = candidate.path && candidate.path === report.selected_path;
            const components = candidate.selection_components || {};
            const openingFrame = candidate.technical_metrics?.start_frame_reference;
            const openingFrameLabel = openingFrame?.status === 'available'
                ? `首帧一致 ${score(openingFrame.score)}`
                : openingFrame?.status === 'not_applicable' ? '首帧一致 不适用' : '首帧一致 证据缺失';
            return <div className={`wb-issue ${selected ? 'warning' : ''}`} key={`${candidate.index || index}-${candidate.path || index}`}>
                <span>{selected ? '已选' : `候选 ${candidate.index || index + 1}`}</span>
                <div>
                    <p>总分 {score(candidate.selection_score)} · 关键短板 {score(candidate.critical_floor_score)} · {openingFrameLabel}</p>
                    <p className="wb-muted">{Object.entries(componentLabels).map(([key, label]) => `${label} ${score(components[key])}`).join(' · ')}</p>
                    {candidate.path && <ProjectVideo projectId={projectId} path={candidate.path} label={selected ? '已选视频' : '候选视频'}/>}
                    <MediaLink projectId={projectId} path={candidate.path} label={selected ? '打开已选视频' : '打开候选视频'}/>
                </div>
            </div>;
        })}
    </div>;
}

function ImageCandidateSelectionEvidence({projectId, report}: {projectId: number; report: any}) {
    if (report?.kind !== 'image_candidate_selection') return null;
    const candidates = Array.isArray(report.candidates) ? report.candidates : [];
    const componentLabels: Record<string, string> = {
        platform: '平台审美',
        review_average: '审核均分',
        technical: '技术质量',
        character_distinctiveness: '角色区分',
        platform_reference: '基线参考',
    };
    const score = (value: unknown) => typeof value === 'number' ? value.toFixed(2) : '-';
    return <div className="wb-summary-actions" aria-label="图像候选选择证据">
        <h4>关键帧候选选择</h4>
        <p className="wb-muted">已按通过门禁、关键短板和多维质量分选择关键帧；分项分数用于复盘，不代表人工审美结论。</p>
        <div className="wb-grid compact">
            <div className="wb-kv"><span>候选数</span><strong>{candidates.length}</strong></div>
            <div className="wb-kv"><span>选中分数</span><strong>{score(report.best_selection_score)}</strong></div>
            <div className="wb-kv"><span>选中关键短板</span><strong>{score(report.best_critical_floor_score)}</strong></div>
        </div>
        {candidates.slice(0, 5).map((candidate: any, index: number) => {
            const selected = candidate.index === report.best_index;
            const components = candidate.selection_components || {};
            return <div className={`wb-issue ${selected ? 'warning' : ''}`} key={`${candidate.index || index}-${candidate.path || index}`}>
                <span>{selected ? '已选' : `候选 ${candidate.index || index + 1}`}</span>
                <div>
                    <p>总分 {score(candidate.selection_score)} · 关键短板 {score(candidate.critical_floor_score)}</p>
                    <p className="wb-muted">{Object.entries(componentLabels).map(([key, label]) => `${label} ${score(components[key])}`).join(' · ')}</p>
                    {candidate.path && <ProjectImage projectId={projectId} path={candidate.path} alt={selected ? '已选关键帧' : '候选关键帧'}/>}
                    <MediaLink projectId={projectId} path={candidate.path} label={selected ? '打开已选关键帧' : '打开候选关键帧'}/>
                </div>
            </div>;
        })}
    </div>;
}

function ReviewSummary({
    summary,
    qualityPlan,
    actionFilter,
    onActionFilterChange,
    busy,
    onRepair,
    onAutoRepair,
    onSetupRepair,
}: {
    summary?: GenerationReviewSummary;
    qualityPlan?: QualityLoopPlan;
    actionFilter: string;
    onActionFilterChange: (action: string) => void;
    busy: boolean;
    onRepair: (sceneNumber: number, action: string) => void;
    onAutoRepair: () => void;
    onSetupRepair: (item: {action?: string; scene_number?: number}) => void;
}) {
    if (!summary) return null;
    const reportEntries = Object.entries(summary.reports || {}).filter(([key]) => !key.startsWith('story_attempt'));
    const isReady = summary.status === 'ready';
    const repairPlan = summary.repair_execution_plan;
    const plannedActions = repairPlanCount(summary);
    const repairActionOptions = Object.keys(summary.repair_queue?.actions || {}).filter(action => automaticRepairActions.has(action));
    return <section className={`wb-panel wb-review-summary ${isReady ? 'ready' : 'blocked'}`} aria-label="审核摘要">
        <div className="wb-row wb-between">
            <div className="wb-row">
                {isReady ? <CheckCircle2 size={19}/> : <AlertTriangle size={19}/>}
                <h3>整体结论</h3>
                <span className={`wb-score ${summary.status}`}>{statuses[summary.status] || summary.status}</span>
            </div>
            <div className="wb-row">
                <span className="wb-badge">需拆分 {summary.shot_complexity?.needs_split ?? 0}</span>
                <span className="wb-badge">警告 {summary.shot_complexity?.warn ?? 0}</span>
                <span className="wb-badge">过期 {summary.stale_reports?.length ?? 0}</span>
            </div>
        </div>
        {summary.action_items?.length ? <div className="wb-summary-actions">
            <h3>下一步动作</h3>
            {summary.action_items.map((item) => <p key={item} className="wb-alert">{labelAction(item)}</p>)}
        </div> : <p className="wb-muted">关键门禁已通过，可以继续进入最终合成或人工抽检。</p>}
        {summary.human_final_review_required && <div className="wb-summary-actions">
            <h3>最终整集人工审核</h3>
            <p className={summary.human_final_review_status === 'approved' ? 'wb-muted' : 'wb-alert'}>
                {summary.human_final_review_status === 'approved'
                    ? '已人工通过，允许进入交付打包。'
                    : '尚未人工通过；交付打包会被阻断。'}
            </p>
        </div>}
        {qualityPlan && <div className="wb-summary-actions">
            <div className="wb-row wb-between">
                <div>
                    <h3>质量闭环计划</h3>
                    <p className="wb-muted">{loopStatusLabels[qualityPlan.status] || qualityPlan.status} · {qualityPlan.next_step}</p>
                </div>
                <div className="wb-row">
                    <label className="wb-inline-field">动作
                        <select value={actionFilter} disabled={busy} onChange={event => onActionFilterChange(event.target.value)}>
                            <option value="">全部自动动作</option>
                            {repairActionOptions.map(action => <option value={action} key={action}>{labelRepairAction(action)}</option>)}
                        </select>
                    </label>
                    <button className="wb-button primary" disabled={busy || !qualityPlan.selected?.length} onClick={onAutoRepair}>
                    <RefreshCw size={16} className={busy ? 'animate-spin' : ''}/>批量自动返工
                    </button>
                </div>
            </div>
            {qualityPlan.selected?.slice(0, 5).map((item, index) => <div className="wb-issue warning" key={`quality-loop-${item.action}-${index}`}>
                <span>{item.scene_number ? `分镜 ${item.scene_number}` : item.stage || '全局'}</span>
                <p>{labelRepairAction(item.action)}：{item.recommendation || item.reason}</p>
            </div>)}
            {qualityPlan.setup_required?.length ? <div className="wb-issue warning">
                <span>配置动作</span>
                <div>
                    <p>还有 {qualityPlan.setup_required.length} 项需要先补资产、workflow 或本地审核服务。</p>
                    {qualityPlan.setup_required.slice(0, 5).map((item, index) => (
                        <div className="wb-row wb-between" key={`setup-repair-${item.action}-${item.scene_number || index}`}>
                            <span className="wb-muted">{item.scene_number ? `分镜 ${item.scene_number} · ` : ''}{labelRepairAction(item.action)}</span>
                            {executableSetupRepair(item.action, item.scene_number) && (
                                <button className="wb-button" disabled={busy} onClick={() => onSetupRepair(item)}>
                                    执行
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            </div> : null}
            {qualityPlan.manual_actions?.length ? <p className="wb-alert">还有 {qualityPlan.manual_actions.length} 项需要人工复核后再选择动作。</p> : null}
        </div>}
        {summary.repair_cycles?.length ? <div className="wb-summary-actions">
            <h3>返工周期记录</h3>
            {summary.repair_cycles.slice(0, 3).map((cycle) => <div className="wb-kv" key={cycle.cycle_id}>
                <span>{new Date(cycle.created_at).toLocaleString()} · {cycle.status}</span>
                <strong>提交 {cycle.submitted_count} · 跳过 {cycle.skipped_count}</strong>
            </div>)}
        </div> : null}
        {summary.repair_queue?.total ? <div className="wb-summary-actions">
            <h3>返工队列 · {summary.repair_queue.total}</h3>
            <div className="wb-grid compact">
                {Object.entries(summary.repair_queue.actions || {}).map(([action, count]) => <div className="wb-kv" key={action}>
                    <span>{labelRepairAction(action)}</span>
                    <strong>{count}</strong>
                </div>)}
            </div>
            {summary.repair_queue.items?.slice(0, 6).map((item, index) => <div key={`${item.source_report}-${item.action}-${index}`} className={`wb-issue ${item.priority === 'high' ? 'blocker' : 'warning'}`}>
                <span>{item.priority === 'high' ? '高' : '中'}</span>
                <p>{item.scene_number ? `分镜 ${item.scene_number} · ` : ''}{labelRepairAction(item.action)}：{item.recommendation || item.reason}</p>
                {executableRepair(item.action, item.scene_number) && <button className="wb-button" disabled={busy} onClick={() => onRepair(Number(item.scene_number), String(item.action))}>执行</button>}
            </div>)}
        </div> : null}
        {plannedActions ? <div className="wb-summary-actions">
            <h3>返修重跑计划 · {plannedActions}</h3>
            {(['auto', 'setup_required', 'manual'] as const).map(bucket => {
                const items = repairPlan?.[bucket] || [];
                if (!items.length) return null;
                return <div key={bucket}>
                    <p className="wb-muted">{planLabel(bucket)}</p>
                    {items.slice(0, 4).map((item, index) => <div className="wb-issue warning" key={`${bucket}-${item.action}-${index}`}>
                        <span>{item.scene_number ? `分镜 ${item.scene_number}` : item.stage || '全局'}</span>
                        <p>{labelRepairAction(item.action)}：{item.rerun_strategy || item.recommendation || item.reason}</p>
                    </div>)}
                </div>;
            })}
            {repairPlan?.rerun_validation_commands?.length ? <div>
                <p className="wb-muted">复验命令</p>
                {repairPlan.rerun_validation_commands.slice(0, 5).map(command => <div className="wb-code" key={command}>{command}</div>)}
            </div> : null}
        </div> : null}
        {reportEntries.length > 0 && <div className="wb-grid compact" aria-label="报告状态">
            {reportEntries.map(([key, statusValue]) => <div className="wb-kv" key={key}>
                <span>{reportTitle(key)}</span>
                <strong>{statusValue ? statuses[statusValue] || statusValue : '未运行'}</strong>
            </div>)}
        </div>}
    </section>;
}

function HumanReviewActions({
    reports,
    onDecision,
    busy,
}: {reports: Record<string, any>; onDecision: (reportKey: string, decision: 'approved' | 'rejected') => void; busy: boolean}) {
    const pending = Object.entries(reports).filter(([, report]) => ['needs_review', 'review_unavailable'].includes(report?.status));
    if (!pending.length) return null;
    return <section className="wb-panel" aria-label="人工审核决策">
        <h3>人工审核决策</h3>
        <p className="wb-muted">决策绑定当前报告版本；剧情、成片或证据变化后会自动失效。</p>
        {pending.map(([key, report]) => <div className="wb-row wb-between" key={key}>
            <span>{reportTitle(key)} · {statuses[report.status] || report.status}</span>
            <span className="wb-row">
                <button className="wb-button" disabled={busy} onClick={() => onDecision(key, 'approved')}>人工通过</button>
                <button className="wb-button" disabled={busy} onClick={() => onDecision(key, 'rejected')}>驳回返工</button>
            </span>
        </div>)}
    </section>;
}

export function ReviewPanel({projectId, updatedAt}: {projectId: number; updatedAt: string}) {
    const [reports, setReports] = useState<Record<string, any>>({});
    const [summary, setSummary] = useState<GenerationReviewSummary | undefined>();
    const [qualityPlan, setQualityPlan] = useState<QualityLoopPlan | undefined>();
    const [actionFilter, setActionFilter] = useState('');
    const [error, setError] = useState('');
    const [baselinePath, setBaselinePath] = useState('');
    const [baselineFile, setBaselineFile] = useState<File | null>(null);
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        try {
            const [reviewData, planData] = await Promise.all([
                projectApi.reviews(projectId),
                projectApi.qualityLoopPlan(projectId, 5, actionFilter || undefined),
            ]);
            setReports(reviewData.reports);
            setSummary(reviewData.summary);
            setQualityPlan(planData.plan);
            setError('');
        } catch (e) {
            setError(errorText(e));
        }
    }, [actionFilter, projectId]);

    const compareBaseline = async () => {
        const baseline = baselinePath.trim();
        if (!baselineFile && !baseline) {
            setError('请上传 Seed Dance 基线视频，或填写服务端可访问的视频路径');
            return;
        }
        setBusy(true);
        setError('');
        try {
            if (baselineFile) {
                const report = await projectApi.uploadSeedDanceBaseline(projectId, baselineFile);
                await load();
                setError(`Seed Dance 基线对比完成：${report.status === 'passed' ? '技术门禁通过' : '需要复核'}。`);
            } else {
                const report = await projectApi.compareSeedDanceBaseline(projectId, {baseline_path: baseline});
                await load();
                setError(`Seed Dance 基线对比完成：${report.status === 'passed' ? '技术门禁通过' : '需要复核'}。`);
            }
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    const runRepair = async (sceneNumber: number, action: string) => {
        setBusy(true);
        setError('');
        try {
            await projectApi.repairScene(projectId, {scene_number: sceneNumber, action});
            await load();
            setError(`已提交分镜 ${sceneNumber} 的返工任务`);
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    const onSetupRepair = async (item: {action?: string; scene_number?: number}) => {
        if (!item.action) return;
        setBusy(true);
        setError('');
        try {
            if (item.action === 'refreeze_spatial_plan') {
                await projectApi.freezeSpatialPlan(projectId);
            } else if (item.action === 'fix_workflow_profile') {
                await projectApi.freezeWorkflowProfile();
            } else if (item.action === 'rewrite_short_drama_story_rhythm') {
                await projectApi.repairScript(projectId);
            } else if (item.action === 'fix_video_output_contract' && item.scene_number) {
                await projectApi.repairScene(projectId, {scene_number: item.scene_number, action: item.action});
            }
            await load();
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    const runAutoRepair = async () => {
        setBusy(true);
        setError('');
        try {
            const result = await projectApi.runAutoRepairQueue(projectId, {
                max_actions: 5,
                ...(actionFilter ? {action: actionFilter} : {}),
            });
            await load();
            const message = result.status === 'no_auto_actions'
                ? '当前项目没有匹配该动作的可执行分镜返修。'
                : result.status === 'manual_review_required'
                    ? '自动返修预算已耗尽，请先完成人工审核。'
                    : `已提交 ${result.submitted.length} 个自动返工动作，跳过 ${result.skipped.length} 个。`;
            setError(message);
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    const recordHumanReview = async (reportKey: string, decision: 'approved' | 'rejected') => {
        setBusy(true);
        setError('');
        try {
            const note = window.prompt('审核意见（可选）') || '';
            await projectApi.humanReview(projectId, {report_key: reportKey, decision, note});
            await load();
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    useEffect(() => { load(); }, [load, updatedAt]);

    return <section aria-label="质量审核">
        <div className="wb-row wb-between">
            <h2>审核结果</h2>
            <button className="wb-icon" aria-label="刷新审核" title="刷新审核" onClick={load}><RefreshCw size={17}/></button>
        </div>
        {error && <p className="wb-alert" role="alert">{error}</p>}
        <ReviewSummary summary={summary} qualityPlan={qualityPlan} actionFilter={actionFilter} onActionFilterChange={setActionFilter} busy={busy} onRepair={runRepair} onAutoRepair={runAutoRepair} onSetupRepair={onSetupRepair}/>
        <HumanReviewActions reports={reports} onDecision={recordHumanReview} busy={busy}/>
        <section className="wb-panel" aria-label="Seed Dance 基线对比">
            <div className="wb-row wb-between">
                <div>
                    <h3>Seed Dance 基线对比</h3>
                    <p className="wb-muted">上传 Seed Dance 参考视频，平台会用当前项目成片做对比。</p>
                </div>
                <button className="wb-button primary" disabled={busy || (!baselineFile && !baselinePath.trim())} onClick={compareBaseline}>
                    <RefreshCw size={16} className={busy ? 'animate-spin' : ''}/>{busy ? '对比中' : '开始对比'}
                </button>
            </div>
            <label style={{marginTop: 14}}>上传基线视频
                <input type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm" onChange={e => setBaselineFile(e.target.files?.[0] || null)}/>
            </label>
            <label style={{marginTop: 14}}>服务端视频路径（可选）
                <input value={baselinePath} onChange={e => setBaselinePath(e.target.value)} placeholder="例如 D:\baseline\seed-dance-reference.mp4"/>
            </label>
        </section>
        {!Object.keys(reports).length && !error && <p className="wb-muted">暂无审核记录</p>}
        {Object.entries(reports).filter(([key]) => !key.startsWith('story_attempt')).map(([key, report]) => <article className="wb-item" key={key}>
            <div className="wb-row">
                <h3>{reportTitle(key)}</h3>
                <span className={`wb-score ${report.status}`}>{statuses[report.status] || report.status}</span>
                {report.average != null && <strong>{report.average} / 5</strong>}
            </div>
            {report.error && <p className="wb-alert">{String(report.error)}</p>}
            <ProviderTrace report={report}/>
            <ReferenceAssetEvidence report={report}/>
            <OutputContractEvidence report={report}/>
            <GenerationRunEvidence report={report}/>
            <FinalCompositionEvidence projectId={projectId} report={report}/>
            <VideoCandidateSelectionEvidence projectId={projectId} report={report}/>
            <ImageCandidateSelectionEvidence projectId={projectId} report={report}/>
            <SeedDanceComparison projectId={projectId} report={report}/>
            <SequenceBoundaryEvidence report={report}/>
            <StoryRoomEvidence report={report}/>
            <EpisodeStyleConsistencyEvidence report={report}/>
            <CharacterIdentityConsistencyEvidence report={report}/>
            <DialogueDeliveryEvidence report={report}/>
            <GenerationContextEvidence report={report}/>
            <AtomicVideoMotionEvidence report={report}/>
            <FirstFrameConsistencyEvidence report={report}/>
            <SequenceTimelineEvidence report={report}/>
            <Scores review={report.review}/>
            {report.batches?.map((batch: any, index: number) => <div key={index}>
                <p>帧组 {index + 1} · {statuses[batch.status] || batch.status} · {batch.average}/5</p>
                <Scores review={batch.review}/>
            </div>)}
            {report.frames && <div className="wb-thumbnails">{report.frames.map((frame: any) => <figure key={frame.index}>
                <ProjectImage projectId={projectId} path={frame.path} alt={`抽帧 ${frame.index}`}/>
                <figcaption className="wb-muted">{Number(frame.timestamp).toFixed(2)} 秒</figcaption>
            </figure>)}</div>}
        </article>)}
    </section>;
}
