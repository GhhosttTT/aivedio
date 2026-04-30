import React from 'react';
import { motion } from 'framer-motion';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Film, LogOut, User, Sparkles } from 'lucide-react';
import { useAuthStore } from '../store/authStore';

/**
 * 全局导航栏
 * 
 * 设计理念：
 * - 玻璃态效果
 * - 流畅的悬停动画
 * - 清晰的视觉层级
 */
export const Navigation: React.FC = () => {
    const location = useLocation();
    const navigate = useNavigate();
    const { user, logout } = useAuthStore();

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    return (
        <motion.nav
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="sticky top-0 z-50 backdrop-blur-xl bg-slate-900/80 border-b border-slate-800/50"
        >
            <div className="max-w-7xl mx-auto px-6 py-4">
                <div className="flex items-center justify-between">
                    {/* Logo */}
                    <Link to="/projects" className="flex items-center gap-3 group">
                        <div className="w-10 h-10 bg-gradient-to-br from-purple-500/20 to-blue-500/20 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform">
                            <Film className="text-purple-400" size={24} />
                        </div>
                        <div>
                            <h1 className="text-lg font-bold bg-gradient-to-r from-white to-purple-200 bg-clip-text text-transparent">
                                AI 短剧平台
                            </h1>
                            <p className="text-xs text-slate-500 flex items-center gap-1">
                                <Sparkles size={10} />
                                <span>智能创作</span>
                            </p>
                        </div>
                    </Link>

                    {/* 用户信息 */}
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-3 px-4 py-2 bg-slate-800/50 rounded-xl">
                            <div className="w-8 h-8 bg-gradient-to-br from-purple-500/30 to-blue-500/30 rounded-lg flex items-center justify-center">
                                <User className="text-purple-400" size={16} />
                            </div>
                            <span className="text-sm text-slate-300">{user?.username || '用户'}</span>
                        </div>

                        <motion.button
                            whileHover={{ scale: 1.05 }}
                            whileTap={{ scale: 0.95 }}
                            onClick={handleLogout}
                            className="px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-xl flex items-center gap-2 transition-colors"
                        >
                            <LogOut size={16} />
                            <span className="text-sm">退出</span>
                        </motion.button>
                    </div>
                </div>
            </div>
        </motion.nav>
    );
};
