import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Film, Sparkles, Lock, User, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { authApi } from '../api/client';

/**
 * 登录页面
 * 
 * 设计理念：
 * - 极简主义 + 未来科技感
 * - 大胆的渐变和光效
 * - 流畅的表单动画
 * - 沉浸式的视觉体验
 */
export const Login: React.FC = () => {
    const navigate = useNavigate();
    const { login } = useAuthStore();
    const [formData, setFormData] = useState({ username: '', password: '' });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            const response = await authApi.login(formData.username, formData.password);
            login(response.token, response.user);
            navigate('/projects');
        } catch (err: any) {
            setError(err.response?.data?.message || '登录失败，请检查用户名和密码');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center px-6 relative overflow-hidden">
            {/* 动态背景 */}
            <div className="absolute inset-0 overflow-hidden">
                {/* 主光效 */}
                <motion.div
                    animate={{
                        scale: [1, 1.2, 1],
                        opacity: [0.3, 0.5, 0.3],
                    }}
                    transition={{
                        duration: 8,
                        repeat: Infinity,
                        ease: 'easeInOut',
                    }}
                    className="absolute top-1/4 left-1/4 w-[800px] h-[800px] bg-purple-500/20 rounded-full blur-3xl"
                />
                <motion.div
                    animate={{
                        scale: [1.2, 1, 1.2],
                        opacity: [0.3, 0.5, 0.3],
                    }}
                    transition={{
                        duration: 8,
                        repeat: Infinity,
                        ease: 'easeInOut',
                        delay: 1,
                    }}
                    className="absolute bottom-1/4 right-1/4 w-[800px] h-[800px] bg-blue-500/20 rounded-full blur-3xl"
                />

                {/* 网格背景 */}
                <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:100px_100px] [mask-image:radial-gradient(ellipse_80%_50%_at_50%_50%,black,transparent)]" />
            </div>

            {/* 登录卡片 */}
            <motion.div
                initial={{ opacity: 0, scale: 0.9, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className="relative z-10 w-full max-w-md"
            >
                {/* Logo 和标题 */}
                <motion.div
                    initial={{ opacity: 0, y: -20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.2 }}
                    className="text-center mb-12"
                >
                    {/* Logo */}
                    <motion.div
                        animate={{
                            rotate: [0, 5, -5, 0],
                        }}
                        transition={{
                            duration: 6,
                            repeat: Infinity,
                            ease: 'easeInOut',
                        }}
                        className="inline-flex items-center justify-center w-20 h-20 mb-6 bg-gradient-to-br from-purple-500/20 to-blue-500/20 backdrop-blur-sm rounded-2xl border border-purple-500/30 shadow-2xl shadow-purple-500/20"
                    >
                        <Film className="text-purple-400" size={40} />
                    </motion.div>

                    {/* 标题 */}
                    <h1 className="text-5xl font-bold mb-4 bg-gradient-to-r from-white via-purple-200 to-blue-200 bg-clip-text text-transparent">
                        AI 短剧平台
                    </h1>
                    <p className="text-slate-400 text-lg flex items-center justify-center gap-2">
                        <Sparkles size={18} className="text-purple-400" />
                        <span>从创意到成品，全自动化制作</span>
                    </p>
                </motion.div>

                {/* 登录表单 */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                    className="bg-gradient-to-br from-slate-800/80 to-slate-900/80 backdrop-blur-xl rounded-3xl p-8 border border-slate-700/50 shadow-2xl"
                >
                    <form onSubmit={handleSubmit} className="space-y-6">
                        {/* 用户名 */}
                        <div>
                            <label className="block text-sm font-medium text-slate-300 mb-2">
                                用户名
                            </label>
                            <div className="relative">
                                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                                    <User className="text-slate-500" size={20} />
                                </div>
                                <input
                                    type="text"
                                    value={formData.username}
                                    onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                                    placeholder="请输入用户名"
                                    className="w-full pl-12 pr-4 py-4 bg-slate-900/50 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                                    required
                                />
                            </div>
                        </div>

                        {/* 密码 */}
                        <div>
                            <label className="block text-sm font-medium text-slate-300 mb-2">
                                密码
                            </label>
                            <div className="relative">
                                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                                    <Lock className="text-slate-500" size={20} />
                                </div>
                                <input
                                    type="password"
                                    value={formData.password}
                                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                                    placeholder="请输入密码"
                                    className="w-full pl-12 pr-4 py-4 bg-slate-900/50 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                                    required
                                />
                            </div>
                        </div>

                        {/* 错误提示 */}
                        {error && (
                            <motion.div
                                initial={{ opacity: 0, y: -10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm"
                            >
                                {error}
                            </motion.div>
                        )}

                        {/* 登录按钮 */}
                        <motion.button
                            type="submit"
                            disabled={loading}
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                            className="w-full py-4 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 rounded-xl text-white font-semibold flex items-center justify-center gap-3 shadow-lg shadow-purple-500/30 hover:shadow-purple-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed group"
                        >
                            {loading ? (
                                <>
                                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    <span>登录中...</span>
                                </>
                            ) : (
                                <>
                                    <span>登录</span>
                                    <ArrowRight className="group-hover:translate-x-1 transition-transform" size={20} />
                                </>
                            )}
                        </motion.button>
                    </form>

                    {/* 提示信息 */}
                    <div className="mt-6 pt-6 border-t border-slate-700/50 text-center">
                        <p className="text-slate-500 text-sm">
                            演示账号：admin / admin123
                        </p>
                    </div>
                </motion.div>

                {/* 底部装饰 */}
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.5 }}
                    className="mt-8 text-center text-slate-600 text-sm"
                >
                    <p>© 2026 AI 短剧自动化生产平台</p>
                </motion.div>
            </motion.div>
        </div>
    );
};
