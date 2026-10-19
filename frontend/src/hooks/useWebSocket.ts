import { useEffect, useRef, useState } from 'react';
import { apiOrigin, authApi } from '../api/client';
import { useAuthStore } from '../store/authStore';

export interface WebSocketMessage {
    type: string;
    task_id?: string;
    project_id?: number;
    scene_id?: number;
    progress?: number;
    current_step?: string | number;
    task_type?: 'image' | 'video' | 'audio' | 'subtitle';
    status?: 'pending' | 'processing' | 'running' | 'completed' | 'failed' | 'cancelled';
    message?: string;
    error?: string;
    characters_count?: number;
    scenes_count?: number;
    provider_progress?: number;
    provider_stage?: string;
    provider_task_id?: string;
    provider_status?: string;
    provider_error?: string;
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
        let disposed = false;
        let reconnectTimer: number | undefined;
        let reconnectAttempt = 0;
        let authRefreshAttempted = false;
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

        async function refreshAndReconnect() {
            if (disposed || authRefreshAttempted) {
                if (!disposed) {
                    useAuthStore.getState().logout();
                    if (!window.location.pathname.includes('/login')) window.location.href = '/login';
                }
                return;
            }
            authRefreshAttempted = true;
            try {
                const tokens = await authApi.refreshToken();
                if (disposed) return;
                useAuthStore.getState().updateTokens(tokens.access_token, tokens.refresh_token);
                reconnectAttempt = 0;
                connect();
            } catch {
                if (!disposed) {
                    useAuthStore.getState().logout();
                    if (!window.location.pathname.includes('/login')) window.location.href = '/login';
                }
            }
        }

        const connect = () => {
            if (disposed) return;
            const currentToken = localStorage.getItem('auth_token');
            if (!currentToken) {
                setIsConnected(false);
                return;
            }
            const currentSocket = new WebSocket(`${wsBaseUrl}/ws/${projectId}?token=${encodeURIComponent(currentToken)}`);
            socket = currentSocket;
            wsRef.current = currentSocket;

            currentSocket.onopen = () => {
                setIsConnected(true);
                reconnectAttempt = 0;
                authRefreshAttempted = false;
            };

            currentSocket.onmessage = (event) => {
                try {
                    const message: WebSocketMessage = JSON.parse(event.data);
                    setLatestMessage(message);
                    setMessages(prev => [...prev.slice(-49), message]);
                } catch {
                    // Ignore malformed server frames and keep the connection alive.
                }
            };

            currentSocket.onerror = () => {
                // onclose performs the single reconnect path.
            };

            currentSocket.onclose = (event) => {
                if (currentSocket !== wsRef.current) return;
                setIsConnected(false);
                if (event.code === 1008 || event.code === 4003) {
                    void refreshAndReconnect();
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
