import { useEffect, useState, useRef } from 'react';

interface WebSocketMessage {
    type: 'progress' | 'completed' | 'error' | 'status';
    task_id?: string;
    project_id?: number;
    scene_id?: number;
    progress?: number;
    current_step?: string;
    task_type?: 'image' | 'video' | 'audio' | 'subtitle';
    status?: 'pending' | 'processing' | 'completed' | 'failed';
    message?: string;
    error?: string;
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
        const wsUrl = `${wsBaseUrl}/ws/progress/${projectId}`;
        
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

        ws.onclose = () => {
            console.log('WebSocket 已断开');
            setIsConnected(false);
        };

        return () => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.close();
            }
        };
    }, [projectId]);

    return { messages, isConnected };
};
