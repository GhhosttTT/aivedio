import { useEffect, useRef, useState } from 'react';
import { apiOrigin } from '../api/client';

export interface WebSocketMessage {
    type: string;
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
 * 后端路由：/ws/{project_id}
 */
export const useWebSocket = (projectId: string) => {
    const [messages, setMessages] = useState<WebSocketMessage[]>([]);
    const [latestMessage, setLatestMessage] = useState<WebSocketMessage | null>(null);
    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        if (!projectId) {
            setIsConnected(false);
            return;
        }
        const configuredWsBase = import.meta.env.VITE_WS_BASE_URL as string | undefined;
        const wsBaseUrl = (configuredWsBase || apiOrigin.replace(/^http/, 'ws')).replace(/\/+$/, '');
        const token = localStorage.getItem('auth_token');
        if (!token) {
            setIsConnected(false);
            return;
        }
        const wsUrl = `${wsBaseUrl}/ws/${projectId}?token=${encodeURIComponent(token)}`;
        let disposed = false;
        let reconnectTimer: number | undefined;
        let reconnectAttempt = 0;
        let socket: WebSocket | null = null;

        const scheduleReconnect = () => {
            if (disposed || reconnectTimer !== undefined) return;
            const delay = Math.min(30000, 1000 * (2 ** reconnectAttempt));
            reconnectAttempt = Math.min(reconnectAttempt + 1, 5);
            reconnectTimer = window.setTimeout(() => {
                reconnectTimer = undefined;
                connect();
            }, delay);
        };

        const connect = () => {
            if (disposed) return;
            socket = new WebSocket(wsUrl);
            wsRef.current = socket;

            socket.onopen = () => {
                setIsConnected(true);
                reconnectAttempt = 0;
            };

            socket.onmessage = (event) => {
                try {
                    const message: WebSocketMessage = JSON.parse(event.data);
                    setLatestMessage(message);
                    setMessages(prev => [...prev.slice(-49), message]);
                } catch {
                    // Ignore malformed server frames and keep the connection alive.
                }
            };

            socket.onerror = () => {
                // onclose performs the single reconnect path.
            };

            socket.onclose = (event) => {
                if (socket !== wsRef.current) return;
                setIsConnected(false);
                if (event.code === 1008 || event.code === 4003) {
                    localStorage.removeItem('auth_token');
                    if (!window.location.pathname.includes('/login')) window.location.href = '/login';
                    return;
                }
                scheduleReconnect();
            };
        };

        connect();
        return () => {
            disposed = true;
            if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
            reconnectTimer = undefined;
            if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) socket.close();
            if (wsRef.current === socket) wsRef.current = null;
        };
    }, [projectId]);

    return { messages, latestMessage, isConnected };
};
