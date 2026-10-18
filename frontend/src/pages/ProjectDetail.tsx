import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, FileText, Users, Activity, ShieldCheck, Play, RefreshCw, Film, Download } from 'lucide-react';
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
    const [deliveryUrl, setDeliveryUrl] = useState('');
    const [topicBrief, setTopicBrief] = useState({audience: '', platform: '', genre: '', hook_type: '', region: '', policy_notes: ''});
    const [assetNotes, setAssetNotes] = useState('');
    const [platformExportUrls, setPlatformExportUrls] = useState<Record<string, string>>({});
    const [options, setOptions] = useState({num_scenes: 16, num_characters: 2, style: '现代都市'});
    const [productionOptions, setProductionOptions] = useState({provider: '', request_mode: 'reference', multi_shot: true, sequence_level_multi_shot: false, native_audio: true, draft: false, model: '', resolution: '1080p', output_format: 'mp4', return_last_frame: true, camera_fixed: false, watermark: false, duration_seconds: null as number | null, add_bgm: false, bgm_path: null as string | null, bgm_volume: 0.3});
    const [bgmName, setBgmName] = useState('');
    const reload = useCallback(async () => {
        try {
            const projectId = Number(id);
            const [data, latest, ready, brief] = await Promise.all([
                projectApi.getProject(projectId),
                projectApi.latestTask(projectId),
                // The production button and model restrictions must use the same
                // engine preflight that the backend enforces on task creation.
                projectApi.productionReadiness(projectId, true, productionOptions.provider || undefined, productionOptions.model || undefined, productionOptions.request_mode || undefined, productionOptions.resolution || undefined, productionOptions.output_format || undefined, productionOptions.duration_seconds),
                projectApi.topicBrief(projectId),
            ]);
            setProject(data); setTask(latest); setReadiness(ready); setTopicBrief(current => ({...current, ...(brief.brief || {})})); setError('');
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
            } else if (operation === '按故事房建议重写剧本') {
                await projectApi.repairScript(Number(id));
                setTab('script');
            } else if (operation === '提升 Draft 正式片') {
                await projectApi.promoteDrafts(Number(id));
                setTab('production');
            } else if (operation === '导出交付包') {
                const exported = await projectApi.deliveryPackage(Number(id));
                const verification = await projectApi.verifyDeliveryPackage(Number(id));
                if (verification.status !== 'passed') throw new Error('交付包校验未通过');
                setDeliveryUrl(await projectApi.mediaUrl(Number(id), exported.package_path, true));
            } else if (operation === '保存选题定位') {
                await projectApi.updateTopicBrief(Number(id), topicBrief);
            } else if (operation === '冻结空间计划') {
                await projectApi.freezeSpatialPlan(Number(id), assetNotes);
            } else if (operation === '冻结视觉风格') {
                await projectApi.freezeVisualStyle(Number(id), {notes: assetNotes});
            } else if (operation.startsWith('导出平台:')) {
                const preset = operation.split(':')[1];
                const exported = await projectApi.platformExport(Number(id), preset);
                const url = await projectApi.mediaUrl(Number(id), exported.output_path, true);
                setPlatformExportUrls(current => ({...current, [preset]: url}));
            } else {
                await projectApi.startProduction(Number(id), productionOptions);
                setTab('production');
            }
            await reload();
        } catch(e) { setError(errorText(e)); }
        finally { setBusy(''); }
    };
    const uploadBgm = async (file: File) => {
        setBusy('上传 BGM'); setError('');
        try {
            const uploaded = await projectApi.uploadBgm(Number(id), file);
            setProductionOptions(current => ({...current, add_bgm: true, bgm_path: uploaded.bgm_path}));
            setBgmName(uploaded.filename);
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
    const draftPromotionBlocked = locked || (project.status === 'completed' && Boolean(project.final_video_path));
    const draftPromotionTitle = project.status === 'in_production'
        ? '项目正在制作，请等待当前任务结束'
        : project.status === 'completed' && project.final_video_path
            ? '项目已完成，不能重复提升 Draft'
            : '将已生成 Draft 提升为正式片';
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
    const nativeSeedanceNon25 = nativeArk && !seedance25;
    const providerCapabilities = providerPreflight?.capabilities || {};
    const fallbackModelOptions = [
        {id: 'doubao-seedance-2-5-260628', label: 'Seedance 2.5'},
        {id: 'doubao-seedance-2-0-260128', label: 'Seedance 2.0'},
        {id: 'doubao-seedance-2-0-fast-260128', label: 'Seedance 2.0 Fast'},
        {id: 'doubao-seedance-2-0-mini-260128', label: 'Seedance 2.0 Mini'},
        {id: 'doubao-seedance-1-0-pro-250528', label: 'Seedance 1.0 Pro'},
        {id: 'doubao-seedance-1-0-pro-fast-251015', label: 'Seedance 1.0 Pro Fast'},
    ];
    const modelOptions = Array.isArray(providerCapabilities.available_models)
        ? providerCapabilities.available_models.filter((item): item is {id: string; label: string} => (
            Boolean(item)
            && typeof item === 'object'
            && typeof item.id === 'string'
            && typeof item.label === 'string'
        ))
        : fallbackModelOptions;
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
    const supportsEdit = nativeArk && typeof providerCapabilities.supports_edit === 'boolean'
        ? providerCapabilities.supports_edit
        : !seedance10;
    const supportsExtend = nativeArk && typeof providerCapabilities.supports_extend === 'boolean'
        ? providerCapabilities.supports_extend
        : !seedance10;
    const supportsFirstFrame = !nativeArk || seedance10 || seedance25;
    const supportsFirstLastFrame = !nativeArk || providerCapabilities.first_last_frame === true;
    const durationIsAutomatic = ['edit', 'extend'].includes(productionOptions.request_mode);
    const durationChoices = [2, 5, 10, 12, 15, 30];
    const durationIsSupported = (seconds: number) => (
        !nativeArk
        || durationIsAutomatic
        || (seconds >= minimumDuration && seconds <= maximumDuration)
    );
    const productionOptionIssue = nativeArk && selectedSeedance
        ? selectedModel && !selectedSupportedResolutions.includes(productionOptions.resolution)
            ? `${selectedModel} 不支持 ${productionOptions.resolution}，可用：${selectedSupportedResolutions.join('、')}`
            : productionOptions.request_mode === 'auto' && !supportsAutoMode
                ? `原生自动识别任务类型仅支持 Seedance 2.5，当前模型为 ${selectedModel}`
                : productionOptions.request_mode === 'first_frame' && !supportsFirstFrame
                    ? `原生显式首帧模式仅支持 Seedance 1.0 或 2.5，当前模型为 ${selectedModel}`
                    : productionOptions.request_mode === 'first_last_frame' && !supportsFirstLastFrame
                        ? `当前模型不支持原生首尾帧模式：${selectedModel}`
                    : ['first_frame', 'first_last_frame'].includes(productionOptions.request_mode) && seedance25 && !productionOptions.draft
                        ? 'Seedance 2.5 首帧/首尾帧模式必须先生成 Draft，再提升正式片'
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
        const nextSupportsAuto = nextIs25;
        const nextSupportsEdit = !nextIs10;
        const nextSupportsExtend = !nextIs10;
        const nextSupportsFirstFrame = nextIs10 || nextIs25;
        const nextSupportsFirstLastFrame = !nativeArk || nextIs25 || nextIs20 || (nextIs10 && !normalized.includes('fast'));
        const nextMode = nativeArk && (
            (productionOptions.request_mode === 'auto' && !nextSupportsAuto)
            || (productionOptions.request_mode === 'edit' && !nextSupportsEdit)
            || (productionOptions.request_mode === 'extend' && !nextSupportsExtend)
            || (productionOptions.request_mode === 'first_frame' && !nextSupportsFirstFrame)
            || (productionOptions.request_mode === 'first_last_frame' && !nextSupportsFirstLastFrame)
        ) ? 'reference' : productionOptions.request_mode;
        const nextMinimumDuration = nextIs25 && ['edit', 'extend'].includes(nextMode)
            ? 4
            : nextIs20
                ? 4
                : (nextIs25 || nextIs10)
                    ? 2
                    : 4;
        const nextMaximumDuration = nextIs25 ? 30 : nextIs10 ? 12 : 15;
        setProductionOptions(current => ({
            ...current,
            model,
            request_mode: nextMode,
            resolution: nativeArk && !nextSupportedResolutions.includes(current.resolution)
                ? nextSupportedResolutions[nextSupportedResolutions.length - 1]
                : current.resolution,
            output_format: nextIsNon25 && current.output_format === 'mov' ? 'mp4' : current.output_format,
            draft: nextIsNon25 ? false : current.draft,
            duration_seconds: current.duration_seconds !== null
                && (current.duration_seconds < nextMinimumDuration || current.duration_seconds > nextMaximumDuration)
                ? null
                : current.duration_seconds,
        }));
    };
    const setRequestMode = (request_mode: string) => setProductionOptions(current => ({
        ...current,
        request_mode,
        duration_seconds: ['edit', 'extend'].includes(request_mode) ? null : current.duration_seconds,
        multi_shot: request_mode === 'multi_shot' ? true : ['edit', 'extend', 'auto', 'first_frame', 'first_last_frame'].includes(request_mode) ? false : current.multi_shot,
        draft: ['first_frame', 'first_last_frame'].includes(request_mode) && seedance25 ? true : current.draft,
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
                {project.final_video_path && <button className="wb-button" disabled={locked} onClick={() => run('导出交付包')}><Download size={17}/>导出交付包</button>}
                {deliveryUrl && <a className="wb-button" href={deliveryUrl}><Download size={17}/>下载 ZIP</a>}
                <button className="wb-button primary" disabled={locked || !project.scenes?.length || productionBlocked || Boolean(productionOptionIssue)} title={productionOptionIssue || (productionBlocked ? productionBlockedTitle : '开始制作')} onClick={() => run('提交制作')}><Play size={17}/>开始制作</button>
            </div>
        </header>
        {error && <p role="alert" className="wb-alert">{error}</p>}
        {busy && <p role="status" className="wb-alert"><RefreshCw size={15} className="inline animate-spin"/> {busy}进行中</p>}
        <VideoEngineStatus/>
        <ProductionReadinessPanel report={readiness} loading={readinessLoading} onRefresh={refreshReadiness}/>
        <section className="wb-item" aria-label="连续性资产锁">
            <div className="wb-row wb-between">
                <div>
                    <strong>连续性资产锁</strong>
                    <p className="wb-muted">冻结空间走位和视觉风格后，后续镜头会使用同一套控制约束。</p>
                </div>
                <span className="wb-badge">
                    空间：{readiness?.checks.spatial_continuity?.asset_pack?.status || '未冻结'} · 风格：{readiness?.checks.visual_style?.status || '未冻结'}
                </span>
            </div>
            <label>审核备注<input disabled={locked} value={assetNotes} onChange={e => setAssetNotes(e.target.value)} placeholder="可选：记录机位、色调和连续性审核结论" /></label>
            <div className="wb-row">
                <button className="wb-button" disabled={locked || !project.scenes?.length} onClick={() => run('冻结空间计划')}>冻结空间计划</button>
                <button className="wb-button" disabled={locked || !project.scenes?.length} onClick={() => run('冻结视觉风格')}>冻结视觉风格</button>
            </div>
        </section>
        <section className="wb-item" aria-label="选题定位">
            <div className="wb-row wb-between"><strong>选题定位锁</strong><span className="wb-muted">让剧本、镜头和审核共享同一商业目标</span></div>
            <div className="wb-fields">
                <label>目标受众<input disabled={locked} value={topicBrief.audience} onChange={e => setTopicBrief({...topicBrief, audience: e.target.value})} placeholder="如：18–35 岁女性"/></label>
                <label>发布平台<input disabled={locked} value={topicBrief.platform} onChange={e => setTopicBrief({...topicBrief, platform: e.target.value})} placeholder="如：抖音竖屏"/></label>
                <label>类型<input disabled={locked} value={topicBrief.genre} onChange={e => setTopicBrief({...topicBrief, genre: e.target.value})} placeholder="如：都市悬疑"/></label>
                <label>开场钩子<input disabled={locked} value={topicBrief.hook_type} onChange={e => setTopicBrief({...topicBrief, hook_type: e.target.value})} placeholder="如：秘密曝光"/></label>
                <label>地区/语言<input disabled={locked} value={topicBrief.region} onChange={e => setTopicBrief({...topicBrief, region: e.target.value})} placeholder="如：中国大陆 / 中文"/></label>
                <label>合规/品牌约束<input disabled={locked} value={topicBrief.policy_notes} onChange={e => setTopicBrief({...topicBrief, policy_notes: e.target.value})} placeholder="可选"/></label>
            </div>
            <button className="wb-button" disabled={locked || Object.entries(topicBrief).some(([key, value]) => key !== 'policy_notes' && !value.trim())} onClick={() => run('保存选题定位')}>保存选题定位</button>
        </section>
        {project.final_video_path && <section className="wb-item" aria-label="平台版本导出">
            <div className="wb-row wb-between"><strong>平台版本导出</strong><span className="wb-muted">固定尺寸、帧率、H.264/AAC 与响度规范</span></div>
            <div className="wb-row">
                {[['douyin', '抖音竖屏'], ['shorts', 'Shorts / Reels'], ['landscape', '横屏 16:9'], ['square', '方形 1:1']].map(([preset, label]) => <span key={preset} className="wb-row"><button className="wb-button" disabled={locked || !readiness || readiness.status !== 'ready'} onClick={() => run(`导出平台:${preset}`)}>{label}</button>{platformExportUrls[preset] && <a className="wb-button" href={platformExportUrls[preset]}>下载</a>}</span>)}
            </div>
        </section>}
        {readiness?.checks.story_room?.missing?.length && (
            <section className="wb-item" aria-label="故事房修复">
                <div className="wb-row wb-between">
                    <div>
                        <strong>故事房质量仍有缺项</strong>
                        <p className="wb-muted">先让审核模型依据当前剧本证据重写，再重新生成视觉资产。</p>
                    </div>
                    <button className="wb-button" disabled={locked} onClick={() => run('按故事房建议重写剧本')}>按建议重写剧本</button>
                </div>
            </section>
        )}
        <section className="wb-item" aria-label="本次视频生成配置">
            <div className="wb-row wb-between"><strong>本次视频生成配置</strong><span className="wb-muted">留空 provider 使用环境默认值</span></div>
            <div className="wb-fields">
                <label>视频引擎<select disabled={locked} value={productionOptions.provider} onChange={e => setProvider(e.target.value)}>
                    <option value="">环境默认</option><option value="seedance_api">Seedance / Ark</option><option value="http_video_api">兼容视频网关</option><option value="local_comfyui">本地 ComfyUI</option>
                </select></label>
                <label>任务模式<select disabled={locked} value={productionOptions.request_mode} onChange={e => setRequestMode(e.target.value)}>
                    <option value="reference">参考生视频 / Ark</option><option value="first_frame" disabled={nativeArk && !supportsFirstFrame}>显式首帧 Draft{nativeArk && !supportsFirstFrame ? '（当前模型不支持）' : ''}</option><option value="first_last_frame" disabled={nativeArk && !supportsFirstLastFrame}>显式首尾帧{nativeArk && !supportsFirstLastFrame ? '（当前模型不支持）' : ''}</option><option value="auto" disabled={nativeArk && !supportsAutoMode}>自动识别任务类型 / Ark 2.5</option><option value="reference_to_video">参考生视频 / 兼容网关</option><option value="multi_shot">多镜头 2.5</option><option value="edit" disabled={nativeArk && !supportsEdit}>视频编辑{nativeArk && !supportsEdit ? '（当前模型不支持）' : ''}</option><option value="extend" disabled={nativeArk && !supportsExtend}>视频延长{nativeArk && !supportsExtend ? '（当前模型不支持）' : ''}</option>
                </select></label>
                <label>Seedance 模型<select disabled={locked || productionOptions.provider !== 'seedance_api'} value={productionOptions.model} onChange={e => setModel(e.target.value)}>
                    <option value="">环境默认</option>{modelOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select></label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.native_audio} onChange={e => setProductionOptions({...productionOptions, native_audio: e.target.checked})}/>原生音频</label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.multi_shot} onChange={e => setProductionOptions({...productionOptions, multi_shot: e.target.checked})}/>启用多镜头</label>
                <label className="wb-check"><input type="checkbox" disabled={locked || productionOptions.request_mode !== 'multi_shot'} checked={productionOptions.sequence_level_multi_shot} onChange={e => setProductionOptions({...productionOptions, sequence_level_multi_shot: e.target.checked})}/>生成完整 30 秒序列并按时间轴切回分镜</label>
                <label className="wb-check"><input type="checkbox" disabled={locked || (nativeArk && !supportsDraft)} checked={productionOptions.draft} onChange={e => setProductionOptions({...productionOptions, draft: e.target.checked})}/>先生成 Draft 样片{nativeArk && !supportsDraft ? '（当前模型不支持）' : ''}</label>
                <label>输出分辨率<select disabled={locked} value={productionOptions.resolution} onChange={e => setProductionOptions({...productionOptions, resolution: e.target.value})}><option value="480p" disabled={nativeArk && !selectedSupportedResolutions.includes('480p')}>480p</option><option value="720p" disabled={nativeArk && !selectedSupportedResolutions.includes('720p')}>720p</option><option value="1080p" disabled={nativeArk && !selectedSupportedResolutions.includes('1080p')}>1080p{nativeArk && !selectedSupportedResolutions.includes('1080p') ? '（当前模型不支持）' : ''}</option><option value="4k" disabled={nativeArk && !selectedSupportedResolutions.includes('4k')}>4K{nativeArk && !selectedSupportedResolutions.includes('4k') ? '（当前模型不支持）' : ''}</option></select></label>
                <label>单镜头时长<select disabled={locked || durationIsAutomatic} value={productionOptions.duration_seconds ?? ''} onChange={e => setProductionOptions({...productionOptions, duration_seconds: e.target.value ? Number(e.target.value) : null})}><option value="">{durationIsAutomatic ? '按输入视频自动保持（-1）' : '自动按分镜/对白'}</option>{durationChoices.map(seconds => <option key={seconds} value={seconds} disabled={!durationIsSupported(seconds)}>{seconds} 秒{!durationIsSupported(seconds) ? '（当前模型范围 ' + minimumDuration + '–' + maximumDuration + ' 秒）' : ''}</option>)}</select></label>
                <label>输出格式<select disabled={locked} value={productionOptions.output_format} onChange={e => setProductionOptions({...productionOptions, output_format: e.target.value})}><option value="mp4">MP4</option><option value="mov" disabled={nativeArk && !supportsMov}>MOV{nativeArk && !supportsMov ? '（当前模型不支持）' : ''}</option></select></label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.return_last_frame} onChange={e => setProductionOptions({...productionOptions, return_last_frame: e.target.checked})}/>返回末帧</label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.camera_fixed} onChange={e => setProductionOptions({...productionOptions, camera_fixed: e.target.checked})}/>固定镜头</label>
                <label className="wb-check"><input type="checkbox" disabled={locked} checked={productionOptions.watermark} onChange={e => setProductionOptions({...productionOptions, watermark: e.target.checked})}/>添加水印</label>
                <label className="wb-check"><input type="checkbox" disabled={locked || !productionOptions.bgm_path} checked={productionOptions.add_bgm} onChange={e => setProductionOptions({...productionOptions, add_bgm: e.target.checked})}/>添加背景音乐{!productionOptions.bgm_path ? '（先上传）' : ''}</label>
                <label>背景音乐<input type="file" accept="audio/mpeg,audio/wav,audio/mp4,audio/aac,audio/ogg" disabled={locked || Boolean(busy)} onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void uploadBgm(file); }}/>{bgmName && <span className="wb-muted">已上传：{bgmName}</span>}</label>
                {productionOptions.add_bgm && <label>音乐底噪音量<input type="range" min="0" max="1" step="0.05" disabled={locked} value={productionOptions.bgm_volume} onChange={e => setProductionOptions({...productionOptions, bgm_volume: Number(e.target.value)})}/><span className="wb-muted">{Math.round(productionOptions.bgm_volume * 100)}%（对白自动 ducking）</span></label>}
            </div>
            {productionOptionIssue && <p role="alert" className="wb-alert">{productionOptionIssue}</p>}
            <button className="wb-button" disabled={draftPromotionBlocked} title={draftPromotionTitle} onClick={() => run('提升 Draft 正式片')}>将已生成 Draft 提升为正式片</button>
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
