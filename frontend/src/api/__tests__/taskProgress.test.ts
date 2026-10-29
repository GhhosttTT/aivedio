import { describe, expect, it } from 'vitest';
import type { ProductionTask } from '../client';
import { applyTaskProgress } from '../taskProgress';

const task: ProductionTask = {
    task_id: 9, celery_task_id: 'new-run', project_id: 1, status: 'running',
    progress: 30, current_step: 3, total_steps: 10,
};

describe('task progress message ownership', () => {
    it('ignores old task cancellation and provider progress', () => {
        expect(applyTaskProgress(task, {
            type: 'status_update', task_id: 'old-run', status: 'cancelled',
            progress: 0, provider_task_id: 'old-paid-job',
        })).toBe(task);
    });

    it('applies matching task progress and remote provider metadata', () => {
        expect(applyTaskProgress(task, {
            type: 'progress_update', task_id: 'new-run', status: 'running',
            progress: 0.7, current_step: 7, provider_task_id: 'current-paid-job',
        })).toMatchObject({progress: 70, current_step: 7, provider_task_id: 'current-paid-job'});
        expect(applyTaskProgress(task, {
            type: 'progress_update', task_id: '9', provider_progress: 50,
            provider_task_id: 'current-paid-job',
        })).toMatchObject({provider_progress: 50, provider_task_id: 'current-paid-job'});
        expect(applyTaskProgress(task, {
            type: 'progress_update', task_id: '8', provider_progress: 99,
        })).toBe(task);
    });

    it('accepts current cancellation without inventing another task', () => {
        expect(applyTaskProgress(task, {
            type: 'status_update', task_id: 'new-run', status: 'cancelled',
        })?.status).toBe('cancelled');
        expect(applyTaskProgress(null, {type: 'status_update', task_id: 'new-run'})).toBeNull();
    });

    it('keeps legacy unscoped progress working and rejects non-finite progress', () => {
        expect(applyTaskProgress(task, {type: 'progress_update', progress: 0.4})?.progress).toBe(40);
        expect(applyTaskProgress(task, {type: 'progress_update', progress: Number.NaN})?.progress).toBe(30);
    });
});
