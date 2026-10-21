import { describe, expect, it } from 'vitest';
import { errorText } from '../errorText';

describe('errorText', () => {
    it('returns a string detail', () => {
        expect(errorText({ response: { data: { detail: '项目不存在' } } })).toBe('项目不存在');
    });

    it('joins FastAPI validation details', () => {
        const error = {
            response: {
                data: {
                    detail: [{ msg: '用户名不能为空' }, { msg: '密码太短' }],
                },
            },
        };
        expect(errorText(error)).toBe('用户名不能为空; 密码太短');
    });

    it('joins object detail errors', () => {
        const error = {
            response: {
                data: {
                    detail: { status: 'failed', errors: ['SHA-256 mismatch: a', 'Size mismatch: b'] },
                },
            },
        };
        expect(errorText(error)).toBe('SHA-256 mismatch: a; Size mismatch: b');
    });

    it('uses object detail message or detail', () => {
        expect(errorText({ response: { data: { detail: { message: '网关失败' } } } })).toBe('网关失败');
        expect(errorText({ response: { data: { detail: { detail: '内部错误' } } } })).toBe('内部错误');
    });

    it('falls back to the axios message and finally a Chinese default', () => {
        expect(errorText({ message: 'Network Error' })).toBe('Network Error');
        expect(errorText({})).toBe('请求失败');
    });
});
