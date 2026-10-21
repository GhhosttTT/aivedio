import { describe, expect, it, vi } from 'vitest';
import { createSingleFlight } from '../singleFlight';

describe('createSingleFlight', () => {
    it('shares one in-flight task between concurrent callers', async () => {
        let resolveTask!: (value: string) => void;
        const task = vi.fn(() => new Promise<string>((resolve) => { resolveTask = resolve; }));
        const run = createSingleFlight(task);

        const first = run();
        const second = run();
        expect(task).toHaveBeenCalledTimes(1);

        resolveTask('token');
        await expect(Promise.all([first, second])).resolves.toEqual(['token', 'token']);
    });

    it('starts a new task after the previous one settles', async () => {
        const task = vi.fn().mockResolvedValueOnce('one').mockResolvedValueOnce('two');
        const run = createSingleFlight(task);

        expect(await run()).toBe('one');
        expect(await run()).toBe('two');
        expect(task).toHaveBeenCalledTimes(2);
    });

    it('clears the gate after a rejection so a retry is possible', async () => {
        const task = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce('ok');
        const run = createSingleFlight(task);

        await expect(run()).rejects.toThrow('boom');
        await expect(run()).resolves.toBe('ok');
    });
});
