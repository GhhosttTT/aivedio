import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { errorText, projectApi } from '../api/client';
import type { GenerationReviewSummary } from '../api/client';
import { ProjectImage } from './ProjectMedia';

const names: Record<string, string> = {
    story: '生成情节复审',
    production_story: '制作前情节复审',
    generation: '成片质量审核',
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
    lower_motion_and_regenerate_video: '降低运动强度后重做视频',
    split_scene: '拆分为更简单的原子镜头',
    start_local_reviewer: '启动 llama.cpp 视觉审核后重跑',
    manual_review: '人工复核',
};

function labelAction(item: string) {
    return actionLabels[item] || item;
}

function labelRepairAction(action?: string) {
    return repairActionLabels[action || ''] || action || '未知动作';
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
    return <div>
        <div className="wb-fields">
            <div><h3>时长差</h3><p className="wb-muted">{differences.duration_delta_seconds ?? '-'} 秒</p></div>
            <div><h3>运动量比例</h3><p className="wb-muted">{differences.motion_energy_ratio ?? '-'}</p></div>
            <div><h3>清晰度比例</h3><p className="wb-muted">{differences.sharpness_ratio ?? '-'}</p></div>
            <div><h3>候选规格</h3><p className="wb-muted">{candidate.width || '-'}x{candidate.height || '-'} · {candidate.fps || '-'} fps</p></div>
            <div><h3>基线规格</h3><p className="wb-muted">{baseline.width || '-'}x{baseline.height || '-'} · {baseline.fps || '-'} fps</p></div>
        </div>
        {gates.length > 0 && <div className="wb-grid compact">
            {gates.map(([key, passed]) => <div className="wb-kv" key={key}>
                <span>{key}</span>
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

function ReviewSummary({summary}: {summary?: GenerationReviewSummary}) {
    if (!summary) return null;
    const reportEntries = Object.entries(summary.reports || {}).filter(([key]) => !key.startsWith('story_attempt'));
    const isReady = summary.status === 'ready';
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
        {summary.repair_queue?.total ? <div className="wb-summary-actions">
            <h3>返工队列 · {summary.repair_queue.total}</h3>
            <div className="wb-grid compact">
                {Object.entries(summary.repair_queue.actions || {}).map(([action, count]) => <div className="wb-kv" key={action}>
                    <span>{labelRepairAction(action)}</span>
                    <strong>{count}</strong>
                </div>)}
            </div>
            {summary.repair_queue.items?.slice(0, 6).map((item, index) => <p key={`${item.source_report}-${item.action}-${index}`} className={`wb-issue ${item.priority === 'high' ? 'blocker' : 'warning'}`}>
                <span>{item.priority === 'high' ? '高' : '中'}</span>
                {item.scene_number ? `分镜 ${item.scene_number} · ` : ''}{labelRepairAction(item.action)}：{item.recommendation || item.reason}
            </p>)}
        </div> : null}
        {reportEntries.length > 0 && <div className="wb-grid compact" aria-label="报告状态">
            {reportEntries.map(([key, statusValue]) => <div className="wb-kv" key={key}>
                <span>{reportTitle(key)}</span>
                <strong>{statusValue ? statuses[statusValue] || statusValue : '未运行'}</strong>
            </div>)}
        </div>}
    </section>;
}

export function ReviewPanel({projectId, updatedAt}: {projectId: number; updatedAt: string}) {
    const [reports, setReports] = useState<Record<string, any>>({});
    const [summary, setSummary] = useState<GenerationReviewSummary | undefined>();
    const [error, setError] = useState('');
    const [baselinePath, setBaselinePath] = useState('');
    const [baselineFile, setBaselineFile] = useState<File | null>(null);
    const [busy, setBusy] = useState(false);

    const load = () => projectApi.reviews(projectId)
        .then(data => {setReports(data.reports); setSummary(data.summary); setError('');})
        .catch(e => setError(errorText(e)));

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
                await projectApi.uploadSeedDanceBaseline(projectId, baselineFile);
            } else {
                await projectApi.compareSeedDanceBaseline(projectId, {baseline_path: baseline});
            }
            await load();
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    useEffect(() => { load(); }, [projectId, updatedAt]);

    return <section aria-label="质量审核">
        <div className="wb-row wb-between">
            <h2>审核结果</h2>
            <button className="wb-icon" aria-label="刷新审核" title="刷新审核" onClick={load}><RefreshCw size={17}/></button>
        </div>
        {error && <p className="wb-alert" role="alert">{error}</p>}
        <ReviewSummary summary={summary}/>
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
            <SeedDanceComparison projectId={projectId} report={report}/>
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
