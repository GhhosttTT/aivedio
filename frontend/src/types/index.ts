/**
 * 类型定义文件
 * 
 * 注意：所有类型定义必须与后端数据库模型完全匹配
 * 参考：src/database/models.py
 */

export type ProjectStatus = 
    | 'draft'              // 草稿
    | 'script_generated'   // 剧本已生成
    | 'in_production'      // 生产中（注意：后端是 in_production 不是 producing）
    | 'completed'          // 已完成
    | 'failed';            // 失败

export interface Character {
    id: number;
    project_id: number;
    name: string;
    description?: string;
    visual_description?: string;
    created_at: string;
}

export interface Scene {
    id: number;
    project_id: number;
    scene_number: number;
    character_name?: string;  // 允许为空，某些分镜可能没有角色
    dialogue?: string;  // 允许为空，某些分镜可能没有对话
    visual_description: string;
    description?: string;  // 别名，与 visual_description 相同
    image_prompt?: string;
    image_path?: string;
    video_path?: string;
    audio_path?: string;
    subtitle_path?: string;
    created_at: string;
}

export interface Project {
    id: number;
    name: string;
    description?: string;
    theme?: string;
    outline?: string;
    status: ProjectStatus;
    user_id: number;
    created_at: string;
    updated_at: string;
    error_message?: string;
    
    // 关联数据
    characters?: Character[];
    scenes?: Scene[];
    
    // 注意：final_video_path 不在数据库模型中，可能需要从 Task 中获取
    final_video_path?: string;
}

export interface User {
    id: number;
    username: string;
    email: string;
    is_active: number;
    created_at: string;
    updated_at: string;
}

export interface Task {
    id: number;
    project_id: number;
    celery_task_id: string;
    status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
    progress: number;
    total_steps: number;
    current_step: number;
    error_message?: string;
    retry_count: number;
    result_path?: string;
    created_at: string;
    updated_at: string;
}

export interface TaskStatus {
    task_id: string;
    status: string;
    progress: number;
    current_step: string;
    result?: any;
    error?: string;
}

export interface ProductionTask {
    task_id: string;
    project_id: number;
    status: string;
    progress: number;
    current_step: string;
    total_steps: number;
    created_at: string;
    updated_at: string;
    error_message?: string;
}
