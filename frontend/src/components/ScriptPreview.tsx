import { useEffect, useState } from 'react';
import { Edit2, RefreshCw, Save, X } from 'lucide-react';
import { errorText, projectApi } from '../api/client';
import type { Project, Scene } from '../types';
import { ProjectImage, ProjectVideo } from './ProjectMedia';

export function ScriptPreview({project, onReload, locked = false}: {project: Project; onReload: () => void; locked?: boolean}) {
    const [editing, setEditing] = useState<Scene | null>(null);
    const [busy, setBusy] = useState<number | null>(null);
    const [error, setError] = useState('');
    const [reports, setReports] = useState<Record<string, any>>({});
    const [reviewLoading, setReviewLoading] = useState(false);
    useEffect(() => {
        let active = true;
        setReviewLoading(true);
        projectApi.reviews(Number(project.id))
            .then(value => { if (active) setReports(value.reports || {}); })
            .catch(() => { if (active) setReports({}); })
            .finally(() => { if (active) setReviewLoading(false); });
        return () => { active = false; };
    }, [project.id, project.updated_at]);

    const sceneReview = (sceneNumber: number) => {
        const matches = Object.entries(reports).filter(([key, report]) => (
            new RegExp(`(^|_)scene_${sceneNumber}(_|$)`).test(key) || report?.scene_number === sceneNumber
        ));
        const failed = matches.find(([, report]) => ['needs_review', 'error', 'stale'].includes(report?.status));
        const passed = matches.find(([, report]) => report?.status === 'passed');
        return failed?.[1] || passed?.[1] || null;
    };
    const reviewStatus = (sceneNumber: number) => sceneReview(sceneNumber)?.status || (reviewLoading ? 'loading' : '未审核');
    const visibleCharacters = (scene: Scene): string[] => {
        if (Array.isArray(scene.characters)) return scene.characters;
        if (typeof scene.characters === 'string' && scene.characters.trim()) return [scene.characters.trim()];
        try {
            const script = project.script ? JSON.parse(project.script) : {};
            const item = (script.scenes || []).find((candidate: any) => candidate.scene_number === scene.scene_number);
            return Array.isArray(item?.characters) ? item.characters : (scene.character_name ? [scene.character_name] : []);
        } catch { return scene.character_name ? [scene.character_name] : []; }
    };
    const save = async (scene: Scene, regenerate = false) => {
        setBusy(scene.scene_number); setError('');
        try {
            if (regenerate) await projectApi.regenerateScene(Number(project.id), scene.scene_number);
            else await projectApi.updateScene(Number(project.id), scene.scene_number, {
                visual_description: scene.visual_description, dialogue: scene.dialogue, character_name: scene.character_name,
                characters: visibleCharacters(scene),
            });
            setEditing(null); onReload();
        } catch(e) { setError(errorText(e)); }
        finally { setBusy(null); }
    };
    return <section style={{marginTop: 24}} aria-label="分镜列表">
        {error && <p className="wb-alert" role="alert">{error}</p>}
        {!project.scenes?.length && <p className="wb-muted">暂无分镜</p>}
        {project.scenes?.map(scene => <article key={scene.id} className="wb-item wb-scene">
            <span className="wb-number">{String(scene.scene_number).padStart(2, '0')}</span>
            <div>{editing?.id === scene.id ? <>
                <label>画面描述<textarea value={editing.visual_description} onChange={e => setEditing({...editing, visual_description: e.target.value})}/></label>
                <label>对白<textarea value={editing.dialogue || ''} onChange={e => setEditing({...editing, dialogue: e.target.value})}/></label>
                <label>说话角色<select value={editing.character_name || ''} onChange={e => setEditing({...editing, character_name: e.target.value || null})}><option value="">无</option>{project.characters?.map(c => <option key={c.id}>{c.name}</option>)}</select></label>
                <fieldset><legend>画面可见角色</legend>{project.characters?.map(c => { const selected = visibleCharacters(editing).includes(c.name); return <label key={c.id} className="wb-check"><input type="checkbox" checked={selected} onChange={e => { const current = visibleCharacters(editing); const next = e.target.checked ? [...current, c.name] : current.filter(name => name !== c.name); setEditing({...editing, characters: next}); }}/>{c.name}</label>; })}</fieldset>
            </> : <><h3>分镜 {scene.scene_number}</h3><p>{scene.visual_description}</p><p className="wb-muted">{scene.character_name || '无说话角色'}{scene.dialogue ? `：${scene.dialogue}` : ' · 无对白'}</p></>}
            <div className="wb-row" style={{marginTop: 14}}>
                {editing?.id === scene.id ? <><button className="wb-icon" aria-label="保存分镜" title="保存分镜" disabled={locked || busy !== null || !editing.visual_description.trim()} onClick={() => save(editing)}><Save size={17}/></button><button className="wb-icon" aria-label="取消编辑" title="取消编辑" disabled={busy !== null} onClick={() => setEditing(null)}><X size={17}/></button></> : <button className="wb-icon" aria-label={`编辑分镜 ${scene.scene_number}`} title="编辑分镜" disabled={locked || busy !== null} onClick={() => setEditing({...scene})}><Edit2 size={17}/></button>}
                <button className="wb-icon" aria-label={`重新生成分镜 ${scene.scene_number}`} title="重新生成分镜" disabled={locked || busy !== null} onClick={() => save(scene, true)}><RefreshCw size={17} className={busy === scene.scene_number ? 'animate-spin' : ''}/></button>
            </div></div>
            <div>
                {scene.image_path ? <ProjectImage projectId={Number(project.id)} path={scene.image_path} alt={`分镜 ${scene.scene_number} 关键帧`}/> : <span className="wb-muted">尚无关键帧</span>}
                {scene.video_path && <ProjectVideo projectId={Number(project.id)} path={scene.video_path} label={`分镜 ${scene.scene_number} 视频`}/>}
                <div className="wb-kv" style={{marginTop: 10}}><span>质检状态</span><strong className={`wb-score ${reviewStatus(scene.scene_number)}`}>{reviewStatus(scene.scene_number)}</strong></div>
                {sceneReview(scene.scene_number)?.technical_score !== undefined && <div className="wb-muted">技术分：{sceneReview(scene.scene_number).technical_score}</div>}
            </div>
        </article>)}
    </section>;
}
