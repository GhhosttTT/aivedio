import axios from 'axios';
import type { Project } from '../types';

/**
 * API 客户端配置
 */
const apiClient = axios.create({
    baseURL: (import.meta as any).env?.VITE_API_BASE_URL || 'http://localhost:8000/api',
    timeout: 30000,
    headers: {
        'Content-Type': 'application/json'
    }
});

// 请求拦截器 - 添加认证 Token
apiClient.interceptors.request.use((config) => {
    const token = localStorage.getItem('auth_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// 响应拦截器 - 处理错误和 401/403
apiClient.interceptors.response.use(
    (response) => response.data,
    (error) => {
        // 处理 401 未授权或 403 禁止访问错误
        if (error.response?.status === 401 || error.response?.status === 403) {
            console.warn('Token 失效或权限不足，清除认证状态');
            localStorage.removeItem('auth_token');
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
        const response = await apiClient.post('/auth/login', { username, password });
        // 响应拦截器已经返回了 response.data，所以 response 就是数据本身
        return {
            access_token: (response as any).access_token,
            refresh_token: '',
            user: { id: 1, username: username }
        };
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
        });
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

export default apiClient;
