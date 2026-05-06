import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Film, User, MessageSquare, RefreshCw, Edit2 } from 'lucide-react';
import { projectApi } from '../api/client';
import type { Project, Scene } from '../types';

interface ScriptPreviewProps {
    project: Project;
    onReload: () => void;
}

/**
 * 剧本预览组件
 * 
 * 功能：
 * - 展示完整剧本
 * - 展示分镜列表
 * - 重新生成单个分镜
 * - 编辑分镜描述
 */
export const ScriptPreview: React.FC<ScriptPreviewProps> = ({ project, onReload }) => {
    const [regeneratingScene, setRegeneratingScene] = useState<number | null>(null);
    const [editingScene, setEditingScene] = useState<number | null>(null);
    const [editDescription, setEditDescription] = useState('');

    const handleRegenerateScene = async (sceneNumber: number) => {
        setRegeneratingScene(sceneNumber);
        try {
            await projectApi.regenerateScene(Number(project.id), sceneNumber);
            onReload();
            setEditingScene(null);
        } catch (error) {
            console.error('重新生成分镜失败:', error);
            alert('重新生成分镜失败，请重试');
        } finally {
            setRegeneratingScene(null);
        }
    };

    const startEdit = (scene: Scene) => {
        setEditingScene(scene.scene_number);
        setEditDescription(scene.description);
    };

    // 只要有分镜就显示，不强制要求 script 字段
    if (!project.scenes || project.scenes.length === 0) {
        return (
            <div className="bg-gradient-to-br from-slate-800/50 to-slate-900/50 backdrop-blur-sm rounded-2xl p-12 text-center border border-slate-700/50">
                <div className="w-20 h-20 bg-slate-800/50 rounded-full flex items-center justify-center mx-auto mb-6">
                    <Film className="text-slate-600" size={40} />
                </div>
                <h3 className="text-2xl font-bold text-slate-400 mb-2">
                    还没有剧本
                </h3>
                <p className="text-slate-500">
                    点击"生成剧本"按钮开始创作
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-8">
            {/* 分镜列表 */}
            <div>
                <h2 className="text-2xl font-bold text-white mb-6">
                    分镜列表 ({project.scenes?.length || 0} 个分镜)
                </h2>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <AnimatePresence>
                        {project.scenes && project.scenes.map((scene, index) => (
                            <motion.div
                                key={scene.id}
                                initial={{ opacity: 0, scale: 0.95 }}
                                animate={{ opacity: 1, scale: 1 }}
                                exit={{ opacity: 0, scale: 0.95 }}
                                transition={{ delay: index * 0.05 }}
                                className="group relative bg-gradient-to-br from-slate-800/80 to-slate-900/80 backdrop-blur-sm rounded-2xl p-6 border border-slate-700/50 hover:border-purple-500/50 transition-all"
                            >
                                {/* 分镜编号 */}
                                <div className="absolute top-4 right-4 w-10 h-10 bg-gradient-to-br from-purple-500/20 to-blue-500/20 rounded-lg flex items-center justify-center">
                                    <span className="text-purple-400 font-bold">
                                        {scene.scene_number}
                                    </span>
                                </div>

                                {/* 场景描述 */}
                                <div className="mb-4 pr-12">
                                    <h3 className="text-lg font-semibold text-white mb-2">
                                        场景描述
                                    </h3>
                                    {editingScene === scene.scene_number ? (
                                        <textarea
                                            value={editDescription}
                                            onChange={(e) => setEditDescription(e.target.value)}
                                            className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors resize-none"
                                            rows={3}
                                        />
                                    ) : (
                                        <p className="text-slate-300 leading-relaxed">
                                            {scene.visual_description}
                                        </p>
                                    )}
                                </div>

                                {/* 角色 */}
                                {scene.character_name && (
                                    <div className="mb-4">
                                        <div className="flex items-center gap-2 mb-2">
                                            <User className="text-slate-500" size={16} />
                                            <span className="text-sm font-medium text-slate-400">
                                                角色
                                            </span>
                                        </div>
                                        <span className="px-3 py-1 bg-slate-700/50 rounded-lg text-sm text-slate-300">
                                            {scene.character_name}
                                        </span>
                                    </div>
                                )}

                                {/* 对话 */}
                                {scene.dialogue && (
                                    <div className="mb-4">
                                        <div className="flex items-center gap-2 mb-2">
                                            <MessageSquare className="text-slate-500" size={16} />
                                            <span className="text-sm font-medium text-slate-400">
                                                {scene.character_name && `${scene.character_name}：`}
                                            </span>
                                        </div>
                                        <p className="text-slate-300 italic pl-4 border-l-2 border-purple-500/30">
                                            "{scene.dialogue}"
                                        </p>
                                    </div>
                                )}

                                {/* 图像提示词 */}
                                {scene.image_prompt && (
                                    <div className="mb-4">
                                        <div className="text-sm font-medium text-slate-400 mb-2">
                                            图像提示词
                                        </div>
                                        <p className="text-xs text-slate-500 leading-relaxed">
                                            {scene.image_prompt}
                                        </p>
                                    </div>
                                )}

                                {/* 操作按钮 */}
                                <div className="flex gap-2 pt-4 border-t border-slate-700/50">
                                    {editingScene === scene.scene_number ? (
                                        <>
                                            <button
                                                onClick={() => setEditingScene(null)}
                                                className="flex-1 px-4 py-2 bg-slate-700/50 hover:bg-slate-700 rounded-lg text-white text-sm font-medium transition-colors"
                                            >
                                                取消
                                            </button>
                                            <button
                                                onClick={() => handleRegenerateScene(scene.scene_number)}
                                                disabled={regeneratingScene === scene.scene_number}
                                                className="flex-1 px-4 py-2 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 rounded-lg text-white text-sm font-medium transition-all disabled:opacity-50 flex items-center justify-center gap-2"
                                            >
                                                {regeneratingScene === scene.scene_number ? (
                                                    <>
                                                        <RefreshCw className="animate-spin" size={16} />
                                                        <span>生成中...</span>
                                                    </>
                                                ) : (
                                                    <>
                                                        <RefreshCw size={16} />
                                                        <span>重新生成</span>
                                                    </>
                                                )}
                                            </button>
                                        </>
                                    ) : (
                                        <button
                                            onClick={() => startEdit(scene)}
                                            className="flex-1 px-4 py-2 bg-slate-700/50 hover:bg-slate-700 rounded-lg text-white text-sm font-medium transition-colors flex items-center justify-center gap-2"
                                        >
                                            <Edit2 size={16} />
                                            <span>编辑并重新生成</span>
                                        </button>
                                    )}
                                </div>
                            </motion.div>
                        ))}
                    </AnimatePresence>
                </div>
            </div>
        </div>
    );
};
