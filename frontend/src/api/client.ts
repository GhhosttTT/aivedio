import axios from 'axios';
import type { Project } from '../types';

/**
 * API 客户端配置
 */
const apiClient = axios.create({
    baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
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

// 响应拦截器 - 处理错误
apiClient.interceptors.response.use(
    (response) => response.data,
    (error) => {
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
    login: async (username: string, password: string): Promise<{ token: string; user: any }> => {
        return apiClient.post('/auth/login', { username, password });
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
     * 生成剧本
     */
    generateScript: async (id: number, data?: {
        theme?: string;
        outline?: string;
    }): Promise<Project> => {
        return apiClient.post(`/projects/${id}/generate-script`, data || {});
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
