import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Film, Clock, CheckCircle, XCircle, Play } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { projectApi } from '../api/client';
import type { Project } from '../types';

/**
 * 项目列表页面
 * 
 * 功能：
 * - 展示所有短剧项目
 * - 创建新项目
 * - 查看项目状态
 * - 跳转到项目详情
 */
export const ProjectList: React.FC = () => {
    const navigate = useNavigate();
    const [projects, setProjects] = useState<Project[]>([]);
    const [loading, setLoading] = useState(true);
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [pagination, setPagination] = useState({
        page: 1,
        pageSize: 12,
        total: 0
    });

    useEffect(() => {
        loadProjects();
    }, [pagination.page]);

    const loadProjects = async () => {
        try {
            const data = await projectApi.listProjects({
                page: pagination.page,
                page_size: pagination.pageSize
            });
            setProjects(data.projects);
            setPagination(prev => ({
                ...prev,
                total: data.total
            }));
        } catch (error) {
            console.error('加载项目失败:', error);
        } finally {
            setLoading(false);
        }
    };

    const getStatusConfig = (status: string) => {
        const configs = {
            draft: { icon: Clock, color: 'text-slate-400', bg: 'bg-slate-500/10', label: '草稿' },
            script_generated: { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10', label: '剧本已生成' },
            in_production: { icon: Play, color: 'text-purple-400', bg: 'bg-purple-500/10', label: '制作中' },
            completed: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: '已完成' },
            failed: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10', label: '失败' },
        };
        return configs[status as keyof typeof configs] || configs.draft;
    };

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
            {/* 背景装饰 */}
            <div className="fixed inset-0 overflow-hidden pointer-events-none">
                <div className="absolute top-0 left-1/4 w-96 h-96 bg-purple-500/5 rounded-full blur-3xl" />
                <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-blue-500/5 rounded-full blur-3xl" />
            </div>

            <div className="relative max-w-7xl mx-auto px-6 py-12">
                {/* 页面标题 */}
                <motion.div
                    initial={{ opacity: 0, y: -20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mb-12"
                >
                    <h1 className="text-5xl font-bold mb-4 bg-gradient-to-r from-white via-purple-200 to-blue-200 bg-clip-text text-transparent">
                        我的短剧项目
                    </h1>
                    <p className="text-slate-400 text-lg">
                        从创意到成品，AI 驱动的全自动化短剧制作
                    </p>
                </motion.div>

                {/* 创建项目按钮 */}
                <motion.button
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={() => setShowCreateModal(true)}
                    className="mb-8 px-8 py-4 bg-gradient-to-r from-purple-600 to-blue-600 rounded-2xl text-white font-semibold flex items-center gap-3 shadow-lg shadow-purple-500/20 hover:shadow-purple-500/40 transition-shadow"
                >
                    <Plus size={24} />
                    <span>创建新项目</span>
                </motion.button>

                {/* 项目网格 */}
                {loading ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {[1, 2, 3].map((i) => (
                            <div key={i} className="h-64 bg-slate-800/50 rounded-2xl animate-pulse" />
                        ))}
                    </div>
                ) : (
                    <motion.div
                        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
                        initial="hidden"
                        animate="visible"
                        variants={{
                            visible: {
                                transition: {
                                    staggerChildren: 0.1
                                }
                            }
                        }}
                    >
                        <AnimatePresence>
                            {projects.map((project, index) => {
                                const statusConfig = getStatusConfig(project.status);
                                const StatusIcon = statusConfig.icon;

                                return (
                                    <motion.div
                                        key={project.id}
                                        variants={{
                                            hidden: { opacity: 0, y: 20 },
                                            visible: { opacity: 1, y: 0 }
                                        }}
                                        whileHover={{ y: -8, transition: { duration: 0.2 } }}
                                        onClick={() => navigate(`/projects/${project.id}`)}
                                        className="group relative bg-gradient-to-br from-slate-800/80 to-slate-900/80 backdrop-blur-sm rounded-2xl p-6 cursor-pointer border border-slate-700/50 hover:border-purple-500/50 transition-all overflow-hidden"
                                    >
                                        {/* 悬停光效 */}
                                        <div className="absolute inset-0 bg-gradient-to-br from-purple-500/0 to-blue-500/0 group-hover:from-purple-500/5 group-hover:to-blue-500/5 transition-all duration-500" />

                                        <div className="relative z-10">
                                            {/* 项目图标 */}
                                            <div className="w-14 h-14 bg-gradient-to-br from-purple-500/20 to-blue-500/20 rounded-xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
                                                <Film className="text-purple-400" size={28} />
                                            </div>

                                            {/* 项目名称 */}
                                            <h3 className="text-xl font-bold text-white mb-2 line-clamp-1">
                                                {project.name}
                                            </h3>

                                            {/* 项目主题 */}
                                            {project.theme && (
                                                <p className="text-slate-400 text-sm mb-4 line-clamp-2">
                                                    {project.theme}
                                                </p>
                                            )}

                                            {/* 状态标签 */}
                                            <div className={`inline-flex items-center gap-2 px-3 py-1.5 ${statusConfig.bg} rounded-lg mb-4`}>
                                                <StatusIcon className={statusConfig.color} size={16} />
                                                <span className={`text-sm font-medium ${statusConfig.color}`}>
                                                    {statusConfig.label}
                                                </span>
                                            </div>

                                            {/* 分镜数量 */}
                                            {project.scenes && project.scenes.length > 0 && (
                                                <div className="text-slate-500 text-sm">
                                                    {project.scenes.length} 个分镜
                                                </div>
                                            )}

                                            {/* 创建时间 */}
                                            <div className="mt-4 pt-4 border-t border-slate-700/50 text-slate-500 text-xs">
                                                {new Date(project.created_at).toLocaleDateString('zh-CN')}
                                            </div>
                                        </div>
                                    </motion.div>
                                );
                            })}
                        </AnimatePresence>
                    </motion.div>
                )}

                {/* 空状态 */}
                {!loading && projects.length === 0 && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="text-center py-20"
                    >
                        <div className="w-24 h-24 bg-slate-800/50 rounded-full flex items-center justify-center mx-auto mb-6">
                            <Film className="text-slate-600" size={48} />
                        </div>
                        <h3 className="text-2xl font-bold text-slate-400 mb-2">
                            还没有项目
                        </h3>
                        <p className="text-slate-500 mb-8">
                            点击上方按钮创建你的第一个短剧项目
                        </p>
                    </motion.div>
                )}
            </div>

            {/* 创建项目模态框 */}
            <CreateProjectModal
                isOpen={showCreateModal}
                onClose={() => setShowCreateModal(false)}
                onSuccess={() => {
                    setShowCreateModal(false);
                    loadProjects();
                }}
            />
        </div>
    );
};

