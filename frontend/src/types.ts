/**
 * 分镜类型
 */
export interface Scene {
    id: number;
    scene_number: number;
    location?: string | null;
    time_period?: string | null;
    characters?: string | null;
    character_name?: string | null;
    dialogue: string;
    visual_description: string;
    image_prompt?: string | null;
    duration?: number | null;
    image_path?: string | null;
    video_path?: string | null;
    audio_path?: string | null;
}

/**
 * 角色类型
 */
export interface Character {
    id: number;
    name: string;
    description?: string | null;
    appearance?: string | null;
    personality?: string | null;
}

/**
 * 项目类型
 */
export interface Project {
    id: number | string;
    name: string;
    description?: string | null;
    theme?: string | null;
    outline?: string | null;
    status: string;
    script?: string | null;
    created_at: string;
    updated_at: string;
    characters?: Character[];
    scenes?: Scene[];
    final_video_path?: string | null;
    total_scenes?: number;
}
