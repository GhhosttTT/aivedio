import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { errorText, projectApi } from '../api/client';
import { ProjectImage } from './ProjectMedia';

const names: Record<string,string> = {story: '生成情节复审', production_story: '制作前情节复审', generation: '成片质量门禁', causal_logic: '因果逻辑', character_motivation: '角色动机', continuity: '连续性', filmability: '可生成性', story_match: '剧情匹配', composition: '构图', visual_integrity: '画面完整性', identity_consistency: '角色一致性'};
const statuses: Record<string,string> = {passed: '通过', needs_review: '需要复核', error: '审核出错', stale: '内容已变更，待重审'};
function Scores({review}: {review: any}) {
    if (!review) return null;
    return <><div className="wb-fields">{Object.entries(review).filter(([,value]: any) => typeof value?.score === 'number').map(([key, value]: any) => <div key={key}><h3>{names[key] || key} · {value.score}/5</h3><p className="wb-muted">{value.evidence}</p></div>)}</div>
        {review.issues?.map((issue: any, index: number) => <p key={index} className="wb-alert">{issue.severity} · 分镜 {issue.scene_number || '-'} · {issue.description || issue.message || issue.evidence || JSON.stringify(issue)}</p>)}
    </>;
}
export function ReviewPanel({projectId, updatedAt}: {projectId: number; updatedAt: string}) {
    const [reports, setReports] = useState<Record<string, any>>({});
    const [error, setError] = useState('');
    const load = () => projectApi.reviews(projectId).then(data => {setReports(data.reports); setError('');}).catch(e => setError(errorText(e)));
    useEffect(() => { load(); }, [projectId, updatedAt]);
    return <section aria-label="质量审核">
        <div className="wb-row wb-between"><h2>审核结果</h2><button className="wb-icon" aria-label="刷新审核" title="刷新审核" onClick={load}><RefreshCw size={17}/></button></div>
        {error && <p className="wb-alert" role="alert">{error}</p>}
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
