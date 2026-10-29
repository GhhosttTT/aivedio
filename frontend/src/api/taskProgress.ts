import type { ProductionTask } from './client';
import type { WebSocketMessage } from '../hooks/useWebSocket';

/** Match lifecycle Celery ids and provider events carrying the database id. */
export function applyTaskProgress(current: ProductionTask | null, message: WebSocketMessage): ProductionTask | null {
    if (!current || (message.task_id && message.task_id !== current.celery_task_id
        && message.task_id !== String(current.task_id))) return current;
    const progress = typeof message.progress === 'number' && Number.isFinite(message.progress)
        ? Math.max(0, Math.min(100, message.progress <= 1 ? message.progress * 100 : message.progress))
        : current.progress;
    return {
        ...current,
        status: message.status || current.status,
        progress,
        ...(typeof message.current_step === 'number' ? {current_step: message.current_step} : {}),
        ...(typeof message.provider_progress === 'number' ? {provider_progress: message.provider_progress} : {}),
        ...(message.provider_stage ? {provider_stage: message.provider_stage} : {}),
        ...(message.provider_task_id ? {provider_task_id: message.provider_task_id} : {}),
        ...(message.provider_status ? {provider_status: message.provider_status} : {}),
        ...(message.provider_error ? {provider_error: message.provider_error} : {}),
    };
}
