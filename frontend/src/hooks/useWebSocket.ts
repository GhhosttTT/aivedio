import { useEffect, useState, useRef } from 'react';

interface WebSocketMessage {
    type: 'progress' | 'completed' | 'error' | 'status' | 
          'script_generation_start' | 'script_generation_complete' | 'script_generation_error';
    task_id?: string;
    project_id?: number;
    scene_id?: number;
    progress?: number;
    current_step?: string;
    task_type?: 'image' | 'video' | 'audio' | 'subtitle';
    status?: 'pending' | 'processing' | 'completed' | 'failed';
    message?: string;
    error?: string;
    characters_count?: number;
    scenes_count?: number;
}

/**
 * WebSocket Hook - 实时通信
 * 
 * 注意：WebSocket URL 格式必须与后端路由匹配
 * 后端路由：/ws/progress/{project_id}
 */
export const useWebSocket = (projectId: string) => {
    const [messages, setMessages] = useState<WebSocketMessage[]>([]);
    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        // 使用环境变量或默认值
        const wsBaseUrl = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000';
        // 后端路由是 /ws/{project_id}，不是 /ws/progress/{project_id}
        const wsUrl = `${wsBaseUrl}/ws/${projectId}`;
        
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log('WebSocket 已连接:', wsUrl);
            setIsConnected(true);
        };

        ws.onmessage = (event) => {
            try {
                const message: WebSocketMessage = JSON.parse(event.data);
                setMessages(prev => [...prev, message]);
            } catch (error) {
                console.error('解析 WebSocket 消息失败:', error);
            }
        };

        ws.onerror = (error) => {
            console.error('WebSocket 错误:', error);
        };

        ws.onclose = (event) => {
            console.log('WebSocket 已断开:', event.code, event.reason);
            setIsConnected(false);
            
            // 如果是 403 或其他认证错误，清除 token 并跳转登录
            if (event.code === 1008 || event.code === 4003) {
                console.warn('WebSocket 认证失败，清除 token');
                localStorage.removeItem('auth_token');
                if (!window.location.pathname.includes('/login')) {
                    window.location.href = '/login';
                }
            }
        };

        return () => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.close();
            }
        };
    }, [projectId]);

    return { messages, isConnected };
};
