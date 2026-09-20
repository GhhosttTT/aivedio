import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, FileText, Users, Activity, ShieldCheck, Play, RefreshCw, Film } from 'lucide-react';
import { projectApi, errorText, ProductionTask } from '../api/client';
import type { Project } from '../types';
import { ScriptPreview } from '../components/ScriptPreview';
import { ProductionProgress } from '../components/ProductionProgress';
import { ReviewPanel } from '../components/ReviewPanel';
import { VideoEngineStatus } from '../components/VideoEngineStatus';
import { ProductionReadinessPanel } from '../components/ProductionReadinessPanel';
import CharacterManager from './CharacterManager';
import type { ProductionReadinessReport } from '../api/client';

export function ProjectDetail() {
    const {id} = useParams();
    const [project, setProject] = useState<Project | null>(null);
    const [task, setTask] = useState<ProductionTask | null>(null);
    const [tab, setTab] = useState('script');
    const [busy, setBusy] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(true);
    const [readiness, setReadiness] = useState<ProductionReadinessReport | null>(null);
    const [readinessLoading, setReadinessLoading] = useState(false);
    const [options, setOptions] = useState({num_scenes: 16, num_characters: 2, style: '现代都市'});
    const reload = useCallback(async () => {
        try {
            const projectId = Number(id);
            const [data, latest, ready] = await Promise.all([
                projectApi.getProject(projectId),
                projectApi.latestTask(projectId),
                projectApi.productionReadiness(projectId, false),
            ]);
            setProject(data); setTask(latest); setReadiness(ready); setError('');
        } catch(e) { setError(errorText(e)); }
        finally { setLoading(false); }
    }, [id]);
    useEffect(() => { reload(); }, [reload]);
    useEffect(() => {
        if (project?.status !== 'in_production') return;
        const timer = window.setInterval(reload, 3000);
        return () => window.clearInterval(timer);
    }, [project?.status, reload]);
    const run = async (operation: string) => {
        if (!project || busy) return;
        setBusy(operation); setError('');
        try {
            if (operation === '剧本生成与情节复审') {
                // 确保空字符串转为undefined
                const theme = project.theme?.trim() || undefined;
                const outline = project.outline?.trim() || undefined;
                await projectApi.generateScript(Number(id), {...options, theme, outline});
            } else {
                await projectApi.startProduction(Number(id));
                setTab('production');
            }
            await reload();
        } catch(e) { setError(errorText(e)); }
        finally { setBusy(''); }
    };
    const refreshReadiness = useCallback(async () => {
        if (!id) return;
        setReadinessLoading(true);
        try {
            setReadiness(await projectApi.productionReadiness(Number(id), true));
        } catch(e) { setError(errorText(e)); }
        finally { setReadinessLoading(false); }
    }, [id]);
    if (loading) return <main className="workbench" role="status">项目加载中</main>;
    if (!project) return <main className="workbench"><Link to="/projects">返回项目</Link><p role="alert" className="wb-alert">{error || '项目不存在'}</p><button className="wb-button" onClick={reload}>重试</button></main>;
    const productionBlocked = Boolean(readiness?.blockers?.length);
    const locked = Boolean(busy) || project.status === 'in_production';
    return <main className="workbench">
        <Link to="/projects" className="wb-row wb-muted"><ArrowLeft size={16}/>项目列表</Link>
        <header className="wb-row wb-between" style={{marginTop: 18}}>
            <div><h1>{project.name}</h1><p className="wb-muted">{project.theme || project.description || '短剧项目'} · {project.scenes?.length || 0} 个分镜</p></div>
            <div className="wb-row">
                <button className="wb-icon" title="刷新项目" aria-label="刷新项目" onClick={reload}><RefreshCw size={17}/></button>
                {project.final_video_path && <Link className="wb-button" to={`/projects/${id}/video`}><Film size={17}/>查看成片</Link>}
                <button className="wb-button primary" disabled={locked || !project.scenes?.length || productionBlocked} title={productionBlocked ? '先处理生产就绪阻断项' : '开始制作'} onClick={() => run('提交制作')}><Play size={17}/>开始制作</button>
            </div>
        </header>
        {error && <p role="alert" className="wb-alert">{error}</p>}
        {busy && <p role="status" className="wb-alert"><RefreshCw size={15} className="inline animate-spin"/> {busy}进行中</p>}
        <VideoEngineStatus/>
        <ProductionReadinessPanel report={readiness} loading={readinessLoading} onRefresh={refreshReadiness}/>
        <nav className="wb-tabs" role="tablist" aria-label="项目工作区">
            {[['script', '剧本分镜', FileText], ['characters', '角色参考', Users], ['production', '制作进度', Activity], ['review', '质量审核', ShieldCheck]].map(([key, label, Icon]) => <button key={String(key)} role="tab" aria-selected={tab === key} onClick={() => setTab(String(key))}><Icon size={17}/>{String(label)}</button>)}
        </nav>
        {tab === 'script' && <>
            <div className="wb-fields">
                <label>分镜数量<input type="number" min={5} max={20} disabled={locked} value={options.num_scenes} onChange={e => setOptions({...options, num_scenes: Number(e.target.value)})}/></label>
                <label>角色数量<input type="number" min={1} max={4} disabled={locked} value={options.num_characters} onChange={e => setOptions({...options, num_characters: Number(e.target.value)})}/></label>
                <label>画面风格<select value={options.style} disabled={locked} onChange={e => setOptions({...options, style: e.target.value})}><option>现代都市</option><option>二维动画</option><option>三维动画</option><option>古装写实</option></select></label>
            </div>
            {/* LLM功能已配置，显示生成剧本按钮 */}
            <button className="wb-button" disabled={locked || options.num_scenes < 5 || options.num_scenes > 20 || options.num_characters < 1 || options.num_characters > 4} onClick={() => {
                if (!project.scenes?.length || window.confirm('重新生成会替换现有分镜，继续吗？')) run('剧本生成与情节复审');
            }}><FileText size={16}/>{project.scenes?.length ? '重新生成剧本' : '生成剧本'}</button>
            <ScriptPreview project={project} onReload={reload} locked={locked}/>
        </>}
        {tab === 'characters' && <CharacterManager projectId={Number(id)} locked={locked}/>}
        {tab === 'production' && <ProductionProgress project={project} task={task} onReload={reload}/>}
        {tab === 'review' && <ReviewPanel projectId={Number(id)} updatedAt={project.updated_at}/>}
    </main>;
}
