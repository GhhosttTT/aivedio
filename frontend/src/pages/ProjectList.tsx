import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Edit2, Trash2, ArrowLeft, ArrowRight, X, RefreshCw } from 'lucide-react';
import { errorText, projectApi } from '../api/client';
import type { Project } from '../types';
const statuses: Record<string,string> = {draft: '草稿', script_generated: '剧本已生成', in_production: '制作中', completed: '已完成', failed: '失败'};
export function ProjectList() {
    const [projects, setProjects] = useState<Project[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [editing, setEditing] = useState<number | null>(null);
    const [modal, setModal] = useState(false);
    const [form, setForm] = useState({name: '', description: '', theme: '', outline: ''});
    const load = async () => {
        setLoading(true);
        try { const data = await projectApi.listProjects({page, page_size: 12}); setProjects(data.projects); setTotal(data.total); setError(''); }
        catch(e) { setError(errorText(e)); }
        finally { setLoading(false); }
    };
    useEffect(() => {load();}, [page]);
    const remove = async (p: Project) => {
        if (!window.confirm(`删除项目“${p.name}”及其素材？此操作无法撤销。`)) return;
        setBusy(true);
        try {await projectApi.deleteProject(Number(p.id)); if (projects.length === 1 && page > 1) setPage(page - 1); else await load();}
        catch(e) {setError(errorText(e));} finally {setBusy(false);}
    };
    return <main className="workbench">
        <header className="wb-row wb-between"><div><h1>短剧项目</h1><p className="wb-muted">{total} 个项目</p></div><div className="wb-row"><button className="wb-icon" title="刷新列表" aria-label="刷新列表" onClick={load}><RefreshCw size={17}/></button><button className="wb-button primary" onClick={() => {setEditing(null); setForm({name: '', description: '', theme: '', outline: ''}); setModal(true);}}><Plus size={17}/>创建项目</button></div></header>
        {error && <p role="alert" className="wb-alert">{error}</p>}
        {loading && <p role="status" className="wb-muted">项目加载中</p>}
        {!loading && !projects.length && !error && <p className="wb-muted" style={{marginTop: 40}}>暂无项目</p>}
        {projects.map(p => <article key={p.id} className="wb-item wb-row wb-between">
            <div><Link to={`/projects/${p.id}`}><h2 style={{marginBottom: 4}}>{p.name}</h2></Link><p className="wb-muted">{p.theme || p.description || '未填写主题'} · {p.scenes?.length || 0} 分镜</p></div>
            <div className="wb-row"><span className={`wb-score ${p.status}`}>{statuses[p.status] || p.status}</span>
                <button className="wb-icon" aria-label={`编辑项目 ${p.name}`} title="编辑项目" disabled={busy || p.status === 'in_production'} onClick={() => {setEditing(Number(p.id)); setForm({name: p.name, description: p.description || '', theme: p.theme || '', outline: p.outline || ''}); setModal(true);}}><Edit2 size={16}/></button>
                <button className="wb-icon" aria-label={`删除项目 ${p.name}`} title="删除项目" disabled={busy || p.status === 'in_production'} onClick={() => remove(p)}><Trash2 size={16}/></button>
            </div>
        </article>)}
        {total > 12 && <div className="wb-row" style={{marginTop: 24}}><button className="wb-icon" aria-label="上一页" title="上一页" disabled={page === 1 || loading} onClick={() => setPage(page - 1)}><ArrowLeft size={17}/></button><span>{page} / {Math.ceil(total / 12)}</span><button className="wb-icon" aria-label="下一页" title="下一页" disabled={page * 12 >= total || loading} onClick={() => setPage(page + 1)}><ArrowRight size={17}/></button></div>}
        {modal && <div className="wb-overlay"><form className="wb-modal" role="dialog" aria-modal="true" aria-label={editing ? '编辑项目' : '创建项目'} onSubmit={async e => {
            e.preventDefault(); setBusy(true); setError('');
            try {if (editing) await projectApi.updateProject(editing, form); else await projectApi.createProject(form); setModal(false); await load();}
            catch(e) {setError(errorText(e));} finally {setBusy(false);}
        }}>
            <div className="wb-row wb-between"><h2>{editing ? '编辑项目' : '创建项目'}</h2><button className="wb-icon" type="button" aria-label="关闭" title="关闭" disabled={busy} onClick={() => setModal(false)}><X size={17}/></button></div>
            <label>项目名称<input required maxLength={100} value={form.name} onChange={e => setForm({...form, name: e.target.value})}/></label>
            <label>主题<input maxLength={200} value={form.theme} onChange={e => setForm({...form, theme: e.target.value})}/></label>
            <label>故事大纲<textarea maxLength={1000} value={form.outline} onChange={e => setForm({...form, outline: e.target.value})}/></label>
            <label>备注<textarea maxLength={500} value={form.description} onChange={e => setForm({...form, description: e.target.value})}/></label>
            {error && <p className="wb-alert" role="alert">{error}</p>}
            <button className="wb-button primary" type="submit" disabled={busy || !form.name.trim()}>{busy ? '保存中' : '保存项目'}</button>
        </form></div>}
    </main>;
}
