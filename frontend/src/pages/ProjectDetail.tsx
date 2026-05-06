import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, RefreshCw, Download, Sparkles } from 'lucide-react';
import { projectApi } from '../api/client';
import { ScriptPreview } from '../components/ScriptPreview';
import { ProductionProgress } from '../components/ProductionProgress';
import { useWebSocket } from '../hooks/useWebSocket';
import type { Project } from '../types';

/**
 * 项目详情页面
 * 
 * 功能：
 * - 查看项目信息
 * - 预览和编辑剧本
 * - 启动生产流程
 * - 监控生产进度
 * - 下载最终视频
 */
export const ProjectDetail: React.FC = () => {
    const { id } = useParams<{ id: string }>();
    const navigate = useNavigate();
    const [project, setProject] = useState<Project | null>(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState<'script' | 'production'>('script');
    const [generating, setGenerating] = useState(false);
    const [starting, setStarting] = useState(false);
    
    // WebSocket 连接
    const { messages } = useWebSocket(id || '');

    useEffect(() => {
        if (id) {
            loadProject(Number(id));
        }
    }, [id]);
    
    // 监听 WebSocket 消息
    useEffect(() => {
        if (!messages || messages.length === 0) return;
        
        const lastMessage = messages[messages.length - 1];
        console.log('收到 WebSocket 消息:', lastMessage);
        
        // 处理剧本生成相关消息
        if (lastMessage.type === 'script_generation_start') {
            setGenerating(true);
            console.log('开始生成剧本');
        } else if (lastMessage.type === 'script_generation_complete') {
            setGenerating(false);
            console.log('剧本生成完成');
            // 重新加载项目数据
            if (id) {
                loadProject(Number(id));
            }
            alert(`✅ ${lastMessage.message}`);
        } else if (lastMessage.type === 'script_generation_error') {
            setGenerating(false);
            console.error('剧本生成失败:', lastMessage.error);
            alert(`❌ 剧本生成失败: ${lastMessage.message}`);
        } else if (lastMessage.type === 'progress') {
            // 显示进度消息（可选）
            console.log(`进度: ${lastMessage.current_step} - ${lastMessage.message}`);
        }
    }, [messages, id]);

    const loadProject = async (projectId: number) => {
        try {
            const data = await projectApi.getProject(projectId);
            console.log('加载项目数据:', data);
            console.log('分镜数量:', data.scenes?.length);
            if (data.scenes && data.scenes.length > 0) {
                console.log('第一个分镜:', data.scenes[0]);
            }
            setProject(data);
            
            // 如果正在生产或已完成，切换到生产标签
            if (data.status === 'in_production' || data.status === 'completed') {
                setActiveTab('production');
            }
        } catch (error) {
            console.error('加载项目失败:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleGenerateScript = async () => {
        if (!id) return;
        
        setGenerating(true);
        try {
            await projectApi.generateScript(Number(id));
            await loadProject(Number(id));
        } catch (error) {
            console.error('生成剧本失败:', error);
            alert('生成剧本失败，请重试');
        } finally {
            setGenerating(false);
        }
    };

    const handleStartProduction = async () => {
        if (!id) return;
        
        setStarting(true);
        try {
            await projectApi.startProduction(Number(id));
            setActiveTab('production');
            await loadProject(Number(id));
        } catch (error) {
            console.error('启动生产失败:', error);
            alert('启动生产失败，请重试');
        } finally {
            setStarting(false);
        }
    };

    if (loading) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center">
                <div className="text-center">
                    <div className="w-16 h-16 border-4 border-purple-500/30 border-t-purple-500 rounded-full animate-spin mx-auto mb-4" />
                    <p className="text-slate-400">加载中...</p>
                </div>
            </div>
        );
    }

    if (!project) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center">
                <div className="text-center">
                    <p className="text-slate-400 text-lg">项目不存在</p>
                    <button
                        onClick={() => navigate('/projects')}
                        className="mt-4 px-6 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-white transition-colors"
                    >
                        返回项目列表
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
            {/* 背景装饰 */}
            <div className="fixed inset-0 overflow-hidden pointer-events-none">
                <div className="absolute top-1/4 right-1/4 w-96 h-96 bg-purple-500/5 rounded-full blur-3xl" />
                <div className="absolute bottom-1/4 left-1/4 w-96 h-96 bg-blue-500/5 rounded-full blur-3xl" />
            </div>

            <div className="relative max-w-7xl mx-auto px-6 py-8">
                {/* 顶部导航 */}
                <motion.div
                    initial={{ opacity: 0, y: -20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mb-8"
                >
                    <button
                        onClick={() => navigate('/projects')}
                        className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors mb-6"
                    >
                        <ArrowLeft size={20} />
                        <span>返回项目列表</span>
                    </button>

                    <div className="flex items-start justify-between">
                        <div>
                            <h1 className="text-4xl font-bold mb-2 bg-gradient-to-r from-white via-purple-200 to-blue-200 bg-clip-text text-transparent">
                                {project.name}
                            </h1>
                            {project.theme && (
                                <p className="text-slate-400 text-lg">{project.theme}</p>
                            )}
                        </div>

                        {/* 操作按钮 */}
                        <div className="flex gap-3">
                            {project.status === 'draft' && (
                                <motion.button
                                    whileHover={{ scale: 1.05 }}
                                    whileTap={{ scale: 0.95 }}
                                    onClick={handleGenerateScript}
                                    disabled={generating}
                                    className="px-6 py-3 bg-gradient-to-r from-purple-600 to-blue-600 rounded-xl text-white font-semibold flex items-center gap-2 shadow-lg shadow-purple-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    <Sparkles size={20} />
                                    <span>{generating ? '生成中...' : '生成剧本'}</span>
                                </motion.button>
                            )}

                            {project.status === 'script_generated' && (
                                <motion.button
                                    whileHover={{ scale: 1.05 }}
                                    whileTap={{ scale: 0.95 }}
                                    onClick={handleStartProduction}
                                    disabled={starting}
                                    className="px-6 py-3 bg-gradient-to-r from-emerald-600 to-teal-600 rounded-xl text-white font-semibold flex items-center gap-2 shadow-lg shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    <Play size={20} />
                                    <span>{starting ? '启动中...' : '开始制作'}</span>
                                </motion.button>
                            )}

                            {project.status === 'completed' && project.final_video_path && (
                                <motion.a
                                    href={project.final_video_path}
                                    download
                                    whileHover={{ scale: 1.05 }}
                                    whileTap={{ scale: 0.95 }}
                                    className="px-6 py-3 bg-gradient-to-r from-emerald-600 to-teal-600 rounded-xl text-white font-semibold flex items-center gap-2 shadow-lg shadow-emerald-500/20"
                                >
                                    <Download size={20} />
                                    <span>下载视频</span>
                                </motion.a>
                            )}
                        </div>
                    </div>
                </motion.div>

                {/* 标签页 */}
                <div className="mb-8">
                    <div className="flex gap-4 border-b border-slate-800">
                        <button
                            onClick={() => setActiveTab('script')}
                            className={`px-6 py-3 font-medium transition-all relative ${
                                activeTab === 'script'
                                    ? 'text-purple-400'
                                    : 'text-slate-500 hover:text-slate-300'
                            }`}
                        >
                            剧本预览
                            {activeTab === 'script' && (
                                <motion.div
                                    layoutId="activeTab"
                                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-purple-500 to-blue-500"
                                />
                            )}
                        </button>
                        <button
                            onClick={() => setActiveTab('production')}
                            className={`px-6 py-3 font-medium transition-all relative ${
                                activeTab === 'production'
                                    ? 'text-purple-400'
                                    : 'text-slate-500 hover:text-slate-300'
                            }`}
                        >
                            制作进度
                            {activeTab === 'production' && (
                                <motion.div
                                    layoutId="activeTab"
                                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-purple-500 to-blue-500"
                                />
                            )}
                        </button>
                    </div>
                </div>

                {/* 内容区域 */}
                <motion.div
                    key={activeTab}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3 }}
                >
                    {activeTab === 'script' ? (
                        <ScriptPreview project={project} onReload={() => loadProject(id!)} />
                    ) : (
                        <ProductionProgress project={project} onReload={() => loadProject(id!)} />
                    )}
                </motion.div>
            </div>
        </div>
    );
};
