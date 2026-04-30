import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ProjectList } from './pages/ProjectList';
import { ProjectDetail } from './pages/ProjectDetail';
import { VideoPreview } from './pages/VideoPreview';
import { Login } from './pages/Login';
import { Navigation } from './components/Navigation';
import { useAuthStore } from './store/authStore';

/**
 * 主应用组件
 * 
 * 功能：
 * - 路由配置
 * - 认证保护
 * - 全局导航
 * - 页面过渡动画
 */
function App() {
    const { isAuthenticated } = useAuthStore();

    return (
        <BrowserRouter>
            <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
                {/* 全局背景装饰 */}
                <div className="fixed inset-0 overflow-hidden pointer-events-none">
                    <div className="absolute top-0 left-1/4 w-[600px] h-[600px] bg-purple-500/3 rounded-full blur-3xl animate-pulse" />
                    <div className="absolute bottom-0 right-1/4 w-[600px] h-[600px] bg-blue-500/3 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '1s' }} />
                    <div className="absolute top-1/2 left-1/2 w-[400px] h-[400px] bg-emerald-500/2 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '2s' }} />
                </div>

                {/* 导航栏 */}
                {isAuthenticated && <Navigation />}

                {/* 路由 */}
                <AnimatePresence mode="wait">
                    <Routes>
                        <Route
                            path="/login"
                            element={
                                isAuthenticated ? (
                                    <Navigate to="/projects" replace />
                                ) : (
                                    <PageTransition>
                                        <Login />
                                    </PageTransition>
                                )
                            }
                        />
                        <Route
                            path="/projects"
                            element={
                                isAuthenticated ? (
                                    <PageTransition>
                                        <ProjectList />
                                    </PageTransition>
                                ) : (
                                    <Navigate to="/login" replace />
                                )
                            }
                        />
                        <Route
                            path="/projects/:id"
                            element={
                                isAuthenticated ? (
                                    <PageTransition>
                                        <ProjectDetail />
                                    </PageTransition>
                                ) : (
                                    <Navigate to="/login" replace />
                                )
                            }
                        />
                        <Route
                            path="/projects/:id/video"
                            element={
                                isAuthenticated ? (
                                    <PageTransition>
                                        <VideoPreview />
                                    </PageTransition>
                                ) : (
                                    <Navigate to="/login" replace />
                                )
                            }
                        />
                        <Route path="/" element={<Navigate to="/projects" replace />} />
                    </Routes>
                </AnimatePresence>
            </div>
        </BrowserRouter>
    );
}

/**
 * 页面过渡动画包装器
 */
const PageTransition: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
        >
            {children}
        </motion.div>
    );
};

export default App;
