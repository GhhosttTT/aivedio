import { Plus, RotateCcw, Trash2 } from 'lucide-react';
import type { ContinuityAssetKind, EngineCapability, ShotCharacterState, ShotContinuityAsset, ShotIntensity, ShotRole, ShotSpecification } from '../types/shotSpecification';

const capabilityOptions: Array<{value: EngineCapability; label: string}> = [
    {value: 'identity_reference', label: '角色身份参考'},
    {value: 'performance_control', label: '表演控制'},
    {value: 'multi_character', label: '多角色控制'},
    {value: 'motion_control', label: '动作控制'},
    {value: 'temporal_keyframes', label: '时序关键帧'},
];

const parseState = (value: string): Record<string, string> => value.split('\n').reduce<Record<string, string>>((result, line) => {
    const [key, ...rest] = line.split('=');
    const normalizedKey = key.trim();
    const normalizedValue = rest.join('=').trim();
    if (normalizedKey && normalizedValue) result[normalizedKey] = normalizedValue;
    return result;
}, {});
const formatState = (value?: Record<string, string>) => Object.entries(value || {}).map(([key, item]) => `${key}=${item}`).join('\n');

export function ShotSpecificationEditor({value, characterNames, disabled, onChange}: {
    value?: ShotSpecification | null;
    characterNames: string[];
    disabled: boolean;
    onChange: (value: ShotSpecification | null) => void;
}) {
    const spec = value || {};
    const patch = (changes: Partial<ShotSpecification>) => onChange({...spec, ...changes});
    const statePatch = (name: string, changes: Partial<ShotCharacterState>) => {
        const states = spec.character_states || [];
        const existing = states.find(state => state.character_name === name);
        patch({character_states: [
            ...states.filter(state => state.character_name !== name),
            {...existing, character_name: name, ...changes},
        ]});
    };
    const assetPatch = (index: number, changes: Partial<ShotContinuityAsset>) => patch({continuity_assets: (spec.continuity_assets || []).map((asset, assetIndex) => assetIndex === index ? {...asset, ...changes} : asset)});
    const addAsset = () => patch({continuity_assets: [...(spec.continuity_assets || []), {asset_id: '', kind: 'prop', inherits_previous: true}]});
    const intensity = (field: 'camera_intensity' | 'action_intensity', label: string) => <label>{label}
        <select value={spec[field] || ''} onChange={event => patch({[field]: event.target.value as ShotIntensity || null})}>
            <option value="">自动规划</option><option value="low">轻</option><option value="medium">中</option><option value="high">强</option>
        </select>
    </label>;
    return <fieldset disabled={disabled} className="wb-shot-spec">
        <legend>镜头规格</legend>
        <div className="wb-shot-spec-fields">
            <label>剧情目的<textarea maxLength={500} value={spec.purpose || ''} onChange={event => patch({purpose: event.target.value})}/></label>
            <label>情绪<input maxLength={200} value={spec.emotion || ''} onChange={event => patch({emotion: event.target.value})}/></label>
            <label>镜头角色<select value={spec.shot_role || ''} onChange={event => patch({shot_role: (event.target.value || null) as ShotRole | null})}>
                <option value="">自动判定</option><option value="establishing">建立镜头</option><option value="dialogue_reaction">对白表演</option><option value="emotion_reaction">情绪反应</option><option value="action">动作镜头</option><option value="prop_interaction">道具交互</option>
            </select></label>
            <label>目标时长（秒）<input type="number" min={0.1} max={120} step={0.1} value={spec.duration_seconds ?? ''} onChange={event => patch({duration_seconds: event.target.value === '' ? null : Number(event.target.value)})}/></label>
            <label>运镜<input maxLength={500} value={spec.camera_movement || ''} onChange={event => patch({camera_movement: event.target.value})}/></label>
            {intensity('camera_intensity', '运镜强度')}
            {intensity('action_intensity', '人物运动强度')}
            <label>表演强度（1–5）<input type="number" min={1} max={5} step={1} value={spec.performance_intensity ?? ''} onChange={event => patch({performance_intensity: event.target.value === '' ? null : Number(event.target.value)})}/></label>
            <label>动作驱动视频路径<input maxLength={1000} placeholder="D:\\assets\\motion\\walk.mp4" value={spec.motion_reference_video || ''} onChange={event => patch({motion_reference_video: event.target.value})}/></label>
            <label>表演驱动音频路径<input maxLength={1000} placeholder="D:\\assets\\audio\\performance.wav" value={spec.performance_reference_audio || ''} onChange={event => patch({performance_reference_audio: event.target.value})}/></label>
            <fieldset className="wb-shot-capabilities"><legend>必需模型能力</legend>{capabilityOptions.map(option => <label className="wb-check" key={option.value}><input type="checkbox" checked={(spec.required_engine_capabilities || []).includes(option.value)} onChange={event => patch({required_engine_capabilities: event.target.checked ? [...(spec.required_engine_capabilities || []), option.value] : (spec.required_engine_capabilities || []).filter(value => value !== option.value)})}/>{option.label}</label>)}</fieldset>
            <label>连续性约束<textarea maxLength={30000} value={(spec.continuity_constraints || []).join('\n')} onChange={event => patch({continuity_constraints: event.target.value.split('\n')})}/></label>
        </div>
        {characterNames.map(name => {
            const state = spec.character_states?.find(item => item.character_name === name) || {character_name: name};
            return <div className="wb-shot-character" key={name}>
                <h4>{name}</h4>
                <div className="wb-shot-spec-fields">
                    <label>角色情绪<input maxLength={200} value={state.emotion || ''} onChange={event => statePatch(name, {emotion: event.target.value})}/></label>
                    <label>人物动作<input maxLength={500} value={state.action || ''} onChange={event => statePatch(name, {action: event.target.value})}/></label>
                    <label>起始状态<textarea maxLength={500} value={state.start_state || ''} onChange={event => statePatch(name, {start_state: event.target.value})}/></label>
                    <label>结束状态<textarea maxLength={500} value={state.end_state || ''} onChange={event => statePatch(name, {end_state: event.target.value})}/></label>
                </div>
            </div>;
        })}
        <section className="wb-shot-assets" aria-label="跨镜头资产状态">
            <div className="wb-row wb-between"><h4>跨镜头资产状态</h4><button type="button" className="wb-icon" title="添加连续性资产" aria-label="添加连续性资产" onClick={addAsset}><Plus size={17}/></button></div>
            {(spec.continuity_assets || []).map((asset, index) => <div className="wb-shot-character" key={`${asset.asset_id}-${index}`}>
                <div className="wb-row wb-between"><strong>资产 {index + 1}</strong><button type="button" className="wb-icon" title="删除连续性资产" aria-label="删除连续性资产" onClick={() => patch({continuity_assets: (spec.continuity_assets || []).filter((_, assetIndex) => assetIndex !== index)})}><Trash2 size={16}/></button></div>
                <div className="wb-shot-spec-fields">
                    <label>资产 ID<input maxLength={100} placeholder="prop:knife" value={asset.asset_id} onChange={event => assetPatch(index, {asset_id: event.target.value})}/></label>
                    <label>类型<select value={asset.kind || 'other'} onChange={event => assetPatch(index, {kind: event.target.value as ContinuityAssetKind})}><option value="prop">道具</option><option value="wardrobe">服装</option><option value="injury">伤势</option><option value="environment">环境</option><option value="blocking">站位</option><option value="other">其他</option></select></label>
                    <label>起始状态<textarea placeholder="hand=right\nwet=true" value={formatState(asset.start_state)} onChange={event => assetPatch(index, {start_state: parseState(event.target.value)})}/></label>
                    <label>结束状态<textarea placeholder="hand=right\nwet=true" value={formatState(asset.end_state)} onChange={event => assetPatch(index, {end_state: parseState(event.target.value)})}/></label>
                    <label className="wb-check"><input type="checkbox" checked={asset.inherits_previous !== false} onChange={event => assetPatch(index, {inherits_previous: event.target.checked})}/>继承上一镜头</label>
                    <label>状态变化说明<textarea maxLength={500} value={asset.transition_note || ''} onChange={event => assetPatch(index, {transition_note: event.target.value})}/></label>
                </div>
            </div>)}
        </section>
        <button type="button" className="wb-icon" title="清空镜头规格" aria-label="清空镜头规格" onClick={() => onChange(null)}><RotateCcw size={17}/></button>
    </fieldset>;
}

