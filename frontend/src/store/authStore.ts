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
    isAuthenticated: boolean;
    login: (token: string, user: User) => void;
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
            isAuthenticated: false,

            login: (token: string, user: User) => {
                localStorage.setItem('auth_token', token);
                set({ user, token, isAuthenticated: true });
            },

            logout: () => {
                localStorage.removeItem('auth_token');
                set({ user: null, token: null, isAuthenticated: false });
            },
        }),
        {
            name: 'auth-storage',
        }
    )
);