/**
 * 创建项目模态框组件
 */
interface CreateProjectModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

const CreateProjectModal: React.FC<CreateProjectModalProps> = ({ isOpen, onClose, onSuccess }) => {
    const [formData, setFormData] = useState({
        name: '',
        description: '',
        theme: '',
        outline: ''
    });
    const [creating, setCreating] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!formData.name.trim()) return;

        setCreating(true);
        try {
            await projectApi.createProject({
                name: formData.name,
                description: formData.description || undefined,
                theme: formData.theme || undefined,
                outline: formData.outline || undefined
            });
            onSuccess();
            setFormData({ name: '', description: '', theme: '', outline: '' });
        } catch (error) {
            console.error('创建项目失败:', error);
        } finally {
            setCreating(false);
        }
    };

    if (!isOpen) return null;

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-6"
                onClick={onClose}
            >
                <motion.div
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.9, opacity: 0 }}
                    onClick={(e) => e.stopPropagation()}
                    className="bg-gradient-to-br from-slate-800 to-slate-900 rounded-3xl p-8 max-w-2xl w-full border border-slate-700/50 shadow-2xl"
                >
                    <h2 className="text-3xl font-bold mb-6 bg-gradient-to-r from-white to-purple-200 bg-clip-text text-transparent">
                        创建新项目
                    </h2>

                    <form onSubmit={handleSubmit} className="space-y-6">
                        {/* 项目名称 */}
                        <div>
                            <label className="block text-sm font-medium text-slate-300 mb-2">
                                项目名称 *
                            </label>
                            <input
                                type="text"
                                value={formData.name}
                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                placeholder="例如：都市爱情短剧"
                                className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
                                required
                            />
                        </div>

                        {/* 项目描述 */}
                        <div>
                            <label className="block text-sm font-medium text-slate-300 mb-2">
                                项目描述
                            </label>
                            <input
                                type="text"
                                value={formData.description}
                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                placeholder="简要描述项目内容"
                                className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
                            />
                        </div>

                        {/* 主题 */}
                        <div>
                            <label className="block text-sm font-medium text-slate-300 mb-2">
                                主题关键词
                            </label>
                            <input
                                type="text"
                                value={formData.theme}
                                onChange={(e) => setFormData({ ...formData, theme: e.target.value })}
                                placeholder="例如：霸道总裁、灰姑娘、逆袭"
                                className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
                            />
                        </div>

                        {/* 故事大纲 */}
                        <div>
                            <label className="block text-sm font-medium text-slate-300 mb-2">
                                故事大纲
                            </label>
                            <textarea
                                value={formData.outline}
                                onChange={(e) => setFormData({ ...formData, outline: e.target.value })}
                                placeholder="简要描述你的故事情节..."
                                rows={4}
                                className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors resize-none"
                            />
                        </div>

                        {/* 按钮 */}
                        <div className="flex gap-4 pt-4">
                            <button
                                type="button"
                                onClick={onClose}
                                className="flex-1 px-6 py-3 bg-slate-700/50 hover:bg-slate-700 rounded-xl text-white font-medium transition-colors"
                            >
                                取消
                            </button>
                            <button
                                type="submit"
                                disabled={creating || !formData.name.trim()}
                                className="flex-1 px-6 py-3 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 rounded-xl text-white font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {creating ? '创建中...' : '创建项目'}
                            </button>
                        </div>
                    </form>
                </motion.div>
            </motion.div>
        </AnimatePresence>
    );
};
