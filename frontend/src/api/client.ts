import axios from 'axios';
import { useAuthStore } from '../store/authStore';
export const apiBase = (import.meta as any).env?.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000/api`;
export const apiOrigin = new URL(apiBase, window.location.href).origin;
export const errorText = (error: any) => { const detail = error?.response?.data?.detail; return typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((x: any) => x.msg).join('; ') : error?.message || '请求失败'; };
import type { LocalizationJob, Project, SourceVideo } from '../types';

/**
 * API 客户端配置
 */
const apiClient = axios.create({
    baseURL: apiBase,
    timeout: 30000,
    headers: {
        'Content-Type': 'application/json'
    }
});

// 请求拦截器 - 添加认证 Token
apiClient.interceptors.request.use((config) => {
    const token = localStorage.getItem('auth_token');
    if (token && !config.headers.Authorization) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// 响应拦截器 - 处理错误和 401/403
apiClient.interceptors.response.use(
    (response) => response.data,
    (error) => {
        // 处理 401 未授权或 403 禁止访问错误
        if (error.response?.status === 401) {
            console.warn('Token 失效或权限不足，清除认证状态');
            useAuthStore.getState().logout();
            // 如果不在登录页，跳转到登录页
            if (!window.location.pathname.includes('/login')) {
                window.location.href = '/login';
            }
        }
        console.error('API 请求失败:', error);
        return Promise.reject(error);
    }
);

/**
 * 认证 API
 */
export const authApi = {
    /**
     * 用户登录
     */
    login: async (username: string, password: string): Promise<{ access_token: string; refresh_token: string; user: any }> => {
        const response = await apiClient.post<any, {access_token: string; refresh_token: string}>('/auth/login', { username, password });
        const user = await apiClient.get<any, {id: string; username: string}>('/auth/me', {headers: {Authorization: `Bearer ${response.access_token}`}});
        return {...response, user};
    },

    /**
     * 刷新 Token
     */
    refreshToken: async (): Promise<{ token: string }> => {
        return apiClient.post('/auth/refresh');
    },
};

/**
 * 项目 API
 */
export const projectApi = {
    latestTask: (id: number) => apiClient.get<any, ProductionTask | null>(`/projects/${id}/production-task`),
    reviews: (id: number) => apiClient.get<any, {reports: Record<string, any>}>(`/projects/${id}/generation-review`),
    updateScene: (id: number, scene: number, data: any) => apiClient.put(`/projects/${id}/scenes/${scene}`, data),
    mediaUrl: async (id: number, path: string) => { const data = await apiClient.get<any, {url: string}>(`/projects/${id}/media-url`, {params: {path}}); return new URL(data.url, apiOrigin).href; },
    /**
     * 获取项目列表
     */
    listProjects: async (params?: {
        status_filter?: string;
        page?: number;
        page_size?: number;
    }): Promise<{ total: number; page: number; page_size: number; projects: Project[] }> => {
        return apiClient.get('/projects', { params });
    },

    /**
     * 获取项目详情
     */
    getProject: async (id: number): Promise<Project> => {
        return apiClient.get(`/projects/${id}`);
    },

    /**
     * 创建项目
     */
    createProject: async (data: {
        name: string;
        description?: string;
        theme?: string;
        outline?: string;
    }): Promise<Project> => {
        return apiClient.post('/projects', data);
    },

    /**
     * 更新项目
     */
    updateProject: async (id: number, data: {
        name?: string;
        description?: string;
        theme?: string;
        outline?: string;
        status?: string;
    }): Promise<Project> => {
        return apiClient.put(`/projects/${id}`, data);
    },

    /**
     * 删除项目
     */
    deleteProject: async (id: number): Promise<{ message: string; detail: string }> => {
        return apiClient.delete(`/projects/${id}`);
    },

    /**
     * 生成剧本（设置10分钟超时，等待LLM完成）
     */
    generateScript: async (id: number, data?: {
        theme?: string;
        outline?: string;
        num_scenes?: number;
        num_characters?: number;
        style?: string;
    }): Promise<Project> => {
        return apiClient.post(`/projects/${id}/generate-script`, data || {}, {
            timeout: 900000  // 15分钟超时，等待LLM生成完成
        });
    },

    /**
     * 重新生成单个分镜
     */
    regenerateScene: async (
        id: number,
        sceneNumber: number
    ): Promise<Project> => {
        return apiClient.post(`/projects/${id}/regenerate-scene`, {
            scene_number: sceneNumber
        }, {timeout: 900000});
    },

    /**
     * 开始生产
     */
    startProduction: async (id: number): Promise<{
        task_id: string;
        project_id: number;
        status: string;
        progress: number;
        current_step: string;
        total_steps: number;
        created_at: string;
        updated_at: string;
        error_message?: string;
    }> => {
        return apiClient.post(`/projects/${id}/produce`);
    },

    /**
     * 重新生成图像（不重新生成剧本）
     */
    regenerateImages: async (id: number): Promise<{
        task_id: string;
        project_id: number;
        status: string;
        progress: number;
        current_step: string;
        total_steps: number;
        created_at: string;
        updated_at: string;
        error_message?: string;
    }> => {
        return apiClient.post(`/projects/${id}/regenerate-images`);
    },
};

/**
 * 任务 API
 */
export const taskApi = {
    /**
     * 获取任务状态
     */
    getTaskStatus: async (taskId: string): Promise<{
        task_id: string;
        status: string;
        progress: number;
        current_step: string;
        result?: any;
        error?: string;
    }> => {
        return apiClient.get(`/tasks/${taskId}/status`);
    },

    /**
     * 取消任务
     */
    cancelTask: async (taskId: string): Promise<{ message: string; detail: string }> => {
        return apiClient.post(`/tasks/${taskId}/cancel`);
    },

    /**
     * 重试任务
     */
    retryTask: async (taskId: string): Promise<{ message: string; detail: string }> => {
        return apiClient.post(`/tasks/${taskId}/retry`);
    },
};

export const localizationApi = {
    uploadSourceVideo: async (projectId: number, file: File): Promise<SourceVideo> => {
        const formData = new FormData();
        formData.append('file', file);
        return apiClient.post(`/localization/projects/${projectId}/source-videos`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
            timeout: 300000,
        });
    },

    listSourceVideos: async (projectId: number): Promise<SourceVideo[]> => {
        return apiClient.get(`/localization/projects/${projectId}/source-videos`);
    },

    listProjectJobs: async (projectId: number): Promise<LocalizationJob[]> => {
        return apiClient.get(`/localization/projects/${projectId}/jobs`);
    },

    createJob: async (data: {
        source_video_id: number;
        target_languages: string[];
        auto_start?: boolean;
        run_inline?: boolean;
    }): Promise<LocalizationJob> => {
        return apiClient.post('/localization/jobs', data, { timeout: 900000 });
    },

    getJob: async (jobId: number): Promise<LocalizationJob> => {
        return apiClient.get(`/localization/jobs/${jobId}`);
    },
};

export default apiClient;


export interface ProductionTask { task_id: number; celery_task_id: string; project_id: number; status: string; progress: number; current_step: number; total_steps: number; error_message?: string; live_step?: {stage: string; scene_id?: number}; }
