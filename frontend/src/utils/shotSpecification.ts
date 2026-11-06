import type { EngineCapability, ShotSpecification } from '../types/shotSpecification';

const engineCapabilities = new Set<EngineCapability>([
    'identity_reference', 'performance_control', 'multi_character', 'motion_control', 'temporal_keyframes',
]);

export function prepareShotSpecification(value: ShotSpecification | null | undefined, visible: string[]): ShotSpecification | null {
    if (!value) return null;
    if (value.duration_seconds != null && (!Number.isFinite(value.duration_seconds) || value.duration_seconds <= 0 || value.duration_seconds > 120)) {
        throw new Error('目标时长应大于 0 且不超过 120 秒');
    }
    if (value.performance_intensity != null && (!Number.isInteger(value.performance_intensity) || value.performance_intensity < 1 || value.performance_intensity > 5)) {
        throw new Error('表演强度应为 1–5 的整数');
    }
    const motionReference = (value.motion_reference_video || '').trim();
    const performanceAudio = (value.performance_reference_audio || '').trim();
    const requiredCapabilities = [...new Set(value.required_engine_capabilities || [])];
    if (requiredCapabilities.some(capability => !engineCapabilities.has(capability))) {
        throw new Error('镜头包含未知的本地模型能力要求');
    }
    if (motionReference.length > 1000 || performanceAudio.length > 1000) {
        throw new Error('驱动素材路径不能超过 1000 字符');
    }
    const constraints = (value.continuity_constraints || []).map(text => text.trim()).filter(Boolean);
    if (constraints.length > 30 || constraints.some(text => text.length > 1000)) {
        throw new Error('连续性约束最多 30 条，每条不超过 1000 字');
    }
    const assets = (value.continuity_assets || []).map(asset => ({
        ...asset,
        asset_id: asset.asset_id.trim(),
        start_state: Object.fromEntries(Object.entries(asset.start_state || {}).filter(([key, item]) => key.trim() && item.trim())),
        end_state: Object.fromEntries(Object.entries(asset.end_state || {}).filter(([key, item]) => key.trim() && item.trim())),
        transition_note: asset.transition_note?.trim() || '',
    }));
    if (assets.some(asset => !asset.asset_id) || new Set(assets.map(asset => asset.asset_id)).size !== assets.length) {
        throw new Error('每个跨镜头资产都需要唯一的资产 ID');
    }
    if (assets.some(asset => Object.keys(asset.start_state || {}).length > 12 || Object.keys(asset.end_state || {}).length > 12)) {
        throw new Error('每个资产的起始和结束状态最多各 12 项');
    }
    return {...value, continuity_constraints: constraints,
        ...(value.motion_reference_video !== undefined ? {motion_reference_video: motionReference} : {}),
        ...(value.performance_reference_audio !== undefined ? {performance_reference_audio: performanceAudio} : {}),
        ...(value.required_engine_capabilities !== undefined ? {required_engine_capabilities: requiredCapabilities} : {}),
        character_states: value.character_states?.filter(state => visible.includes(state.character_name)) || [],
        ...(value.continuity_assets !== undefined ? {continuity_assets: assets} : {}),
    };
}
