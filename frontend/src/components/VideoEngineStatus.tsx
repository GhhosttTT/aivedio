import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { errorText, projectApi, VideoEnginePreflight } from '../api/client';

export function VideoEngineStatus() {
    const [report, setReport] = useState<VideoEnginePreflight | null>(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const provider = report?.provider;
    const ready = report?.status === 'ready_for_production_video_test';
    const load = async () => {
        setLoading(true);
        setError('');
        try {
            setReport(await projectApi.videoEnginePreflight());
        } catch (e) {
            setError(errorText(e));
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => { load(); }, []);
    return <section className={`wb-item ${ready ? '' : 'wb-alert'}`} aria-label="视频引擎状态">
        <div className="wb-row wb-between">
            <div className="wb-row">
                {ready ? <CheckCircle2 size={18} color="#82d6af"/> : <AlertTriangle size={18}/>}
                <strong>{ready ? '成品视频引擎已就绪' : '成品视频引擎未就绪'}</strong>
            </div>
            <button className="wb-icon" type="button" aria-label="刷新视频引擎状态" disabled={loading} onClick={load}>
                <RefreshCw size={16} className={loading ? 'animate-spin' : ''}/>
            </button>
        </div>
        {report && <p className="wb-muted">
            {ready
                ? '当前已配置可接受导演提示词的视频工作流，可以进入生产测试。'
                : '当前会被生产门槛拦截，避免把 SVD 保底结果误当成 Seed Dance 级成片。'}
        </p>}
        {report?.workflow && <p className="wb-muted">
            workflow: {report.workflow.workflow_path || '未配置'} · {report.workflow.status}
        </p>}
        {provider && provider.provider !== 'local_comfyui' && <p className="wb-muted">
            provider: {provider.provider || 'unknown'} · {provider.configuration?.api_format || 'legacy'} · {provider.configuration?.model || 'default'} · {provider.configuration?.resolution || '720p'} · 模式 {provider.configuration?.request_mode || 'reference'}
        </p>}
        {provider?.capabilities && <p className="wb-muted">
            多模态参考 {provider.capabilities.multimodal_references ? '✓' : '—'} ·
            连续镜头末帧 {provider.capabilities.continuity_last_frame ? '✓' : '—'} ·
            首尾帧 {provider.capabilities.first_last_frame ? '✓' : '—'} ·
            参考音频 {provider.capabilities.reference_audio_supported ? '✓' : '—'} ·
            编辑/延长 {provider.capabilities.edit_and_extend ? '✓' : '—'} ·
            原生音频 {provider.capabilities.native_audio ? '✓' : '—'} ·
            多镜头 {provider.capabilities.multi_shot ? '✓' : '—'}
        </p>}
        {provider?.capabilities?.output_artifact_validation !== undefined && <p className="wb-muted">
            Ark 输出文件校验 {provider.capabilities.output_artifact_validation ? '✓ 已启用' : '— 未启用'}
        </p>}
        {report?.action_items?.map((item) => <p key={item} className="wb-muted">{item}</p>)}
        {provider?.warnings?.map((item) => <p key={`provider-warning-${item}`} className="wb-muted">{item}</p>)}
        {provider?.action_items?.map((item) => <p key={`provider-action-${item}`} className="wb-muted">{item}</p>)}
        {error && <p role="alert" className="wb-alert">{error}</p>}
    </section>;
}
