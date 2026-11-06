export type ShotIntensity = 'low' | 'medium' | 'high';
export type ShotRole = 'establishing' | 'dialogue_reaction' | 'emotion_reaction' | 'action' | 'prop_interaction';
export type EngineCapability = 'identity_reference' | 'performance_control' | 'multi_character' | 'motion_control' | 'temporal_keyframes';

export interface ShotCharacterState {
    character_name: string;
    emotion?: string;
    action?: string;
    start_state?: string;
    end_state?: string;
}

export type ContinuityAssetKind = 'prop' | 'wardrobe' | 'injury' | 'environment' | 'blocking' | 'other';

export interface ShotContinuityAsset {
    asset_id: string;
    kind?: ContinuityAssetKind;
    start_state?: Record<string, string>;
    end_state?: Record<string, string>;
    inherits_previous?: boolean;
    transition_note?: string;
}

export interface ShotSpecification {
    purpose?: string;
    emotion?: string;
    shot_role?: ShotRole | null;
    required_engine_capabilities?: EngineCapability[];
    duration_seconds?: number | null;
    camera_movement?: string;
    camera_intensity?: ShotIntensity | null;
    action_intensity?: ShotIntensity | null;
    performance_intensity?: number | null;
    motion_reference_video?: string;
    performance_reference_audio?: string;
    continuity_constraints?: string[];
    character_states?: ShotCharacterState[];
    continuity_assets?: ShotContinuityAsset[];
}
