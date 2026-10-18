import { useEffect, useState } from 'react';
import { CheckCircle, Circle, Loader, RefreshCw, X } from 'lucide-react';
import { errorText, ProductionTask, projectApi, taskApi } from '../api/client';
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
    const [outputUrl, setOutputUrl] = useState('');
    const outputPath = task?.result?.output_path;
    useEffect(() => {
        let active = true;
        setOutputUrl('');
        if (task?.status !== 'completed' || typeof outputPath !== 'string' || !outputPath) {
            return () => { active = false; };
        }
        projectApi.mediaUrl(Number(project.id), outputPath)
            .then(url => { if (active) setOutputUrl(url); })
            .catch(() => { if (active) setOutputUrl(''); });
        return () => { active = false; };
    }, [project.id, task?.status, outputPath]);
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
    const providerStageNames: Record<string,string> = {provider_queued: 'Seedance 排队中', provider_running: 'Seedance 任务已启动', provider_processing: 'Seedance 生成中', provider_succeeded: 'Seedance 已生成，正在下载', provider_completed: 'Seedance 已生成，正在下载', provider_downloaded: 'Seedance 视频已下载', provider_failed: 'Seedance 生成失败', provider_timeout: 'Seedance 请求超时'};
    const statusLabel = !task ? '未提交' : ({running: '制作中', pending: '排队中', completed: '已完成', failed: '失败', cancelled: '已请求取消'}[task.status] || task.status);
    return <section aria-label="制作进度">
        <div className="wb-row wb-between"><h2>{statusLabel}</h2><div className="wb-row">
            {running && <button className="wb-button danger" disabled={busy} onClick={() => action(true)}><X size={16}/>取消制作</button>}
            {task?.status === 'failed' && project.status !== 'in_production' && <button className="wb-button" disabled={busy} onClick={() => action(false)}><RefreshCw size={16}/>重试任务</button>}
        </div></div>
        <progress value={progress} max={100} aria-label="总体进度"/>
        <p className="wb-muted">{Math.round(progress)}% · {task ? `${current} / ${task.total_steps} 步` : `${steps.length} 步`}</p>
        {task?.production_options && <p className="wb-muted">本次参数：{task.production_options.provider || '环境默认'} · {task.production_options.model || '环境默认模型'} · {task.production_options.resolution || '默认分辨率'} · {task.production_options.output_format || '默认格式'}</p>}
        {outputUrl && <div className="wb-production-result"><p className="wb-muted">最终成片</p><video controls preload="metadata" src={outputUrl} aria-label="最终成片预览" style={{maxWidth: '100%', borderRadius: 8}} /></div>}
        {running && task?.live_step && <p role="status">{liveScene ? `分镜 ${liveScene.scene_number} · ` : ''}{stageNames[task.live_step.stage] || task.live_step.stage}</p>}
        {running && task?.provider_stage && <p role="status" className="wb-muted">{providerStageNames[task.provider_stage] || task.provider_stage}{typeof task.provider_progress === 'number' ? ' · ' + Math.round(task.provider_progress) + '%' : ''}</p>}
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
