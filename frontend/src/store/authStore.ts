import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
    id: string;
    username: string;
    email?: string;
}

interface AuthState {
    user: User | null;
    token: string | null;
    refreshTokenValue: string | null;
    isAuthenticated: boolean;
    login: (token: string, user: User, refreshToken?: string) => void;
    updateTokens: (token: string, refreshToken?: string) => void;
    logout: () => void;
}

/**
 * 认证状态管理
 * 
 * 使用 Zustand 进行状态管理
 * 使用 persist 中间件持久化到 localStorage
 */
export const useAuthStore = create<AuthState>()(
    persist(
        (set) => ({
            user: null,
            token: null,
            refreshTokenValue: null,
            isAuthenticated: false,

            login: (token: string, user: User, refreshToken?: string) => {
                localStorage.setItem('auth_token', token);
                if (refreshToken) localStorage.setItem('refresh_token', refreshToken);
                set({ user, token, refreshTokenValue: refreshToken || null, isAuthenticated: true });
            },

            updateTokens: (token: string, refreshToken?: string) => {
                localStorage.setItem('auth_token', token);
                if (refreshToken) localStorage.setItem('refresh_token', refreshToken);
                set((state) => ({
                    token,
                    refreshTokenValue: refreshToken || state.refreshTokenValue,
                    isAuthenticated: true,
                }));
            },

            logout: () => {
                localStorage.removeItem('auth_token');
                localStorage.removeItem('refresh_token');
                set({ user: null, token: null, refreshTokenValue: null, isAuthenticated: false });
            },
        }),
        {
            name: 'auth-storage',
        }
    )
);
