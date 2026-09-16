import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { errorText, projectApi } from '../api/client';
import type { GenerationReviewSummary } from '../api/client';
import { ProjectImage } from './ProjectMedia';

const names: Record<string,string> = {story: '生成情节复审', production_story: '制作前情节复审', generation: '成片质量门禁', causal_logic: '因果逻辑', character_motivation: '角色动机', continuity: '连续性', filmability: '可生成性', story_match: '剧情匹配', composition: '构图', visual_integrity: '画面完整性', identity_consistency: '角色一致性'};
const statuses: Record<string,string> = {passed: '通过', needs_review: '需要复核', error: '审核出错', stale: '内容已变更，待重审', blocked: '被阻断', ready: '可继续'};
const actionLabels: Record<string,string> = {
    'Story or media changed; rerun the stale reviews before composing.': '剧情或媒体已变更，需要重跑过期审核后再合成。',
    'Split or simplify scenes marked needs_split in shot_complexity.json before GPU generation.': '先拆分或简化 shot_complexity.json 中标记 needs_split 的分镜，再进 GPU 生成。',
    'Review warning scenes in shot_complexity.json; keep one action and static camera.': '复核 shot_complexity.json 中的警告分镜，保持单一动作和静态镜头。',
    'Run production story review before generating final assets.': '生成最终资产前先运行制作前情节复审。',
    'Run sampled-frame generation review before final composition.': '最终合成前先运行抽帧成片质量审核。',
};
function labelAction(item: string) { return actionLabels[item] || item; }
function Scores({review}: {review: any}) {
    if (!review) return null;
    return <><div className="wb-fields">{Object.entries(review).filter(([,value]: any) => typeof value?.score === 'number').map(([key, value]: any) => <div key={key}><h3>{names[key] || key} · {value.score}/5</h3><p className="wb-muted">{value.evidence}</p></div>)}</div>
        {review.issues?.map((issue: any, index: number) => <p key={index} className="wb-alert">{issue.severity} · 分镜 {issue.scene_number || '-'} · {issue.description || issue.message || issue.evidence || JSON.stringify(issue)}</p>)}
    </>;
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
        {reportEntries.length > 0 && <div className="wb-grid compact" aria-label="报告状态">
            {reportEntries.map(([key, statusValue]) => <div className="wb-kv" key={key}>
                <span>{names[key] || key}</span>
                <strong>{statusValue ? statuses[statusValue] || statusValue : '未运行'}</strong>
            </div>)}
        </div>}
    </section>;
}
export function ReviewPanel({projectId, updatedAt}: {projectId: number; updatedAt: string}) {
    const [reports, setReports] = useState<Record<string, any>>({});
    const [summary, setSummary] = useState<GenerationReviewSummary | undefined>();
    const [error, setError] = useState('');
    const load = () => projectApi.reviews(projectId).then(data => {setReports(data.reports); setSummary(data.summary); setError('');}).catch(e => setError(errorText(e)));
    useEffect(() => { load(); }, [projectId, updatedAt]);
    return <section aria-label="质量审核">
        <div className="wb-row wb-between"><h2>审核结果</h2><button className="wb-icon" aria-label="刷新审核" title="刷新审核" onClick={load}><RefreshCw size={17}/></button></div>
        {error && <p className="wb-alert" role="alert">{error}</p>}
        <ReviewSummary summary={summary}/>
        {!Object.keys(reports).length && !error && <p className="wb-muted">暂无审核记录</p>}
        {Object.entries(reports).filter(([key]) => !key.startsWith('story_attempt')).map(([key, report]) => <article className="wb-item" key={key}>
            <div className="wb-row"><h3>{names[key] || (key.startsWith('scene_') ? `分镜 ${key.replace('scene_', '')} 抽帧审核` : key)}</h3><span className={`wb-score ${report.status}`}>{statuses[report.status] || report.status}</span>{report.average != null && <strong>{report.average} / 5</strong>}</div>
            {report.error && <p className="wb-alert">{String(report.error)}</p>}
            <Scores review={report.review}/>
            {report.batches?.map((batch: any, index: number) => <div key={index}><p>帧组 {index + 1} · {statuses[batch.status] || batch.status} · {batch.average}/5</p><Scores review={batch.review}/></div>)}
            {report.frames && <div className="wb-thumbnails">{report.frames.map((frame: any) => <figure key={frame.index}><ProjectImage projectId={projectId} path={frame.path} alt={`抽帧 ${frame.index}`}/><figcaption className="wb-muted">{Number(frame.timestamp).toFixed(2)} 秒</figcaption></figure>)}</div>}
        </article>)}
    </section>;
}
