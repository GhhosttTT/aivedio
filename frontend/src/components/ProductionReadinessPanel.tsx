import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert } from 'lucide-react';
import type { ProductionReadinessReport, QualityScorecard } from '../api/client';

export function ProductionReadinessPanel({
    report,
    loading,
    onRefresh,
    onRepairAction,
    onApproveStoryRoom,
}: {
    report: ProductionReadinessReport | null;
    loading: boolean;
    onRefresh: () => void;
    onRepairAction?: (action: string) => void;
    onApproveStoryRoom?: () => void;
}) {
    const status = report?.status || 'loading';
    const blocked = status === 'blocked';
    const warning = status === 'needs_review';
    const Icon = blocked ? ShieldAlert : warning ? AlertTriangle : CheckCircle2;
    const label = blocked ? '生产被阻断' : warning ? '可草稿生成，正式成片需复查' : report ? '生产就绪' : '检查中';
    const issues = [...(report?.blockers || []), ...(report?.warnings || [])].slice(0, 5);
    const script = report?.checks.script;
    const storyRhythm = report?.checks.story_rhythm;
    const storyRoom = report?.checks.story_room;
    const storyApproval = storyRoom?.approval;
    const episodeRhythm = report?.checks.episode_rhythm;
    const topicBrief = report?.checks.topic_brief;
    const visualFormat = report?.checks.visual_format;
    const characters = report?.checks.characters;
    const complexity = report?.checks.shot_complexity;
    const spatial = report?.checks.spatial_continuity;
    const reviewer = report?.checks.reviewer;
    const workflowProfile = report?.checks.workflow_profile;
    const qualityGates = workflowProfile?.profile?.quality_gates || {};
    const capabilityEvidence = workflowProfile?.profile?.capability_evidence || {};
    const missingCapabilities = workflowProfile?.missing_capabilities || [];
    const profileGaps = [
        ...(workflowProfile?.missing || []),
        ...(workflowProfile?.stale || []),
        ...(workflowProfile?.quality_budget_issues || []),
    ];
    const sampleValidation = report?.checks.sample_validation;
    const qualityScorecard = sampleValidation?.quality_scorecard;
    const scorecardFocus = sampleValidation?.checks?.quality_scorecard_next_focus || qualityScorecard?.next_focus;
    const readinessActions = report?.repair_actions || [];
    return (
        <section className={`wb-panel wb-readiness ${blocked ? 'blocked' : warning ? 'needs_review' : 'ready'}`}>
            <div className="wb-row wb-between">
                <div className="wb-row">
                    <Icon size={19}/>
                    <div>
                        <h2>生产就绪</h2>
                        <p className="wb-muted">{label}</p>
                    </div>
                </div>
                <button className="wb-icon" title="刷新生产就绪检查" aria-label="刷新生产就绪检查" disabled={loading} onClick={onRefresh}>
                    <RefreshCw size={17} className={loading ? 'animate-spin' : ''}/>
                </button>
            </div>
            <div className="wb-grid compact">
                <Metric label="分镜" value={script ? `${script.scene_count}/${script.minimum_production_scenes}` : '未检查'}/>
                <Metric label="剧情节奏" value={storyRhythm ? `${storyRhythm.score}/5 ${storyRhythm.status}` : '未检查'}/>
                <Metric label="故事房质量" value={storyRoom ? `${storyRoom.score}/9 ${storyRoom.status}` : '未检查'}/>
                <Metric label="选题商业度" value={topicBrief?.score != null ? `${topicBrief.score}/${topicBrief.score_max || 10} ${topicBrief.score_status || ''}` : '未检查'}/>
                <Metric label="市场证据" value={topicBrief?.market_fit ? `${topicBrief.market_fit.score}/${topicBrief.market_fit.score_max} ${topicBrief.market_fit.status}` : '未录入'}/>
                <Metric label="整集节奏" value={episodeRhythm ? `${episodeRhythm.total_duration_seconds.toFixed(1)}s ${episodeRhythm.status}` : '未检查'}/>
                <Metric label="开场钩子" value={episodeRhythm?.hook_status === 'passed' ? `${episodeRhythm.hook_latency_seconds ?? 0}s` : episodeRhythm?.hook_status === 'needs_review' ? '需提前' : '未检查'}/>
                <Metric label="成片画幅" value={visualFormat ? `${visualFormat.width}x${visualFormat.height}` : '未检查'}/>
                <Metric label="角色身份" value={characters ? `${characters.characters.filter(item => item.has_identity_spec && !item.missing_identity_fields.length).length}/${characters.visible_character_names.length}` : '未检查'}/>
                <Metric label="角色参考" value={characters ? `${characters.visible_character_names.length - characters.missing_references.length}/${characters.visible_character_names.length}` : '未检查'}/>
                <Metric label="角色声线" value={characters ? `${characters.visible_character_names.length - characters.missing_voice_profiles.length}/${characters.visible_character_names.length}` : '未检查'}/>
                <Metric label="复杂镜头" value={complexity ? `${complexity.summary.needs_split} 阻断 / ${complexity.summary.warn} 警告` : '未检查'}/>
                <Metric label="空间计划" value={spatial ? `${spatial.summary.total - spatial.summary.weak}/${spatial.summary.total}` : '未检查'}/>
                <Metric label="审核门槛" value={reviewer ? `${reviewer.image_review_required && reviewer.video_review_required ? '已开启' : '未完全开启'}` : '未检查'}/>
                <Metric label="Workflow" value={workflowProfile ? workflowProfile.status : '未检查'}/>
                <Metric label="样片验证" value={sampleValidation ? sampleValidation.status : '未检查'}/>
                <Metric label="样片质量分" value={qualityScorecard ? formatScore(qualityScorecard.production_score) : '未检查'}/>
                <Metric label="视频引擎" value={report?.checks.video_engine?.status || '未预检'}/>
            </div>
            {characters?.missing_voice_profiles?.length ? (
                <div className="wb-summary-actions">
                    <div className="wb-row wb-between">
                        <div>
                            <h3>角色声线绑定缺口</h3>
                            <p className="wb-muted">为对白角色冻结 voice ID，避免跨分镜或跨机器生成时声线漂移。</p>
                        </div>
                        <span className="wb-badge">{characters.missing_voice_profiles.length} 个角色</span>
                    </div>
                    <div className="wb-issue warning">
                        <span>待绑定</span>
                        <p>{characters.missing_voice_profiles.join(' / ')}</p>
                    </div>
                </div>
            ) : null}
            {storyRoom?.status === 'passed' && storyApproval && (
                <div className="wb-summary-actions" aria-label="故事房审批">
                    <div className="wb-row wb-between">
                        <div>
                            <h3>故事房审批</h3>
                            <p className="wb-muted">
                                {storyApproval.status === 'approved'
                                    ? '当前剧本与分镜已锁定，可进入生产门禁。'
                                    : storyApproval.status === 'stale'
                                        ? '剧本或分镜已变化，需要重新审批。'
                                        : '质量检查通过，但尚未完成制作前审批。'}
                            </p>
                        </div>
                        <span className={`wb-badge ${storyApproval.status === 'approved' ? 'success' : ''}`}>
                            {storyApproval.status === 'approved' ? '已审批' : storyApproval.status === 'stale' ? '审批已失效' : '待审批'}
                        </span>
                    </div>
                    {storyApproval.status !== 'approved' && (
                        <button className="wb-button primary" disabled={loading} onClick={onApproveStoryRoom}>
                            审批当前故事房版本
                        </button>
                    )}
                </div>
            )}
            {storyRoom && storyRoom.missing?.length > 0 && (
                <div className="wb-summary-actions">
                    <div className="wb-row wb-between">
                        <div>
                            <h3>故事房修复建议</h3>
                            <p className="wb-muted">正式成片前先补齐结构证据，避免把 GPU 预算花在弱剧本上。</p>
                        </div>
                        <span className="wb-badge">{storyRoom.missing.length} 项待修复</span>
                    </div>
                    <div className="wb-issue warning">
                        <span>缺项</span>
                        <p>{storyRoom.missing.join(' / ')}</p>
                    </div>
                    {storyRoom.rewrite_actions?.slice(0, 4).map(action => (
                        <div className="wb-issue warning" key={action}>
                            <span>建议</span><p>{action}</p>
                        </div>
                    ))}
                </div>
            )}
            {topicBrief?.recommendations?.length ? (
                <div className="wb-summary-actions">
                    <div className="wb-row wb-between">
                        <div>
                            <h3>选题评分改进建议</h3>
                            <p className="wb-muted">评分衡量商业定位是否足够具体，不代表播放量预测。</p>
                        </div>
                        <span className="wb-badge">{topicBrief.score}/{topicBrief.score_max || 10}</span>
                    </div>
                    {topicBrief.recommendations.slice(0, 4).map(item => <div className="wb-issue warning" key={item}><span>建议</span><p>{item}</p></div>)}
                </div>
            ) : null}
            {topicBrief?.market_fit && topicBrief.market_fit.status !== 'passed' && (
                <div className="wb-summary-actions">
                    <div className="wb-row wb-between">
                        <div>
                            <h3>市场证据仍需补强</h3>
                            <p className="wb-muted">生成前补充可比作品、差异化和可衡量指标，方便后续复盘成片表现。</p>
                        </div>
                        <span className="wb-badge">{topicBrief.market_fit.score}/{topicBrief.market_fit.score_max}</span>
                    </div>
                    {(topicBrief.market_fit.recommendations || []).slice(0, 3).map((item: string) => <div className="wb-issue warning" key={item}><span>建议</span><p>{item}</p></div>)}
                </div>
            )}
            {qualityScorecard && (
                <div className="wb-summary-actions">
                    <div className="wb-row wb-between">
                        <div>
                            <h3>样片质量分数卡</h3>
                            <p className="wb-muted">
                                {qualityScorecard.status || 'unknown'} · production_score {formatScore(qualityScorecard.production_score)}
                            </p>
                        </div>
                        {scorecardFocus?.suggested_action && <span className="wb-badge">{labelScorecardAction(scorecardFocus.suggested_action)}</span>}
                    </div>
                    <div className="wb-grid compact">
                        <Metric label="最弱维度" value={scorecardFocus?.dimension || '无'}/>
                        <Metric label="建议动作" value={scorecardFocus?.suggested_action ? labelScorecardAction(scorecardFocus.suggested_action) : '无'}/>
                        <Metric label="涉及分镜" value={formatScenes(scorecardFocus?.scenes)}/>
                        <Metric label="返修数" value={String(qualityScorecard.repair_queue_total ?? 0)}/>
                    </div>
                    {qualityScorecard.weakest_dimensions?.slice(0, 3).map((item) => (
                        <div className={`wb-issue ${item.status === 'passed' ? 'warning' : 'blocker'}`} key={item.dimension}>
                            <span>{item.dimension}</span>
                            <p>
                                {formatScore(item.score)} / {item.issue_count ?? 0} 项问题
                                {item.scenes?.length ? ` · 分镜 ${item.scenes.join(', ')}` : ''}
                                {item.evidence?.length ? ` · ${item.evidence.slice(0, 2).join('；')}` : ''}
                            </p>
                        </div>
                    ))}
                </div>
            )}
            {workflowProfile && (
                <div className="wb-summary-actions">
                    <h3>Workflow 生产能力</h3>
                    <div className="wb-grid compact">
                        <Metric label="质量档" value={String(qualityGates.quality_profile || '未冻结')}/>
                        <Metric label="图像预算" value={`${qualityGates.image_candidates ?? '-'} 候选 / ${qualityGates.image_refinement_passes ?? '-'} 轮`}/>
                        <Metric label="视频预算" value={`${qualityGates.video_candidates ?? '-'} 候选 / ${qualityGates.video_refinement_passes ?? '-'} 轮`}/>
                        <Metric label="人物身份底线" value={formatScore(typeof qualityGates.character_identity_min_score === 'number' ? qualityGates.character_identity_min_score : undefined)}/>
                        <Metric label="身份分差上限" value={typeof qualityGates.character_identity_max_score_spread === 'number' ? String(qualityGates.character_identity_max_score_spread) : '-'}/>
                        <Metric label="身份证据覆盖" value={`${typeof qualityGates.character_identity_min_observations === 'number' ? qualityGates.character_identity_min_observations : '-'} 次起`}/>
                        <Metric label="曝光漂移阻断" value={typeof qualityGates.episode_style_brightness_blocker === 'number' ? String(qualityGates.episode_style_brightness_blocker) : '-'}/>
                        <Metric label="饱和度漂移阻断" value={typeof qualityGates.episode_style_saturation_blocker === 'number' ? String(qualityGates.episode_style_saturation_blocker) : '-'}/>
                        <Metric label="对比度漂移阻断" value={typeof qualityGates.episode_style_contrast_blocker === 'number' ? String(qualityGates.episode_style_contrast_blocker) : '-'}/>
                        <Metric label="静止片段上限" value={`${typeof qualityGates.video_max_static_run_seconds === 'number' ? qualityGates.video_max_static_run_seconds : '-'}s`}/>
                        <Metric label="时间跳变上限" value={typeof qualityGates.video_max_temporal_jump_ratio === 'number' ? String(qualityGates.video_max_temporal_jump_ratio) : '-'}/>
                        <Metric label="开场钩子上限" value={`${typeof qualityGates.rhythm_max_hook_latency_seconds === 'number' ? qualityGates.rhythm_max_hook_latency_seconds : '-'}s`}/>
                    </div>
                    {profileGaps.length > 0 && <div className="wb-issue blocker">
                        <span>Profile</span>
                        <p>{profileGaps.slice(0, 8).join(' / ')}</p>
                    </div>}
                    {missingCapabilities.length > 0 && <div className="wb-issue blocker">
                        <span>能力</span>
                        <p>{missingCapabilities.join(' / ')}</p>
                    </div>}
                    <div className="wb-grid compact">
                        {Object.entries(capabilityEvidence).slice(0, 8).map(([name, evidence]) => (
                            <div className="wb-kv" key={name}>
                                <span>{name}</span>
                                <strong>{evidence.present ? (evidence.matched_nodes || []).slice(0, 2).join(', ') || '已验证' : '缺失'}</strong>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {spatial?.asset_pack?.control_gaps?.length ? (
                <div className="wb-summary-actions">
                    <div className="wb-row wb-between">
                        <div>
                            <h3>空间控制缺口</h3>
                            <p className="wb-muted">冻结包缺少分镜级控制参考，正式生成前需要重新冻结空间计划。</p>
                        </div>
                        <span className="wb-badge">{spatial.asset_pack.control_gaps.length} 个分镜</span>
                    </div>
                    {spatial.asset_pack.control_gaps.slice(0, 8).map((gap) => (
                        <div className="wb-issue blocker" key={gap.scene_number}>
                            <span>分镜 {gap.scene_number}{gap.character ? ` · ${gap.character}` : ''}</span>
                            <p>{gap.missing.join(' / ')}</p>
                        </div>
                    ))}
                </div>
            ) : null}
            {readinessActions.length > 0 && (
                <div className="wb-summary-actions">
                    <h3>就绪修复动作</h3>
                    {readinessActions.slice(0, 8).map((item) => (
                        <div className={`wb-issue ${item.severity === 'warning' ? 'warning' : 'blocker'}`} key={item.action}>
                            <span>{item.scope === 'global_sample' ? '全局样片 · ' : ''}{item.severity === 'warning' ? '建议' : '阻断'} · {labelScorecardAction(item.action)}</span>
                            <p>{item.recommendation} · {item.reason}{item.instructions ? ` · ${item.instructions}` : ''}</p>
                            {item.scope !== 'global_sample' && isExecutableRepairAction(item.action) && (
                                <button
                                    className="wb-button"
                                    disabled={loading}
                                    onClick={() => onRepairAction?.(item.action)}
                                >
                                    执行
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            )}
            {issues.length > 0 && (
                <div className="wb-summary-actions">
                    {issues.map(issue => (
                        <p key={`${issue.severity}-${issue.code}`} className={`wb-issue ${issue.severity}`}>
                            <span>{issue.severity === 'blocker' ? '阻断' : '警告'}</span>{issue.message}
                        </p>
                    ))}
                </div>
            )}
            {!issues.length && report && <p className="wb-muted">当前没有生产阻断项。正式成片仍需要通过样片审核和基准对比。</p>}
        </section>
    );
}

function Metric({label, value}: {label: string; value: string}) {
    return <div className="wb-kv"><span>{label}</span><strong>{value}</strong></div>;
}

function formatScore(value: QualityScorecard['production_score'] | undefined): string {
    return typeof value === 'number' ? `${value.toFixed(1)}/5` : '未评分';
}

function formatScenes(scenes: number[] | undefined): string {
    return scenes?.length ? scenes.join(', ') : '无';
}

function labelScorecardAction(action: string): string {
    const labels: Record<string, string> = {
        refine_prompt_composition: '优化构图/质感',
        refine_face_aesthetic_detail: '优化五官皮肤细节',
        regenerate_keyframe_with_identity_lock: '锁定身份重生关键帧',
        regenerate_keyframe_with_role_separation: '强化角色区分',
        lower_motion_and_regenerate_video: '降低运动重生视频',
        increase_motion_and_regenerate_video: '提高运动重生视频',
        regenerate_video_with_performance_direction: '强化表演方向',
        refine_video_commercial_aesthetic: '优化视频商业质感',
        refine_final_composition_finish: '统一最终成片精修',
        refine_dialogue_audio_delivery: '优化对白音频',
        rewrite_short_drama_story_rhythm: '重写短剧节奏',
        complete_topic_brief: '补齐选题定位',
        refine_topic_brief: '细化选题定位',
        split_scene: '拆分复杂分镜',
        refreeze_spatial_plan: '重做空间计划',
        fix_workflow_profile: '修复 Workflow Profile',
        run_real_gpu_sample_validation: '运行真实 GPU 样片验证',
    };
    return labels[action] || action;
}

function isExecutableRepairAction(action: string): boolean {
    return action === 'refreeze_spatial_plan'
        || action === 'fix_workflow_profile'
        || action === 'rewrite_short_drama_story_rhythm'
        || action === 'lower_motion_and_regenerate_video'
        || action === 'regenerate_video_with_performance_direction'
        || action === 'refine_video_commercial_aesthetic'
        || action === 'refine_final_composition_finish';
}
