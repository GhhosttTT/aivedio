import { useCallback, useEffect, useState } from 'react';
import { Plus, Trash2, Upload, X } from 'lucide-react';
import { characterApi, Character, CharacterReference } from '../api/characterApi';
import { errorText } from '../api/client';
import { ProjectImage } from '../components/ProjectMedia';

export default function CharacterManager({projectId, locked = false}: {projectId: number; locked?: boolean}) {
    const [characters, setCharacters] = useState<Character[]>([]);
    const [references, setReferences] = useState<Record<number, CharacterReference[]>>({});
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [creating, setCreating] = useState(false);
    const [form, setForm] = useState({name: '', description: '', appearance: ''});
    const load = useCallback(async () => {
        try {
            const data = await characterApi.listCharacters(projectId);
            setCharacters(data);
            const entries = await Promise.all(data.map(async c => [c.id, await characterApi.listReferences(projectId, c.id)] as const));
            setReferences(Object.fromEntries(entries));
        } catch(e) { setError(errorText(e)); }
    }, [projectId]);
    useEffect(() => { load(); }, [load]);
    const operate = async (fn: () => Promise<unknown>) => {
        setBusy(true); setError('');
        try { await fn(); setCreating(false); await load(); }
        catch(e) { setError(errorText(e)); }
        finally { setBusy(false); }
    };
    return <section aria-label="角色参考">
        <div className="wb-row wb-between"><h2>角色与参考图</h2><button className="wb-button" disabled={locked || busy} onClick={() => setCreating(true)}><Plus size={16}/>创建角色</button></div>
        {error && <p role="alert" className="wb-alert">{error}</p>}
        {!characters.length && <p className="wb-muted">暂无角色</p>}
        {characters.map(c => <article className="wb-item" key={c.id}>
            <div className="wb-row wb-between"><h3>{c.name}</h3><button className="wb-icon" aria-label={`删除角色 ${c.name}`} title="删除角色" disabled={locked || busy} onClick={() => { if (window.confirm(`删除角色“${c.name}”？`)) operate(() => characterApi.deleteCharacter(projectId, c.id)); }}><Trash2 size={16}/></button></div>
            <p>{c.description}</p><p className="wb-muted">{c.appearance}</p>
            <div className="wb-thumbnails">{references[c.id]?.map(ref => <ProjectImage key={ref.image_path} projectId={projectId} path={ref.image_path} alt={`${c.name} 参考图 ${ref.id}`}/>)}</div>
            <label style={{maxWidth: 330}}><span className="wb-row"><Upload size={16}/>上传 {c.name} 参考图</span><input type="file" accept="image/png,image/jpeg,image/webp" disabled={locked || busy} onChange={e => {
                const file = e.target.files?.[0]; e.target.value = '';
                if (!file) return;
                if (file.size > 10 * 1024 * 1024) { setError('参考图不能超过 10 MB'); return; }
                operate(() => characterApi.uploadReference(projectId, c.id, file));
            }}/></label>
        </article>)}
        {creating && <div className="wb-overlay"><form role="dialog" aria-modal="true" aria-label="创建角色" className="wb-modal" onSubmit={e => {e.preventDefault(); operate(() => characterApi.createCharacter(projectId, form));}}>
            <div className="wb-row wb-between"><h2>创建角色</h2><button type="button" className="wb-icon" title="关闭" aria-label="关闭" onClick={() => setCreating(false)}><X size={17}/></button></div>
            <label>角色名称<input required maxLength={100} value={form.name} onChange={e => setForm({...form, name: e.target.value})}/></label>
            <label>角色描述<textarea value={form.description} maxLength={500} onChange={e => setForm({...form, description: e.target.value})}/></label>
            <label>外貌设定<textarea value={form.appearance} maxLength={500} onChange={e => setForm({...form, appearance: e.target.value})}/></label>
            <button className="wb-button primary" disabled={busy || !form.name.trim()} type="submit">创建</button>
        </form></div>}
    </section>;
}
