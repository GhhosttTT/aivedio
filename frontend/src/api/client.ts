import axios from 'axios';
import { useAuthStore } from '../store/authStore';
export const apiBase = (import.meta as any).env?.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000/api`;
export const apiOrigin = new URL(apiBase, window.location.href).origin;
export const errorText = (error: any) => { const detail = error?.response?.data?.detail; return typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((x: any) => x.msg).join('; ') : error?.message || '请求失败'; };
import type { LocalizationJob, Project, SourceVideo } from '../types';

/**
 * API 客户端配置
 */
const apiClient = axios.create({
    baseURL: apiBase,
    timeout: 30000,
    headers: {
        'Content-Type': 'application/json'
    }
});

let refreshInFlight: Promise<{access_token: string; refresh_token: string}> | null = null;

// 请求拦截器 - 添加认证 Token
apiClient.interceptors.request.use((config) => {
    const token = localStorage.getItem('auth_token');
    if (token && !config.headers.Authorization) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// 响应拦截器 - 处理错误和 401/403
apiClient.interceptors.response.use(
    (response) => response.data,
    async (error) => {
        const originalRequest = error.config as (typeof error.config & {_authRetry?: boolean}) | undefined;
        const requestUrl = String(originalRequest?.url || '');
        if (
            error.response?.status === 401 &&
            originalRequest &&
            !originalRequest._authRetry &&
            !requestUrl.includes('/auth/login') &&
            !requestUrl.includes('/auth/refresh')
        ) {
            originalRequest._authRetry = true;
            try {
                if (!refreshInFlight) refreshInFlight = authApi.refreshToken();
                const tokens = await refreshInFlight;
                refreshInFlight = null;
                useAuthStore.getState().updateTokens(tokens.access_token, tokens.refresh_token);
                originalRequest.headers = originalRequest.headers || {};
                originalRequest.headers.Authorization = `Bearer ${tokens.access_token}`;
                return apiClient(originalRequest);
            } catch (refreshError) {
                refreshInFlight = null;
                useAuthStore.getState().logout();
                if (!window.location.pathname.includes('/login')) window.location.href = '/login';
                return Promise.reject(refreshError);
            }
        }
        if (error.response?.status === 401) {
            useAuthStore.getState().logout();
            if (!window.location.pathname.includes('/login')) window.location.href = '/login';
        }
        console.error('API 请求失败:', error);
        return Promise.reject(error);
    }
);

/**
 * 认证 API
 */
export const authApi = {
    /**
     * 用户登录
     */
    login: async (username: string, password: string): Promise<{ access_token: string; refresh_token: string; user: any }> => {
        const response = await apiClient.post<any, {access_token: string; refresh_token: string}>('/auth/login', { username, password });
        const user = await apiClient.get<any, {id: string; username: string}>('/auth/me', {headers: {Authorization: `Bearer ${response.access_token}`}});
        return {...response, user};
    },

    /**
     * 刷新 Token
     */
    refreshToken: async (): Promise<{ access_token: string; refresh_token: string }> => {
        const refreshToken = useAuthStore.getState().refreshTokenValue || localStorage.getItem('refresh_token');
        if (!refreshToken) throw new Error('缺少刷新令牌');
        const response = await axios.post<{ access_token: string; refresh_token: string }>(
            `${apiBase}/auth/refresh`,
            { refresh_token: refreshToken },
            { headers: { 'Content-Type': 'application/json' } },
        );
        return response.data;
    },
};

/**
 * 项目 API
 */
export const projectApi = {
    videoEnginePreflight: () => apiClient.get<any, VideoEnginePreflight>('/projects/video-engine/preflight'),
    latestTask: (id: number) => apiClient.get<any, ProductionTask | null>(`/projects/${id}/production-task`),
    reviews: (id: number) => apiClient.get<any, GenerationReviewResponse>(`/projects/${id}/generation-review`),
    humanReview: (id: number, data: {report_key: string; decision: 'approved' | 'rejected'; note?: string}) => apiClient.post<any, {decision: Record<string, any>}>(`/projects/${id}/human-review`, data),
    deliveryPackage: (id: number) => apiClient.post<any, {package_path: string; manifest_path: string; files?: Array<{path: string; size: number; sha256: string}>; cover?: {status?: string}}>(`/projects/${id}/delivery-package`),
    verifyDeliveryPackage: (id: number) => apiClient.get<any, {status: string; checked_files: number; errors: string[]}>(`/projects/${id}/delivery-package/verify`),
    topicBrief: (id: number) => apiClient.get<any, {status: string; missing: string[]; brief: Record<string, string>}>(`/projects/${id}/topic-brief`),
    updateTopicBrief: (id: number, data: Record<string, string>) => apiClient.put<any, Record<string, string>>(`/projects/${id}/topic-brief`, data),
    marketSignals: (id: number) => apiClient.get<any, {status: string; score: number; score_max: number; recommendations?: string[]; evidence?: {comparables?: Array<{title?: string}>; differentiation?: string; success_metric?: string; notes?: string}}>(`/projects/${id}/topic-brief/market-signals`),
    updateMarketSignals: (id: number, data: {comparables: Array<Record<string, string> | string>; differentiation?: string; success_metric?: string; notes?: string}) => apiClient.put(`/projects/${id}/topic-brief/market-signals`, data),
    uploadBgm: async (id: number, file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return apiClient.post<any, {project_id: number; bgm_path: string; filename: string; size: number}>(`/projects/${id}/bgm`, formData, {
            headers: {'Content-Type': 'multipart/form-data'},
            timeout: 300000,
        });
    },
    platformExport: (id: number, preset: string) => apiClient.post<any, {output_path: string; preset: string; label: string; width: number; height: number; fps: number; technical_metrics?: {status?: string}}>(`/projects/${id}/platform-export/${preset}`),
    qualityLoopPlan: (id: number, maxActions = 5, action?: string) => apiClient.get<any, QualityLoopPlanResponse>(`/projects/${id}/quality-loop/plan`, {params: {max_actions: maxActions, ...(action ? {action} : {})}}),
    runAutoRepairQueue: (id: number, data: {max_actions?: number; dry_run?: boolean; action?: string}) => apiClient.post<any, RepairQueueAutoRunResponse>(`/projects/${id}/repair-queue/auto`, data),
    productionReadiness: (id: number, includeEnginePreflight = true, providerOverride?: string, modelOverride?: string, requestModeOverride?: string, resolutionOverride?: string, outputFormatOverride?: string, durationOverride?: number | null) => apiClient.get<any, ProductionReadinessReport>(`/projects/${id}/production-readiness`, {params: {include_engine_preflight: includeEnginePreflight, ...(providerOverride ? {provider_override: providerOverride} : {}), ...(modelOverride ? {model_override: modelOverride} : {}), ...(requestModeOverride ? {request_mode_override: requestModeOverride} : {}), ...(resolutionOverride ? {resolution_override: resolutionOverride} : {}), ...(outputFormatOverride ? {output_format_override: outputFormatOverride} : {}), ...(durationOverride !== null && durationOverride !== undefined ? {duration_override: durationOverride} : {})}}),
    approveStoryRoom: (id: number, notes = '') => apiClient.post<any, {project_id: number; status: string; approval: Record<string, any>}>(`/projects/${id}/approve-story-room`, {notes}),
    freezeSpatialPlan: (id: number, notes = '') => apiClient.post<any, {project_id: number; status: string; asset_pack: Record<string, any>}>(`/projects/${id}/freeze-spatial-plan`, {notes}),
    freezeVisualStyle: (id: number, data?: {style_prompt?: string; negative_prompt?: string; notes?: string}) => apiClient.post<any, {project_id: number; status: string; asset_pack: Record<string, any>}>(`/projects/${id}/freeze-visual-style`, data || {}),
    freezeWorkflowProfile: (data?: {capabilities?: Record<string, any>; notes?: string}) => apiClient.post<any, {status: string; profile: Record<string, any>}>('/projects/workflow-profile/freeze', data || {}),
    compareSeedDanceBaseline: (id: number, data: {baseline_path: string; candidate_path?: string}) => apiClient.post<any, SeedDanceBaselineComparison>(`/projects/${id}/seed-dance-baseline`, data, {timeout: 300000}),
    uploadSeedDanceBaseline: (id: number, file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return apiClient.post<any, SeedDanceBaselineComparison>(`/projects/${id}/seed-dance-baseline/upload`, formData, {
            headers: {'Content-Type': 'multipart/form-data'},
            timeout: 300000,
        });
    },
    updateScene: (id: number, scene: number, data: any) => apiClient.put(`/projects/${id}/scenes/${scene}`, data),
    mediaUrl: async (id: number, path: string, download = false) => { const data = await apiClient.get<any, {url: string}>(`/projects/${id}/media-url`, {params: {path}}); const url = new URL(data.url, apiOrigin); if (download) url.searchParams.set('download', 'true'); return url.href; },
    /**
     * 获取项目列表
     */
    listProjects: async (params?: {
        status_filter?: string;
        page?: number;
        page_size?: number;
    }): Promise<{ total: number; page: number; page_size: number; projects: Project[] }> => {
        return apiClient.get('/projects', { params });
    },

    /**
     * 获取项目详情
     */
    getProject: async (id: number): Promise<Project> => {
        return apiClient.get(`/projects/${id}`);
    },

    /**
     * 创建项目
     */
    createProject: async (data: {
        name: string;
        description?: string;
        theme?: string;
        outline?: string;
    }): Promise<Project> => {
        return apiClient.post('/projects', data);
    },

    /**
     * 更新项目
     */
    updateProject: async (id: number, data: {
        name?: string;
        description?: string;
        theme?: string;
        outline?: string;
        status?: string;
    }): Promise<Project> => {
        return apiClient.put(`/projects/${id}`, data);
    },

    /**
     * 删除项目
     */
    deleteProject: async (id: number): Promise<{ message: string; detail: string }> => {
        return apiClient.delete(`/projects/${id}`);
    },

    /**
     * 生成剧本（设置10分钟超时，等待LLM完成）
     */
    generateScript: async (id: number, data?: {
        theme?: string;
        outline?: string;
        num_scenes?: number;
        num_characters?: number;
        style?: string;
    }): Promise<Project> => {
        return apiClient.post(`/projects/${id}/generate-script`, data || {}, {
            timeout: 900000  // 15分钟超时，等待LLM生成完成
        });
    },
    repairScript: async (id: number): Promise<Project> => apiClient.post(`/projects/${id}/repair-script`, {}, {
        timeout: 900000,
    }),

    /**
     * 重新生成单个分镜
     */
    regenerateScene: async (
        id: number,
        sceneNumber: number
    ): Promise<Project> => {
        return apiClient.post(`/projects/${id}/regenerate-scene`, {
            scene_number: sceneNumber
        }, {timeout: 900000});
    },

    /**
     * 开始生产
     */
    startProduction: async (id: number, options?: {
        provider?: string;
        request_mode?: string;
        multi_shot?: boolean;
        sequence_level_multi_shot?: boolean;
        native_audio?: boolean;
        draft?: boolean;
        draft_task_id?: string;
        model?: string;
        resolution?: string;
        output_format?: string;
        return_last_frame?: boolean;
        camera_fixed?: boolean;
        watermark?: boolean;
        duration_seconds?: number | null;
        add_bgm?: boolean;
        bgm_path?: string | null;
        bgm_volume?: number;
    }): Promise<{
        task_id: string;
        project_id: number;
        status: string;
        progress: number;
        current_step: string;
        total_steps: number;
        created_at: string;
        updated_at: string;
        error_message?: string;
    }> => {
        return apiClient.post(`/projects/${id}/produce`, options || {});
    },
    promoteDrafts: async (id: number): Promise<{
        task_id: string;
        project_id: number;
        status: string;
        progress: number;
        current_step: string;
        total_steps: number;
        created_at: string;
        updated_at: string;
        error_message?: string;
    }> => apiClient.post(`/projects/${id}/promote-drafts`),

    /**
     * 重新生成图像（不重新生成剧本）
     */
    regenerateImages: async (id: number): Promise<{
        task_id: string;
        project_id: number;
        status: string;
        progress: number;
        current_step: string;
        total_steps: number;
        created_at: string;
        updated_at: string;
        error_message?: string;
    }> => {
        return apiClient.post(`/projects/${id}/regenerate-images`);
    },

    repairScene: async (id: number, data: {scene_number: number; action: string}): Promise<{
        task_id: string;
        project_id: number;
        status: string;
        progress: number;
        current_step: string;
        total_steps: number;
        created_at: string;
        updated_at: string;
        error_message?: string;
    }> => {
        return apiClient.post(`/projects/${id}/repair-scene`, data);
    },
};

/**
 * 任务 API
 */
export const taskApi = {
    /**
     * 获取任务状态
     */
    getTaskStatus: async (taskId: string): Promise<{
        task_id: string;
        status: string;
        progress: number;
        current_step: string;
        result?: {output_path?: string; composition_review?: {status?: string; average?: number; technical_score?: number; error?: string}; composition_review_path?: string};
        error?: string;
        provider_progress?: number;
        provider_stage?: string;
        provider_state?: string;
        provider_task_id?: string;
        provider_request_submitted?: boolean;
        provider_status?: string;
        provider_error?: string;
        production_options?: ProductionTask['production_options'];
    }> => {
        return apiClient.get(`/tasks/${taskId}/status`);
    },

    /**
     * 取消任务
     */
    cancelTask: async (taskId: string): Promise<{ message: string; detail: string }> => {
        return apiClient.post(`/tasks/${taskId}/cancel`);
    },

    /**
     * 重试任务
     */
    retryTask: async (taskId: string): Promise<{ message: string; detail: string }> => {
        return apiClient.post(`/tasks/${taskId}/retry`);
    },
};

export const localizationApi = {
    uploadSourceVideo: async (projectId: number, file: File): Promise<SourceVideo> => {
        const formData = new FormData();
        formData.append('file', file);
        return apiClient.post(`/localization/projects/${projectId}/source-videos`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
            timeout: 300000,
        });
    },

    listSourceVideos: async (projectId: number): Promise<SourceVideo[]> => {
        return apiClient.get(`/localization/projects/${projectId}/source-videos`);
    },

    listProjectJobs: async (projectId: number): Promise<LocalizationJob[]> => {
        return apiClient.get(`/localization/projects/${projectId}/jobs`);
    },

    createJob: async (data: {
        source_video_id: number;
        target_languages: string[];
        auto_start?: boolean;
        run_inline?: boolean;
    }): Promise<LocalizationJob> => {
        return apiClient.post('/localization/jobs', data, { timeout: 900000 });
    },

    getJob: async (jobId: number): Promise<LocalizationJob> => {
        return apiClient.get(`/localization/jobs/${jobId}`);
    },
    quality: async (jobId: number): Promise<{report: any; human_review: {decision: string; note?: string}; review_history?: Array<{decision: string; note?: string; reviewed_by?: number; reviewed_at?: string}>}> => {
        return apiClient.get(`/localization/jobs/${jobId}/quality`);
    },
    qualityReview: async (jobId: number, data: {decision: 'approved' | 'rejected'; note?: string}) => {
        return apiClient.post(`/localization/jobs/${jobId}/quality-review`, data);
    },
};

export default apiClient;


export interface ProductionTask { task_id: number; celery_task_id: string; project_id: number; status: string; progress: number; current_step: number; total_steps: number; error_message?: string; result?: {output_path?: string; composition_review?: {status?: string; average?: number; technical_score?: number; error?: string}; composition_review_path?: string; sequence_evidence?: {boundary_status?: string; severe_transition_count?: number; geometry_mismatch_count?: number; segment_count?: number; report_path?: string}}; live_step?: {stage: string; scene_id?: number}; provider_progress?: number; provider_stage?: string; provider_state?: string; provider_task_id?: string; provider_request_submitted?: boolean; provider_status?: string; provider_error?: string; production_options?: {provider?: string; request_mode?: string; model?: string; resolution?: string; output_format?: string; duration_seconds?: number; native_audio?: boolean; multi_shot?: boolean}; }

export interface GenerationReviewSummary {
    status: 'ready' | 'blocked' | string;
    reports: Record<string, string | undefined>;
    stale_reports: string[];
    shot_complexity: {
        status?: string;
        needs_split: number;
        warn: number;
    };
    repair_queue?: {
        total: number;
        actions: Record<string, number>;
        items: Array<{
            priority?: string;
            stage?: string;
            action?: string;
            reason?: string;
            recommendation?: string;
            source_report?: string;
            scene_number?: number;
            candidate_index?: number;
        }>;
    };
    repair_execution_plan?: {
        auto?: Array<RepairExecutionPlanItem>;
        setup_required?: Array<RepairExecutionPlanItem>;
        manual?: Array<RepairExecutionPlanItem>;
        rerun_validation_commands?: string[];
    };
    sequence_boundary?: {status?: string; reports?: number};
    action_items: string[];
    human_final_review_required?: boolean;
    human_final_review_status?: string | null;
    human_approved_reports?: string[];
    repair_cycles?: Array<{cycle_id: string; status: string; created_at: string; submitted_count: number; skipped_count: number}>;
}

export interface SeedDanceBaselineComparison {
    kind?: 'seed_dance_baseline_comparison' | string;
    status: 'passed' | 'needs_review' | string;
    score?: number;
    min_score?: number;
    candidate_video_path?: string;
    baseline_video_path?: string;
    uploaded_baseline_path?: string;
    candidate_sha256?: string;
    baseline_sha256?: string;
    contact_sheet_path?: string | null;
    gates?: Record<string, boolean>;
    differences?: Record<string, number | boolean | string | null>;
}

export interface RepairExecutionPlanItem {
    action?: string;
    stage?: string;
    scene_number?: number;
    reason?: string;
    recommendation?: string;
    rerun_strategy?: string;
    parameter_hints?: Record<string, string | number | boolean>;
}

export interface QualityLoopPlan {
    status: 'can_auto_repair' | 'setup_required' | 'manual_review_required' | 'ready' | 'blocked' | string;
    selected: Array<GenerationRepairQueueItem>;
    skipped: Array<GenerationRepairQueueItem & {reason?: string}>;
    setup_required: Array<GenerationRepairQueueItem>;
    manual_actions: Array<GenerationRepairQueueItem>;
    next_step: string;
}

export interface QualityLoopPlanResponse {
    project_id: number;
    summary_status?: string;
    quality_scorecard?: QualityScorecard;
    plan: QualityLoopPlan;
}

export interface QualityScorecardDimension {
    dimension: string;
    label?: string;
    status?: string;
    score?: number;
    issue_count?: number;
    scenes?: number[];
    evidence?: string[];
}

export interface QualityScorecard {
    status?: string;
    production_score?: number;
    repair_queue_total?: number;
    weakest_dimensions?: QualityScorecardDimension[];
    next_focus?: {
        dimension?: string;
        label?: string;
        suggested_action?: string;
        scenes?: number[];
        evidence?: string[];
    } | null;
}

export interface RepairQueueAutoRunResponse {
    project_id: number;
    status: string;
    dry_run: boolean;
    submitted: Array<GenerationRepairQueueItem & {task_id?: string; status?: string}>;
    skipped: Array<GenerationRepairQueueItem & {reason?: string}>;
    considered: Array<GenerationRepairQueueItem>;
    cycle_id?: string;
}

export interface GenerationRepairQueueItem {
    priority?: string;
    stage?: string;
    action?: string;
    reason?: string;
    recommendation?: string;
    source_report?: string;
    scene_number?: number;
    candidate_index?: number;
}

export interface GenerationReviewResponse {
    project_id: number;
    reports: Record<string, any>;
    summary?: GenerationReviewSummary;
    human_decisions?: Record<string, any>;
}

export interface VideoEnginePreflight {
    status: 'ready_for_production_video_test' | 'production_not_ready' | string;
    engine: string;
    workflow: {
        status: string;
        workflow_path?: string;
        checks?: Record<string, any>;
        placeholders?: string[];
        likely_output_nodes?: Array<{node_id: string; class_type: string}>;
        error?: string;
    };
    requirements: string[];
    action_items: string[];
    provider?: {
        provider?: string;
        status?: string;
        message?: string;
        configuration?: Record<string, string>;
        checks?: Record<string, any>;
        capabilities?: Record<string, boolean | number | string | string[] | Record<string, number> | Array<Record<string, string>>>;
        action_items?: string[];
        warnings?: string[];
    };
    warnings?: string[];
}

export interface ProductionReadinessIssue {
    code: string;
    severity: 'blocker' | 'warning' | string;
    message: string;
}

export interface ProductionReadinessReport {
    project_id: number;
    status: 'ready' | 'needs_review' | 'blocked' | string;
    delivery_evidence?: {
        status: 'ready' | 'missing' | 'invalid' | string;
        path?: string;
        task_record_id?: number | null;
        captured_at?: string | null;
    };
    blockers: ProductionReadinessIssue[];
    warnings: ProductionReadinessIssue[];
    repair_actions?: Array<{
        action: string;
        stage: string;
        execution: string;
        scope?: 'project' | 'global_sample' | string;
        severity?: string;
        source_report: string;
        reason: string;
        recommendation: string;
        instructions?: string;
    }>;
    checks: {
        script?: {
            scene_count: number;
            minimum_production_scenes: number;
            contiguous_scene_numbers: boolean;
            draft_fallback_enabled: boolean;
            has_script_json: boolean;
        };
        story_rhythm?: {
            status: string;
            score: number;
            missing: string[];
            signals?: Record<string, any>;
        };
        story_room?: {
            status: string;
            score: number;
            missing: string[];
            rewrite_actions?: string[];
            signals?: Record<string, any>;
            scene_notes?: Array<{scene_number: number; reason: string; signals?: string[]}>;
            approval?: {
                status: 'approved' | 'missing' | 'stale' | string;
                input_hash?: string;
                approved_hash?: string | null;
            };
        };
        episode_rhythm?: {
            status: string;
            scene_count: number;
            total_duration_seconds: number;
            hook_status?: string;
            hook_latency_seconds?: number | null;
            issues?: Array<{code: string; severity: string; scene_number: number; message: string}>;
        };
        topic_brief?: {
            status: string;
            missing: string[];
            brief?: Record<string, string>;
            score?: number;
            score_max?: number;
            score_status?: string;
            score_missing?: string[];
            recommendations?: string[];
            market_fit?: {
                status: string;
                score: number;
                score_max: number;
                recommendations?: string[];
            };
        };
        content_safety?: {
            status: string;
            message?: string;
            hit_count?: number;
            categories?: string[];
            uncovered_categories?: string[];
            hits?: Array<{scene_number?: number; field?: string; category?: string; terms?: string[]}>
        };
        visual_format?: {
            status: string;
            width: number;
            height: number;
            aspect_ratio: string;
            target: string;
            recommended?: {width: number; height: number};
        };
        characters?: {
            total_characters: number;
            visible_character_names: string[];
            missing_records: string[];
            missing_identity_specs: string[];
            incomplete_identity_specs: Array<{name: string; missing_fields: string[]}>;
            missing_references: string[];
            missing_appearance: string[];
            missing_voice_profiles: string[];
            distinctiveness?: Record<string, any>;
            characters: Array<{id: number; name: string; has_appearance: boolean; has_identity_spec: boolean; missing_identity_fields: string[]; reference_count: number; voice_binding?: string}>;
        };
        shot_complexity?: {
            status: string;
            summary: {total: number; needs_split: number; warn: number};
        };
        spatial_continuity?: {
            status: string;
            summary: {total: number; weak: number};
            asset_pack?: {
                status?: string;
                stale?: string[];
                scene_stale?: Array<Record<string, unknown>>;
                control_gaps?: Array<{scene_number: number; control_type?: string; character?: string; missing: string[]}>;
            };
            scenes: Array<{
                scene_number: number;
                status: string;
                shot_scale?: string;
                camera_angle?: string;
                character_positions: Record<string, string>;
                prop_focus?: string;
            }>;
        };
        visual_style?: {
            status: string;
            stale?: string[];
            path?: string;
        };
        reviewer?: {
            backend: string;
            configured: boolean;
            image_review_required: boolean;
            video_review_required: boolean;
        };
        workflow_profile?: {
            status: string;
            missing?: string[];
            stale?: string[];
            missing_capabilities?: string[];
            quality_budget_issues?: string[];
            image_spatial_contract?: {
                groups?: Record<string, boolean>;
                missing_groups?: string[];
                placeholders?: string[];
            };
            video_quality_contract?: {
                groups?: Record<string, boolean>;
                missing_groups?: string[];
                placeholders?: string[];
            };
            minimum_quality_budget?: Record<string, unknown>;
            profile?: {
                capabilities?: Record<string, boolean | number | string | string[] | Record<string, number> | Array<Record<string, string>>>;
                capability_evidence?: Record<string, {
                    present?: boolean;
                    matched_nodes?: string[];
                    requirement?: string;
                }>;
                quality_gates?: Record<string, unknown>;
            };
        };
        sample_validation?: {
            status: string;
            path: string;
            required_status: string;
            quality_scorecard?: QualityScorecard;
            checks?: {
                render_profile?: Record<string, unknown>;
                render_profile_passed?: boolean;
                render_workflow_parameters_passed?: boolean;
                image_review_present?: boolean;
                image_review_covers_rendered_cases?: boolean;
                image_review_missing_case_ids?: string[];
                image_review_passed?: boolean;
                video_review_passed?: boolean;
                video_identity_gate_passed?: boolean;
                video_temporal_gate_passed?: boolean;
                video_aesthetic_gate_passed?: boolean;
                baseline_contact_sheet_present?: boolean;
                baseline_comparison_passed?: boolean;
                manual_review_covers_rendered_cases?: boolean;
                manual_review_missing_case_ids?: string[];
                manual_clip_review_present?: boolean;
                manual_clip_score?: number | null;
                manual_clip_review_passed?: boolean;
                manual_blocking_issues?: Array<Record<string, unknown>>;
                manual_blocking_issues_passed?: boolean;
                repair_queue_empty?: boolean;
                manual_review_passed?: boolean;
                quality_scorecard_production_score?: number | null;
                quality_scorecard_next_focus?: QualityScorecard['next_focus'];
            };
            action_items?: string[];
        };
        video_engine?: VideoEnginePreflight;
        [key: string]: any;
    };
    action_items: string[];
}
