const detailText = (value: any): string => {
    if (typeof value === 'string') return value;
    if (typeof value?.msg === 'string') return value.msg;
    if (typeof value?.message === 'string') return value.message;
    return '';
};

export const errorText = (error: any) => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        const parts = detail.map(detailText).filter(Boolean);
        return parts.length ? parts.join('; ') : '请求失败';
    }
    if (detail && typeof detail === 'object') {
        if (Array.isArray(detail.errors)) {
            const parts = detail.errors.map(detailText).filter(Boolean);
            if (parts.length) return parts.join('; ');
        }
        if (typeof detail.message === 'string') return detail.message;
        if (typeof detail.detail === 'string') return detail.detail;
        try {
            return JSON.stringify(detail);
        } catch {
            return '请求失败';
        }
    }
    return error?.message || '请求失败';
};
