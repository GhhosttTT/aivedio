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
    const [productionOptions, setProductionOptions] = useState({provider: '', request_mode: 'reference', multi_shot: true, sequence_level_multi_shot: false, native_audio: true, draft: false, model: '', resolution: '1080p', output_format: 'mp4', return_last_frame: true, camera_fixed: false, watermark: false, duration_seconds: null as number | null});
    const reload = useCallback(async () => {
        try {
            const projectId = Number(id);
            const [data, latest, ready] = await Promise.all([
                projectApi.getProject(projectId),
                projectApi.latestTask(projectId),
                // The production button and model restrictions must use the same
                // engine preflight that the backend enforces on task creation.
                projectApi.productionReadiness(projectId, true, productionOptions.provider || undefined, productionOptions.model || undefined, productionOptions.request_mode || undefined, productionOptions.resolution || undefined, productionOptions.output_format || undefined, productionOptions.duration_seconds),
            ]);
            setProject(data); setTask(latest); setReadiness(ready); setError('');
        } catch(e) { setError(errorText(e)); }
        finally { setLoading(false); }
    }, [id, productionOptions.provider, productionOptions.model, productionOptions.request_mode, productionOptions.resolution, productionOptions.output_format, productionOptions.duration_seconds]);
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
            } else if (operation === '提升 Draft 正式片') {
                await projectApi.promoteDrafts(Number(id));
                setTab('production');
            } else {
                await projectApi.startProduction(Number(id), productionOptions);
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
        setReadiness(await projectApi.productionReadiness(Number(id), true, productionOptions.provider || undefined, productionOptions.model || undefined, productionOptions.request_mode || undefined, productionOptions.resolution || undefined, productionOptions.output_format || undefined, productionOptions.duration_seconds));
        } catch(e) { setError(errorText(e)); }
        finally { setReadinessLoading(false); }
    }, [id, productionOptions.provider, productionOptions.model, productionOptions.request_mode, productionOptions.resolution, productionOptions.output_format, productionOptions.duration_seconds]);
    useEffect(() => {
        if (productionOptions.provider || productionOptions.model || productionOptions.request_mode || productionOptions.resolution || productionOptions.output_format || productionOptions.duration_seconds !== null) {
            // Never let a report for the previous engine/model authorize a new
            // paid generation request while the replacement preflight is running.
            setReadiness(null);
            void refreshReadiness();
        }
    }, [productionOptions.provider, productionOptions.model, productionOptions.request_mode, productionOptions.resolution, productionOptions.output_format, productionOptions.duration_seconds, refreshReadiness]);
    if (loading) return <main className="workbench" role="status">项目加载中</main>;
    if (!project) return <main className="workbench"><Link to="/projects">返回项目</Link><p role="alert" className="wb-alert">{error || '项目不存在'}</p><button className="wb-button" onClick={reload}>重试</button></main>;
    const productionBlocked = !readiness || readiness.status !== 'ready';
    const productionBlockedTitle = !readiness ? '生产就绪检查未完成' : readiness.status === 'needs_review' ? '先处理生产复查项' : '先处理生产就绪阻断项';
    const locked = Boolean(busy) || project.status === 'in_production';
    const providerPreflight = readiness?.checks?.video_engine?.provider;
    const selectedSeedance = productionOptions.provider === 'seedance_api'
        || (!productionOptions.provider && providerPreflight?.provider === 'seedance_api');
    const nativeArk = selectedSeedance && providerPreflight?.checks?.native_ark_format === true;
    const configuredModel = String(providerPreflight?.configuration?.model || '').toLowerCase();
    const selectedModel = String(productionOptions.model || configuredModel).toLowerCase();
    const seedance25 = ['2.5', '2-5', '2_5'].some(token => selectedModel.includes(token));
    const seedance10 = ['1.0', '1-0'].some(token => selectedModel.includes(token));
    const seedance20 = ['2.0', '2-0'].some(token => selectedModel.includes(token));
    const seedance20Limited = seedance20 && (selectedModel.includes('fast') || selectedModel.includes('mini'));
    const nativeSeedance25 = nativeArk && seedance25;
    const nativeSeedanceNon25 = nativeArk && !seedance25;
    const providerCapabilities = providerPreflight?.capabilities || {};
    const capabilityResolutions = Array.isArray(providerCapabilities.supported_resolutions)
        ? providerCapabilities.supported_resolutions.map(String)
        : [];
    const selectedSupportedResolutions = nativeArk && capabilityResolutions.length
        ? capabilityResolutions
        : seedance25
        ? ['480p', '720p', '1080p']
        : seedance20Limited
            ? ['480p', '720p']
            : seedance10
                ? ['480p', '720p', '1080p']
                : ['480p', '720p', '1080p', '4k'];
    const capabilityMinDuration = Number(providerCapabilities.duration_min_seconds);
    const capabilityMaxDuration = Number(providerCapabilities.duration_max_seconds);
    const minimumDuration = nativeArk && Number.isFinite(capabilityMinDuration)
        ? capabilityMinDuration
        : (seedance25 && ['edit', 'extend'].includes(productionOptions.request_mode) ? 4 : seedance20 ? 4 : (seedance25 || seedance10) ? 2 : 4);
    const maximumDuration = nativeArk && Number.isFinite(capabilityMaxDuration)
        ? capabilityMaxDuration
        : (seedance25 ? 30 : seedance10 ? 12 : 15);
    const supportsAutoMode = nativeArk && typeof providerCapabilities.supports_auto_mode === 'boolean'
        ? providerCapabilities.supports_auto_mode
        : seedance25;
    const supportsDraft = nativeArk && typeof providerCapabilities.supports_draft === 'boolean'
        ? providerCapabilities.supports_draft
        : seedance25;
    const supportsMov = nativeArk && typeof providerCapabilities.supports_mov === 'boolean'
        ? providerCapabilities.supports_mov
        : seedance25;
    const productionOptionIssue = nativeArk && selectedSeedance
        ? selectedModel && !selectedSupportedResolutions.includes(productionOptions.resolution)
            ? `${selectedModel} 不支持 ${productionOptions.resolution}，可用：${selectedSupportedResolutions.join('、')}`
            : productionOptions.request_mode === 'auto' && !supportsAutoMode
                ? `原生自动识别任务类型仅支持 Seedance 2.5，当前模型为 ${selectedModel}`
            : seedance10 && ['edit', 'extend'].includes(productionOptions.request_mode)
                ? `原生 ${selectedModel} 不支持${productionOptions.request_mode === 'edit' ? '编辑' : '延长'}任务，请使用 Seedance 2.0 或 2.5`
                : productionOptions.duration_seconds !== null
                    && (productionOptions.duration_seconds < minimumDuration
                        || productionOptions.duration_seconds > maximumDuration)
                    ? `${selectedModel} 单镜头时长必须在 ${minimumDuration}–${maximumDuration} 秒之间`
                    : ''
        : '';
    const setModel = (model: string) => {
        const normalized = (model || configuredModel).toLowerCase();
        const nextIs25 = ['2.5', '2-5', '2_5'].some(token => normalized.includes(token));
        const nextIs10 = ['1.0', '1-0'].some(token => normalized.includes(token));
        const nextIs20 = ['2.0', '2-0'].some(token => normalized.includes(token));
        const nextIs20Limited = nextIs20 && (normalized.includes('fast') || normalized.includes('mini'));
        const nextSupportedResolutions = nextIs25
            ? ['480p', '720p', '1080p']
            : nextIs20Limited
                ? ['480p', '720p']
                : nextIs10
                    ? ['480p', '720p', '1080p']
                    : ['480p', '720p', '1080p', '4k'];
        const nextIsNon25 = nativeArk && !nextIs25;
        setProductionOptions(current => ({
            ...current,
            model,
            resolution: nativeArk && !nextSupportedResolutions.includes(current.resolution)
                ? nextSupportedResolutions[nextSupportedResolutions.length - 1]
                : current.resolution,
            output_format: nextIsNon25 && current.output_format === 'mov' ? 'mp4' : current.output_format,
            draft: nextIsNon25 ? false : current.draft,
        }));
    };
    const setRequestMode = (request_mode: string) => setProductionOptions(current => ({
        ...current,
        request_mode,
        duration_seconds: ['edit', 'extend'].includes(request_mode) ? null : current.duration_seconds,
        multi_shot: request_mode === 'multi_shot' ? true : ['edit', 'extend', 'auto'].includes(request_mode) ? false : current.multi_shot,
        resolution: (
            nativeArk
            && current.resolution === '4k'
        ) ? '1080p' : current.resolution,
        output_format: nativeSeedanceNon25 && current.output_format === 'mov' ? 'mp4' : current.output_format,
    }));
    const setProvider = (provider: string) => setProductionOptions(current => ({
        ...current,
        provider,
        resolution: provider === 'seedance_api' && nativeArk && current.resolution === '4k' ? '1080p' : current.resolution,
        output_format: provider === 'seedance_api' && nativeSeedanceNon25 && current.output_format === 'mov' ? 'mp4' : current.output_format,
    }));
    return <main className="workbench">
        <Link to="/projects" className="wb-row wb-muted"><ArrowLeft size={16}/>项目列表</Link>
        <header className="wb-row wb-between" style={{marginTop: 18}}>
            <div><h1>{project.name}</h1><p className="wb-muted">{project.theme || project.description || '短剧项目'} · {project.scenes?.length || 0} 个分镜</p></div>
            <div className="wb-row">
                <button className="wb-icon" title="刷新项目" aria-label="刷新项目" onClick={reload}><RefreshCw size={17}/></button>
                {project.final_video_path && <Link className="wb-button" to={`/projects/${id}/video`}><Film size={17}/>查看成片</Link>}
                <button className="wb-button primary" disabled={locked || !project.scenes?.length || productionBlocked || Boolean(productionOptionIssue)} title={productionOptionIssue || (productionBlocked ? productionBlockedTitle : '开始制作')} onClick={() => run('提交制作')}><Play size={17}/>开始制作</button>
            </div>
        </header>
        {error && <p role="alert" className="wb-alert">{error}</p>}
        {busy && <p role="status" className="wb-alert"><RefreshCw size={15} className="inline animate-spin"/> {busy}进行中</p>}
        <VideoEngineStatus/>
        <ProductionReadinessPanel report={readiness} loading={readinessLoading} onRefresh={refreshReadiness}/>
        <section className="wb-item" aria-label="本次视频生成配置">
            <div className="wb-row wb-between"><strong>本次视频生成配置</strong><span className="wb-muted">留空 provider 使用环境默认值</span></div>
            <div className="wb-fields">
                <label>视频引擎<select disabled={locked} value={productionOptions.provider} onChange={e => setProvider(e.target.value)}>
                    <option value="">环境默认</option><option value="seedance_api">Seedance / Ark</option><option value="http_video_api">兼容视频网关</option><option value="local_comfyui">本地 ComfyUI</option>
                </select></label>
                <label>任务模式<select disabled={locked} value={productionOptions.request_mode} onChange={e => setRequestMode(e.target.value)}>
                    <option value="reference">参考生视频 / Ark</option><option value="auto">自动识别任务类型 / Ark 2.5</option><option value="reference_to_video">参考生视频 / 兼容网关</option><option value="multi_shot">多镜头 2.5</option><option value="edit">视频编辑</option><option value="extend">视频延长</option>
                </select></label>
                <label>Seedance 模型<select disabled={locked || productionOptions.provider !== 'seedance_api'} value={productionOptions.model} onChange={e => setModel(e.target.value)}>
                    <option value="">环境默认</option><option value="doubao-seedance-2-5-260628">Seedance 2.5</option><option value="doubao-seedance-2-0-260128">Seedance 2.0</option><option value="doubao-seedance-1-0-pro-250528">Seedance 1.0 Pro</option>
                </select></label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.native_audio} onChange={e => setProductionOptions({...productionOptions, native_audio: e.target.checked})}/>原生音频</label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.multi_shot} onChange={e => setProductionOptions({...productionOptions, multi_shot: e.target.checked})}/>启用多镜头</label>
                <label className="wb-check"><input type="checkbox" disabled={locked || productionOptions.request_mode !== 'multi_shot'} checked={productionOptions.sequence_level_multi_shot} onChange={e => setProductionOptions({...productionOptions, sequence_level_multi_shot: e.target.checked})}/>生成完整 30 秒序列并按时间轴切回分镜</label>
                <label className="wb-check"><input type="checkbox" disabled={locked || (nativeArk && !supportsDraft)} checked={productionOptions.draft} onChange={e => setProductionOptions({...productionOptions, draft: e.target.checked})}/>先生成 Draft 样片{nativeArk && !supportsDraft ? '（当前模型不支持）' : ''}</label>
                <label>输出分辨率<select disabled={locked} value={productionOptions.resolution} onChange={e => setProductionOptions({...productionOptions, resolution: e.target.value})}><option value="480p" disabled={nativeArk && !selectedSupportedResolutions.includes('480p')}>480p</option><option value="720p" disabled={nativeArk && !selectedSupportedResolutions.includes('720p')}>720p</option><option value="1080p" disabled={nativeArk && !selectedSupportedResolutions.includes('1080p')}>1080p{nativeArk && !selectedSupportedResolutions.includes('1080p') ? '（当前模型不支持）' : ''}</option><option value="4k" disabled={nativeArk && !selectedSupportedResolutions.includes('4k')}>4K{nativeArk && !selectedSupportedResolutions.includes('4k') ? '（当前模型不支持）' : ''}</option></select></label>
                <label>单镜头时长<select disabled={locked || (nativeSeedance25 && ['edit', 'extend'].includes(productionOptions.request_mode))} value={productionOptions.duration_seconds ?? ''} onChange={e => setProductionOptions({...productionOptions, duration_seconds: e.target.value ? Number(e.target.value) : null})}><option value="">{nativeSeedance25 && ['edit', 'extend'].includes(productionOptions.request_mode) ? '按输入视频自动保持（-1）' : '自动按分镜/对白'}</option><option value={2} disabled={nativeSeedance25 && ['edit', 'extend'].includes(productionOptions.request_mode)}>2 秒{nativeSeedance25 && ['edit', 'extend'].includes(productionOptions.request_mode) ? '（编辑/延长最低 4 秒）' : ''}</option><option value={5}>5 秒</option><option value={10}>10 秒</option><option value={15}>15 秒</option><option value={30}>30 秒</option></select></label>
                <label>输出格式<select disabled={locked} value={productionOptions.output_format} onChange={e => setProductionOptions({...productionOptions, output_format: e.target.value})}><option value="mp4">MP4</option><option value="mov" disabled={nativeArk && !supportsMov}>MOV{nativeArk && !supportsMov ? '（当前模型不支持）' : ''}</option></select></label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.return_last_frame} onChange={e => setProductionOptions({...productionOptions, return_last_frame: e.target.checked})}/>返回末帧</label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.camera_fixed} onChange={e => setProductionOptions({...productionOptions, camera_fixed: e.target.checked})}/>固定镜头</label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.watermark} onChange={e => setProductionOptions({...productionOptions, watermark: e.target.checked})}/>添加水印</label>
            </div>
            {productionOptionIssue && <p role="alert" className="wb-alert">{productionOptionIssue}</p>}
            <button className="wb-button" disabled={locked} onClick={() => run('提升 Draft 正式片')}>将已生成 Draft 提升为正式片</button>
        </section>
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
