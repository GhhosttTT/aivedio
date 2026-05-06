import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
    Image, Video, Mic, FileText, Film, 
    CheckCircle, XCircle, Loader, Clock,
    AlertCircle, Play, X, RefreshCw
} from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';
import { taskApi, projectApi } from '../api/client';
import type { Project } from '../types';

interface ProductionProgressProps {
    project: Project;
    onReload: () => void;
}

interface TaskProgress {
    image: 'pending' | 'processing' | 'completed' | 'failed';
    video: 'pending' | 'processing' | 'completed' | 'failed';
    audio: 'pending' | 'processing' | 'completed' | 'failed';
    subtitle: 'pending' | 'processing' | 'completed' | 'failed';
}

/**
 * 生产进度监控组件
 * 
 * 功能：
 * - 实时显示生产进度
 * - WebSocket 接收进度更新
 * - 展示每个分镜的任务状态
 * - 支持取消和重试
 */
export const ProductionProgress: React.FC<ProductionProgressProps> = ({ project, onReload }) => {
    const [taskProgress, setTaskProgress] = useState<Record<number, TaskProgress>>({});
    const [overallProgress, setOverallProgress] = useState(0);
    const [currentPhase, setCurrentPhase] = useState('准备中');
    const [cancelling, setCancelling] = useState(false);
    const [taskId, setTaskId] = useState<string | null>(null);
    const [selectedImage, setSelectedImage] = useState<{url: string, sceneNumber: number} | null>(null);
    const [regenerating, setRegenerating] = useState(false);

    // WebSocket 连接
    const { messages, isConnected } = useWebSocket(String(project.id));

    // 根据项目状态初始化进度
    useEffect(() => {
        if (project.status === 'completed') {
            setOverallProgress(100);
            setCurrentPhase('已完成');
        } else if (project.status === 'failed') {
            setCurrentPhase('失败');
        } else if (project.status === 'in_production') {
            setCurrentPhase('制作中');
        }
        
        // 初始化每个分镜的任务状态（无论项目状态如何）
        const initialProgress: Record<number, TaskProgress> = {};
        project.scenes?.forEach(scene => {
            initialProgress[scene.scene_number] = {
                image: scene.image_path ? 'completed' : 'pending',
                video: scene.video_path ? 'completed' : 'pending',
                audio: scene.audio_path ? 'completed' : 'pending',
                subtitle: (scene as any).subtitle_path ? 'completed' : 'pending'
            } as TaskProgress;
        });
        setTaskProgress(initialProgress);
    }, [project.status, project.scenes]);

    // 处理 WebSocket 消息
    useEffect(() => {
        if (messages.length > 0) {
            const latestMessage = messages[messages.length - 1];
            
            if (latestMessage.type === 'progress') {
                setOverallProgress((latestMessage.progress ?? 0) * 100);
                setCurrentPhase(latestMessage.current_step || '处理中');
                
                if (latestMessage.scene_id && latestMessage.task_type) {
                    const sceneId = latestMessage.scene_id;
                    const taskType = latestMessage.task_type as keyof TaskProgress;
                    const status = latestMessage.status as TaskProgress[keyof TaskProgress];
                    
                    setTaskProgress(prev => ({
                        ...prev,
                        [sceneId]: {
                            ...prev[sceneId],
                            [taskType]: status
                        }
                    }));
                }
            } else if (latestMessage.type === 'completed') {
                setOverallProgress(100);
                setCurrentPhase('已完成');
                onReload();
            } else if (latestMessage.type === 'error') {
                setCurrentPhase('失败');
                onReload();
            }
            
            // 保存任务 ID
            if (latestMessage.task_id) {
                setTaskId(latestMessage.task_id);
            }
        }
    }, [messages, onReload]);

    const handleCancelTask = async () => {
        if (!taskId) return;
        
        setCancelling(true);
        try {
            await taskApi.cancelTask(taskId);
            onReload();
        } catch (error) {
            console.error('取消任务失败:', error);
            alert('取消任务失败，请重试');
        } finally {
            setCancelling(false);
        }
    };

    const handleRetryTask = async () => {
        if (!taskId) return;
        
        try {
            await taskApi.retryTask(taskId);
            onReload();
        } catch (error) {
            console.error('重试任务失败:', error);
            alert('重试任务失败，请重试');
        }
    };

    const handleRegenerateImages = async () => {
        if (!confirm('确定要重新生成图像吗？这将清除所有已生成的图像并重新开始。')) {
            return;
        }
        
        setRegenerating(true);
        try {
            await projectApi.regenerateImages(project.id);
            onReload();
            alert('✅ 重新生成任务已启动');
        } catch (error) {
            console.error('重新生成图像失败:', error);
            alert('❌ 重新生成图像失败，请重试');
        } finally {
            setRegenerating(false);
        }
    };

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'completed':
                return <CheckCircle className="text-emerald-400" size={20} />;
            case 'failed':
                return <XCircle className="text-red-400" size={20} />;
            case 'processing':
                return <Loader className="text-blue-400 animate-spin" size={20} />;
            default:
                return <Clock className="text-slate-500" size={20} />;
        }
    };

    const getTaskIcon = (taskType: string) => {
        switch (taskType) {
            case 'image':
                return <Image size={18} />;
            case 'video':
                return <Video size={18} />;
            case 'audio':
                return <Mic size={18} />;
            case 'subtitle':
                return <FileText size={18} />;
            default:
                return <Film size={18} />;
        }
    };

    if (project.status === 'draft' || project.status === 'script_generated') {
        return (
            <div className="bg-gradient-to-br from-slate-800/50 to-slate-900/50 backdrop-blur-sm rounded-2xl p-12 text-center border border-slate-700/50">
                <div className="w-20 h-20 bg-slate-800/50 rounded-full flex items-center justify-center mx-auto mb-6">
                    <Play className="text-slate-600" size={40} />
                </div>
                <h3 className="text-2xl font-bold text-slate-400 mb-2">
                    还未开始制作
                </h3>
                <p className="text-slate-500">
                    点击"开始制作"按钮启动生产流程
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-8">
            {/* 总体进度 */}
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-gradient-to-br from-slate-800/50 to-slate-900/50 backdrop-blur-sm rounded-2xl p-8 border border-slate-700/50"
            >
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h2 className="text-2xl font-bold text-white mb-2">
                            制作进度
                        </h2>
                        <p className="text-slate-400">
                            {currentPhase}
                        </p>
                    </div>

                    <div className="flex items-center gap-4">
                        {/* 重新制作按钮 */}
                        {(project.status === 'in_production' || project.status === 'failed' || project.status === 'completed') && (
                            <button
                                onClick={handleRegenerateImages}
                                disabled={regenerating}
                                className="px-4 py-2 bg-orange-500/10 hover:bg-orange-500/20 text-orange-400 rounded-lg flex items-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <RefreshCw size={16} className={regenerating ? 'animate-spin' : ''} />
                                <span>{regenerating ? '重新生成中...' : '重新制作'}</span>
                            </button>
                        )}

                        {/* 刷新按钮 */}
                        <button
                            onClick={onReload}
                            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-white flex items-center gap-2 transition-colors"
                        >
                            <RefreshCw size={16} />
                            <span>刷新</span>
                        </button>

                        {/* WebSocket 连接状态 */}
                        <div className="flex items-center gap-2">
                            <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-red-400'} animate-pulse`} />
                            <span className="text-sm text-slate-400">
                                {isConnected ? '实时连接' : '连接断开'}
                            </span>
                        </div>
                    </div>
                </div>

                {/* 进度条 */}
                <div className="relative h-4 bg-slate-900/50 rounded-full overflow-hidden mb-4">
                    <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${overallProgress}%` }}
                        transition={{ duration: 0.5, ease: 'easeOut' }}
                        className="absolute inset-y-0 left-0 bg-gradient-to-r from-purple-500 to-blue-500 rounded-full"
                    />
                    <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent animate-shimmer" />
                </div>

                <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-400">
                        {Math.round(overallProgress)}% 完成
                    </span>
                    {project.status === 'in_production' && taskId && (
                        <button
                            onClick={handleCancelTask}
                            disabled={cancelling}
                            className="px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50"
                        >
                            <X size={16} />
                            <span>{cancelling ? '取消中...' : '取消制作'}</span>
                        </button>
                    )}
                    {project.status === 'failed' && taskId && (
                        <button
                            onClick={handleRetryTask}
                            className="px-4 py-2 bg-purple-500/10 hover:bg-purple-500/20 text-purple-400 rounded-lg transition-colors flex items-center gap-2"
                        >
                            <Play size={16} />
                            <span>重试</span>
                        </button>
                    )}
                </div>
            </motion.div>

            {/* 分镜任务列表 */}
            {project.scenes && project.scenes.length > 0 && (
                <div>
                    <h3 className="text-xl font-bold text-white mb-6">
                        分镜任务详情
                    </h3>

                    <div className="space-y-4">
                        <AnimatePresence>
                            {project.scenes.map((scene, index) => {
                                const progress = taskProgress[scene.scene_number] || {
                                    image: 'pending',
                                    video: 'pending',
                                    audio: 'pending',
                                    subtitle: 'pending'
                                };

                                const tasks = [
                                    { type: 'image', label: '图像生成', status: progress.image },
                                    { type: 'video', label: '视频生成', status: progress.video },
                                    { type: 'audio', label: '配音生成', status: progress.audio },
                                    { type: 'subtitle', label: '字幕生成', status: progress.subtitle }
                                ];

                                return (
                                    <motion.div
                                        key={scene.id}
                                        initial={{ opacity: 0, x: -20 }}
                                        animate={{ opacity: 1, x: 0 }}
                                        transition={{ delay: index * 0.05 }}
                                        className="bg-gradient-to-br from-slate-800/80 to-slate-900/80 backdrop-blur-sm rounded-xl p-6 border border-slate-700/50"
                                    >
                                        <div className="flex items-start justify-between mb-4">
                                            <div>
                                                <h4 className="text-lg font-semibold text-white mb-1">
                                                    分镜 {scene.scene_number}
                                                </h4>
                                                <p className="text-sm text-slate-400 line-clamp-2">
                                                    {scene.visual_description}
                                                </p>
                                            </div>
                                        </div>

                                        {/* 任务状态网格 */}
                                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                            {tasks.map((task) => (
                                                <div
                                                    key={task.type}
                                                    onClick={() => {
                                                        if (task.type === 'image' && scene.image_path && task.status === 'completed') {
                                                            const imageUrl = `http://localhost:8000/${scene.image_path.replace(/\\/g, '/')}`;
                                                            setSelectedImage({ url: imageUrl, sceneNumber: scene.scene_number });
                                                        }
                                                    }}
                                                    className={`p-4 rounded-lg border transition-all cursor-pointer ${
                                                        task.status === 'completed'
                                                            ? 'bg-emerald-500/10 border-emerald-500/30 hover:bg-emerald-500/20'
                                                            : task.status === 'failed'
                                                            ? 'bg-red-500/10 border-red-500/30'
                                                            : task.status === 'processing'
                                                            ? 'bg-blue-500/10 border-blue-500/30'
                                                            : 'bg-slate-800/50 border-slate-700/50'
                                                    }`}
                                                >
                                                    <div className="flex items-center gap-2 mb-2">
                                                        {getTaskIcon(task.type)}
                                                        <span className="text-sm font-medium text-white">
                                                            {task.label}
                                                        </span>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        {getStatusIcon(task.status)}
                                                        <span className="text-xs text-slate-400">
                                                            {task.status === 'completed' && '已完成'}
                                                            {task.status === 'failed' && '失败'}
                                                            {task.status === 'processing' && '处理中'}
                                                            {task.status === 'pending' && '等待中'}
                                                        </span>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </motion.div>
                                );
                            })}
                        </AnimatePresence>
                    </div>
                </div>
            )}

            {/* 错误信息 */}
            {project.status === 'failed' && (project as any).error_message && (
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-red-500/10 border border-red-500/30 rounded-xl p-6"
                >
                    <div className="flex items-start gap-3">
                        <AlertCircle className="text-red-400 flex-shrink-0 mt-1" size={20} />
                        <div>
                            <h4 className="text-lg font-semibold text-red-400 mb-2">
                                制作失败
                            </h4>
                            <p className="text-red-300/80">
                                {(project as any).error_message}
                            </p>
                        </div>
                    </div>
                </motion.div>
            )}

            {/* 图片查看弹窗 */}
            {selectedImage && (
                <div 
                    className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-8"
                    onClick={() => setSelectedImage(null)}
                >
                    <div className="relative max-w-6xl max-h-full">
                        <button
                            onClick={() => setSelectedImage(null)}
                            className="absolute -top-12 right-0 text-white hover:text-slate-300 transition-colors"
                        >
                            <X size={32} />
                        </button>
                        <div className="bg-slate-900 rounded-lg overflow-hidden border border-slate-700">
                            <div className="p-4 border-b border-slate-700">
                                <h3 className="text-white font-semibold">
                                    分镜 {selectedImage.sceneNumber} - 生成图像
                                </h3>
                            </div>
                            <img
                                src={selectedImage.url}
                                alt={`分镜 ${selectedImage.sceneNumber}`}
                                className="max-w-full max-h-[80vh] object-contain"
                                onClick={(e) => e.stopPropagation()}
                            />
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
