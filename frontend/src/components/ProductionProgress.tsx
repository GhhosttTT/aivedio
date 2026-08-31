import { useState } from 'react';
import { CheckCircle, Circle, Loader, RefreshCw, X } from 'lucide-react';
import { errorText, ProductionTask, taskApi } from '../api/client';
import type { Project } from '../types';

export const productionSteps = (count: number) => [
    '情节复审与提示词准备',
    ...Array.from({length: count}, (_, i) => `分镜 ${i + 1} · 图像生成`),
    ...Array.from({length: count}, (_, i) => `分镜 ${i + 1} · 视频生成`),
    ...Array.from({length: count}, (_, i) => `分镜 ${i + 1} · 配音生成`),
    ...Array.from({length: count}, (_, i) => `分镜 ${i + 1} · 字幕生成`),
    '抽帧评分与质量门禁', '字幕压制与最终合成',
];

export function ProductionProgress({project, task, onReload}: {project: Project; task: ProductionTask | null; onReload: () => void}) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const steps = productionSteps(project.scenes?.length || 0);
    const running = task?.status === 'running' || task?.status === 'pending';
    const action = async (cancel: boolean) => {
        if (!task || busy) return;
        setBusy(true); setError('');
        try {
            if (cancel) await taskApi.cancelTask(task.celery_task_id);
            else await taskApi.retryTask(task.celery_task_id);
            onReload();
        } catch(e) { setError(errorText(e)); }
        finally { setBusy(false); }
    };
    const current = task?.current_step || 0;
    const progress = Math.max(0, Math.min(100, task?.progress || 0));
    const stageNames: Record<string,string> = {prepare_generation: '情节复审与提示词准备', generate_image: '图像生成', generate_video: '视频生成', generate_audio: '配音生成', generate_subtitle: '字幕生成', review_generation: '抽帧评分', compose_final_video: '最终合成'};
    const liveScene = project.scenes?.find(scene => scene.id === task?.live_step?.scene_id);
    const statusLabel = !task ? '未提交' : ({running: '制作中', pending: '排队中', completed: '已完成', failed: '失败', cancelled: '已请求取消'}[task.status] || task.status);
    return <section aria-label="制作进度">
        <div className="wb-row wb-between"><h2>{statusLabel}</h2><div className="wb-row">
            {running && <button className="wb-button danger" disabled={busy} onClick={() => action(true)}><X size={16}/>取消制作</button>}
            {task?.status === 'failed' && project.status !== 'in_production' && <button className="wb-button" disabled={busy} onClick={() => action(false)}><RefreshCw size={16}/>重试任务</button>}
        </div></div>
        <progress value={progress} max={100} aria-label="总体进度"/>
        <p className="wb-muted">{Math.round(progress)}% · {task ? `${current} / ${task.total_steps} 步` : `${steps.length} 步`}</p>
        {running && task?.live_step && <p role="status">{liveScene ? `分镜 ${liveScene.scene_number} · ` : ''}{stageNames[task.live_step.stage] || task.live_step.stage}</p>}
        {(error || task?.error_message) && <p role="alert" className="wb-alert">{error || task?.error_message}</p>}
        <ol>{steps.map((label, index) => {
            const done = task?.status === 'completed' || index < current;
            const active = task?.status === 'running' && index === current;
            return <li className="wb-row wb-item" key={label}>
                {done ? <CheckCircle size={18} color="#82d6af"/> : active ? <Loader size={18} className="animate-spin"/> : <Circle size={18} color="#777"/>}
                <span>{label}</span><span className="wb-muted">{done ? '已完成' : active ? '处理中' : index === current && task?.status === 'failed' ? '失败' : '等待'}</span>
            </li>;
        })}</ol>
    </section>;
}
