import { useEffect, useState } from 'react';
import { Download, Play, RefreshCw, Upload } from 'lucide-react';
import { errorText, localizationApi, projectApi } from '../api/client';
import type { LocalizationJob, Project, SourceVideo } from '../types';
import { useMediaUrl } from '../components/ProjectMedia';
const languages = [['en','英语'],['es','西班牙语'],['pt','葡萄牙语'],['ar','阿拉伯语'],['id','印尼语'],['th','泰语'],['vi','越南语'],['ja','日语'],['ko','韩语']];
const stages: Record<string,string> = {uploaded:'源片已上传', preprocessing:'音画预处理', cleaning:'画面擦除', asr:'对白识别', translation:'本地化翻译', rendering:'字幕压制', moderation:'智能审核', completed:'处理结束'};
function Output({projectId, job, language}: {projectId: number; job: LocalizationJob; language: string}) {
    const video = useMediaUrl(projectId, job.rendered_video_dir ? `${job.rendered_video_dir}/${language}.mp4` : null);
    const subtitle = useMediaUrl(projectId, job.translated_subtitle_dir ? `${job.translated_subtitle_dir}/${language}.srt` : null);
    return <article className="wb-item"><h3>{languages.find(([code]) => code === language)?.[1] || language}</h3>
        {video.url && <video className="wb-video" style={{maxHeight: 300}} src={video.url} controls playsInline preload="none" aria-label={`${language} 成片`}/>}
        <div className="wb-row">{video.url && <a className="wb-button" href={video.url + '&download=true'}><Download size={16}/>视频</a>}{subtitle.url && <a className="wb-button" href={subtitle.url + '&download=true'}><Download size={16}/>字幕</a>}</div>
        {(video.error || subtitle.error) && <p className="wb-alert">{video.error || subtitle.error}</p>}
    </article>;
}
export function LocalizationDashboard() {
    const [projects, setProjects] = useState<Project[]>([]);
    const [projectId, setProjectId] = useState(0);
    const [sources, setSources] = useState<SourceVideo[]>([]);
    const [sourceId, setSourceId] = useState(0);
    const [jobs, setJobs] = useState<LocalizationJob[]>([]);
    const [job, setJob] = useState<LocalizationJob | null>(null);
    const [selected, setSelected] = useState(['en']);
    const [file, setFile] = useState<File | null>(null);
    const [busy, setBusy] = useState('');
    const [error, setError] = useState('');
    const report = useMediaUrl(projectId, job?.moderation_report_path);
    useEffect(() => {projectApi.listProjects({page_size: 100}).then(data => {setProjects(data.projects); setProjectId(Number(data.projects[0]?.id) || 0);}).catch(e => setError(errorText(e)));}, []);
    useEffect(() => {
        let active = true;
        setSources([]); setSourceId(0); setJobs([]); setJob(null); setError(''); setFile(null);
        if (projectId) Promise.all([localizationApi.listSourceVideos(projectId), localizationApi.listProjectJobs(projectId)]).then(([videos, data]) => {
            if (!active) return;
            setSources(videos); setSourceId(videos[0]?.id || 0); setJobs(data); setJob(data[0] || null);
        }).catch(e => {if (active) setError(errorText(e));});
        return () => {active = false;};
    }, [projectId]);
    useEffect(() => {
        if (!job || !['queued','running'].includes(job.status)) return;
        let active = true;
        const timer = window.setInterval(() => localizationApi.getJob(job.id).then(data => {if(active) setJob(data);}).catch(e => {if(active) setError(errorText(e));}), 3000);
        return () => {active = false; window.clearInterval(timer);};
    }, [job?.id, job?.status]);
    const run = async (upload: boolean) => {
        setBusy(upload ? '上传中' : '提交中'); setError('');
        try {
            if (upload && file) {
                const data = await localizationApi.uploadSourceVideo(projectId, file);
                setSources(prev => [data, ...prev]); setSourceId(data.id); setFile(null);
            } else {
                const data = await localizationApi.createJob({source_video_id: sourceId, target_languages: selected, auto_start: true});
                setJob(data); setJobs(prev => [data, ...prev]);
            }
        } catch(e) {setError(errorText(e));} finally {setBusy('');}
    };
    const running = job && ['queued','running'].includes(job.status);
    return <main className="workbench"><h1>源片出海译制</h1>
        {error && <p role="alert" className="wb-alert">{error}</p>}
        <div className="wb-fields">
            <label>项目<select value={projectId} disabled={Boolean(busy)} onChange={e => setProjectId(Number(e.target.value))}><option value={0}>选择项目</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            <label>中文源片<input type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm" disabled={Boolean(busy) || !projectId} onChange={e => setFile(e.target.files?.[0] || null)}/></label>
            <div className="wb-row"><button className="wb-button" disabled={Boolean(busy) || !projectId || !file} onClick={() => run(true)}><Upload size={16}/>上传源片</button></div>
        </div>
        <label>已上传源片<select value={sourceId} disabled={Boolean(busy)} onChange={e => setSourceId(Number(e.target.value))}><option value={0}>选择源片</option>{sources.map(source => <option value={source.id} key={source.id}>{source.original_filename}</option>)}</select></label>
        <fieldset style={{margin: '24px 0'}}><legend>目标语种</legend><div className="wb-row" style={{marginTop: 12}}>{languages.map(([code, name]) => <label key={code} style={{flexDirection: 'row', alignItems: 'center'}}><input type="checkbox" checked={selected.includes(code)} disabled={Boolean(busy)} onChange={e => setSelected(prev => e.target.checked ? [...prev, code] : prev.filter(x => x !== code))}/>{name}</label>)}</div></fieldset>
        <button className="wb-button primary" disabled={Boolean(busy) || !sourceId || !selected.length || Boolean(running)} onClick={() => run(false)}><Play size={16}/>{busy || '开始译制'}</button>
        {busy && <p role="status" className="wb-muted">{busy}</p>}
        <section style={{marginTop: 32}}><div className="wb-row wb-between"><h2>译制任务</h2>{job && <button className="wb-icon" aria-label="刷新译制任务" title="刷新译制任务" onClick={() => localizationApi.getJob(job.id).then(setJob).catch(e => setError(errorText(e)))}><RefreshCw size={16}/></button>}</div>
            <label>任务记录<select value={job?.id || 0} onChange={e => setJob(jobs.find(x => x.id === Number(e.target.value)) || null)}><option value={0}>选择任务</option>{jobs.map(x => <option key={x.id} value={x.id}>#{x.id} · {x.target_languages.join(', ')} · {x.status}</option>)}</select></label>
            {job && <><p className="wb-item">{stages[job.current_stage] || job.current_stage} · {job.status} · {job.progress.toFixed(0)}%</p><progress aria-label="译制进度" value={job.progress} max={100}/>
                <div className="wb-row" style={{marginTop: 12}}>{Object.entries(stages).map(([key,label]) => <span className={`wb-score ${key === job.current_stage ? 'passed' : ''}`} key={key}>{label}</span>)}</div>
                {job.error_message && <p role="alert" className="wb-alert">{job.error_message}</p>}
                {report.url && <a className="wb-button" style={{marginTop: 16}} href={report.url} target="_blank" rel="noreferrer">查看审核报告</a>}
                {['completed','needs_review'].includes(job.status) && job.target_languages.map(language => <Output key={`${job.id}-${language}`} projectId={projectId} job={job} language={language}/>)}
            </>}
            {!job && <p className="wb-muted">暂无译制任务</p>}
        </section>
    </main>;
}
