import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert } from 'lucide-react';
import type { ProductionReadinessReport } from '../api/client';

export function ProductionReadinessPanel({
    report,
    loading,
    onRefresh,
}: {
    report: ProductionReadinessReport | null;
    loading: boolean;
    onRefresh: () => void;
}) {
    const status = report?.status || 'loading';
    const blocked = status === 'blocked';
    const warning = status === 'needs_review';
    const Icon = blocked ? ShieldAlert : warning ? AlertTriangle : CheckCircle2;
    const label = blocked ? '生产被阻断' : warning ? '可草稿生成，正式成片需复查' : report ? '生产就绪' : '检查中';
    const issues = [...(report?.blockers || []), ...(report?.warnings || [])].slice(0, 5);
    const script = report?.checks.script;
    const storyRhythm = report?.checks.story_rhythm;
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
                <Metric label="成片画幅" value={visualFormat ? `${visualFormat.width}x${visualFormat.height}` : '未检查'}/>
                <Metric label="角色身份" value={characters ? `${characters.characters.filter(item => item.has_identity_spec && !item.missing_identity_fields.length).length}/${characters.visible_character_names.length}` : '未检查'}/>
                <Metric label="角色参考" value={characters ? `${characters.visible_character_names.length - characters.missing_references.length}/${characters.visible_character_names.length}` : '未检查'}/>
                <Metric label="复杂镜头" value={complexity ? `${complexity.summary.needs_split} 阻断 / ${complexity.summary.warn} 警告` : '未检查'}/>
                <Metric label="空间计划" value={spatial ? `${spatial.summary.total - spatial.summary.weak}/${spatial.summary.total}` : '未检查'}/>
                <Metric label="审核门槛" value={reviewer ? `${reviewer.image_review_required && reviewer.video_review_required ? '已开启' : '未完全开启'}` : '未检查'}/>
                <Metric label="Workflow" value={workflowProfile ? workflowProfile.status : '未检查'}/>
                <Metric label="样片验证" value={sampleValidation ? sampleValidation.status : '未检查'}/>
                <Metric label="视频引擎" value={report?.checks.video_engine?.status || '未预检'}/>
            </div>
            {workflowProfile && (
                <div className="wb-summary-actions">
                    <h3>Workflow 生产能力</h3>
                    <div className="wb-grid compact">
                        <Metric label="质量档" value={String(qualityGates.quality_profile || '未冻结')}/>
                        <Metric label="图像预算" value={`${qualityGates.image_candidates ?? '-'} 候选 / ${qualityGates.image_refinement_passes ?? '-'} 轮`}/>
                        <Metric label="视频预算" value={`${qualityGates.video_candidates ?? '-'} 候选 / ${qualityGates.video_refinement_passes ?? '-'} 轮`}/>
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