export function ShotSpecificationSummary({value}: {value?: ShotSpecification | null}) {
    if (!value) return null;
    const intensity = {low: '轻', medium: '中', high: '强'};
    return <details className="wb-shot-spec-summary">
        <summary>镜头规格{value.duration_seconds ? ` · ${value.duration_seconds} 秒` : ''}</summary>
        {value.purpose && <p>剧情目的：{value.purpose}</p>}
        {value.emotion && <p>情绪：{value.emotion}</p>}
        {value.shot_role && <p>镜头角色：{value.shot_role}</p>}
        {!!value.required_engine_capabilities?.length && <p>必需能力：{value.required_engine_capabilities.join('、')}</p>}
        <p>运镜：{value.camera_movement || '自动规划'}{value.camera_intensity ? ` · ${intensity[value.camera_intensity]}` : ''}</p>
        {value.action_intensity && <p>人物运动：{intensity[value.action_intensity]}</p>}
        {value.performance_intensity && <p>表演强度：{value.performance_intensity}/5</p>}
        {value.motion_reference_video && <p>动作驱动：已绑定</p>}
        {value.performance_reference_audio && <p>表演音频：已绑定</p>}
        {!!value.continuity_constraints?.length && <ul>{value.continuity_constraints.map((text, index) => <li key={index}>{text}</li>)}</ul>}
        {value.continuity_assets?.map(asset => <div key={asset.asset_id}>
            <strong>{asset.asset_id} · {asset.kind || 'other'}</strong>
            {!!Object.keys(asset.start_state || {}).length && <p>起始：{formatState(asset.start_state).replace(/\n/g, '；')}</p>}
            {!!Object.keys(asset.end_state || {}).length && <p>结束：{formatState(asset.end_state).replace(/\n/g, '；')}</p>}
            {asset.transition_note && <p>变化：{asset.transition_note}</p>}
        </div>)}
        {value.character_states?.map(state => <div key={state.character_name}>
            <strong>{state.character_name}</strong>
            {state.emotion && <p>情绪：{state.emotion}</p>}
            {state.action && <p>动作：{state.action}</p>}
            {state.start_state && <p>起始：{state.start_state}</p>}
            {state.end_state && <p>结束：{state.end_state}</p>}
        </div>)}
    </details>;
}
