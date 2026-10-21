import { beforeEach, describe, expect, it, vi } from 'vitest';

function installBrowserStubs() {
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => { storage.set(key, String(value)); },
        removeItem: (key: string) => { storage.delete(key); },
        clear: () => { storage.clear(); },
    });
    vi.stubGlobal('window', {
        location: {
            protocol: 'http:',
            hostname: 'localhost',
            href: 'http://localhost/projects',
            pathname: '/projects',
        },
    });
}

async function loadClient() {
    vi.resetModules();
    installBrowserStubs();
    const client = await import('../client');
    const store = await import('../../store/authStore');
    return { ...client, useAuthStore: store.useAuthStore };
}

function unauthorized(config: any) {
    const error: any = new Error('Unauthorized');
    error.config = config;
    error.isAxiosError = true;
    error.response = { status: 401, data: { detail: 'expired' }, headers: {}, config };
    return error;
}

describe('refresh interceptor', () => {
    beforeEach(() => {
        vi.unstubAllGlobals();
    });

    it('refreshes once for concurrent 401s and retries with the new token', async () => {
        const { apiClient, authApi, useAuthStore } = await loadClient();
        useAuthStore.getState().updateTokens('old-access', 'old-refresh');
        const refresh = vi.spyOn(authApi, 'refreshToken').mockResolvedValue({
            access_token: 'new-access',
            refresh_token: 'new-refresh',
        });
        apiClient.defaults.adapter = async (config: any) => {
            if (!String(config.headers?.Authorization || '').includes('new-access')) {
                throw unauthorized(config);
            }
            return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
        };

        const [first, second] = await Promise.all([
            apiClient.get('/projects'),
            apiClient.get('/projects'),
        ]);

        expect(first).toEqual({ ok: true });
        expect(second).toEqual({ ok: true });
        expect(refresh).toHaveBeenCalledTimes(1);
        expect(useAuthStore.getState().token).toBe('new-access');
    });

    it('logs out once when refresh fails', async () => {
        const { apiClient, authApi, useAuthStore } = await loadClient();
        useAuthStore.getState().updateTokens('old-access', 'old-refresh');
        vi.spyOn(authApi, 'refreshToken').mockRejectedValue(new Error('refresh failed'));
        apiClient.defaults.adapter = async (config: any) => {
            throw unauthorized(config);
        };

        const results = await Promise.allSettled([
            apiClient.get('/projects'),
            apiClient.get('/projects'),
        ]);

        expect(results.every((result) => result.status === 'rejected')).toBe(true);
        expect(useAuthStore.getState().isAuthenticated).toBe(false);
        expect((window.location as any).href).toBe('/login');
    });
});
