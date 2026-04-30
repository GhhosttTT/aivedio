import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { useParams, useNavigate } from 'react-router-dom';
import { 
    ArrowLeft, Download, Share2, Play, Pause, 
    Volume2, VolumeX, Maximize, SkipBack, SkipForward,
    Film, Clock, Eye
} from 'lucide-react';
import { projectApi } from '../api/client';
import type { Project } from '../types';

/**
 * 视频预览页面
 * 
 * 设计理念：
 * - 沉浸式影院体验
 * - 自定义视频播放器
 * - 流畅的控制动画
 * - 优雅的信息展示
 */
export const VideoPreview: React.FC = () => {
    const { id } = useParams<{ id: string }>();
    const navigate = useNavigate();
    const videoRef = useRef<HTMLVideoElement>(null);
    
    const [project, setProject] = useState<Project | null>(null);
    const [loading, setLoading] = useState(true);
    const [playing, setPlaying] = useState(false);
    const [muted, setMuted] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [volume, setVolume] = useState(1);
    const [showControls, setShowControls] = useState(true);
    const [isFullscreen, setIsFullscreen] = useState(false);

    useEffect(() => {
        if (id) {
            loadProject(Number(id));
        }
    }, [id]);

    const loadProject = async (projectId: number) => {
        try {
            const data = await projectApi.getProject(projectId);
            setProject(data);
        } catch (error) {
            console.error('加载项目失败:', error);
        } finally {
            setLoading(false);
        }
    };

    const togglePlay = () => {
        if (videoRef.current) {
            if (playing) {
                videoRef.current.pause();
            } else {
                videoRef.current.play();
            }
            setPlaying(!playing);
        }
    };

    const toggleMute = () => {
        if (videoRef.current) {
            videoRef.current.muted = !muted;
            setMuted(!muted);
        }
    };

    const handleVolumeChange = (value: number) => {
        if (videoRef.current) {
            videoRef.current.volume = value;
            setVolume(value);
            setMuted(value === 0);
        }
    };

    const handleSeek = (value: number) => {
        if (videoRef.current) {
            videoRef.current.currentTime = value;
            setCurrentTime(value);
        }
    };

    const skip = (seconds: number) => {
        if (videoRef.current) {
            videoRef.current.currentTime += seconds;
        }
    };

    const toggleFullscreen = () => {
        if (!document.fullscreenElement) {
            videoRef.current?.requestFullscreen();
            setIsFullscreen(true);
        } else {
            document.exitFullscreen();
            setIsFullscreen(false);
        }
    };

    const formatTime = (seconds: number) => {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    };

    const handleDownload = () => {
        if (project?.final_video_path) {
            const link = document.createElement('a');
            link.href = project.final_video_path;
            link.download = `${project.name}.mp4`;
            link.click();
        }
    };

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center">
                <div className="text-center">
                    <div className="w-16 h-16 border-4 border-purple-500/30 border-t-purple-500 rounded-full animate-spin mx-auto mb-4" />
                    <p className="text-slate-400">加载中...</p>
                </div>
            </div>
        );
    }

    if (!project || !project.final_video_path) {
        return (
            <div className="min-h-screen flex items-center justify-center">
                <div className="text-center">
                    <Film className="w-20 h-20 text-slate-600 mx-auto mb-4" />
                    <p className="text-slate-400 text-lg mb-4">视频不存在</p>
                    <button
                        onClick={() => navigate('/projects')}
                        className="px-6 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-white transition-colors"
                    >
                        返回项目列表
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen">
            {/* 顶部导航 */}
            <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                className="relative z-20 max-w-7xl mx-auto px-6 py-6"
            >
                <button
                    onClick={() => navigate(`/projects/${id}`)}
                    className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors"
                >
                    <ArrowLeft size={20} />
                    <span>返回项目</span>
                </button>
            </motion.div>

            {/* 视频播放器容器 */}
            <div className="max-w-7xl mx-auto px-6 pb-12">
                <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: 0.2 }}
                    className="relative bg-black rounded-3xl overflow-hidden shadow-2xl"
                    onMouseEnter={() => setShowControls(true)}
                    onMouseLeave={() => playing && setShowControls(false)}
                >
                    {/* 视频元素 */}
                    <video
                        ref={videoRef}
                        src={project.final_video_path}
                        className="w-full aspect-video"
                        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
                        onEnded={() => setPlaying(false)}
                        onClick={togglePlay}
                    />

                    {/* 播放/暂停覆盖层 */}
                    {!playing && (
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="absolute inset-0 flex items-center justify-center bg-black/30 backdrop-blur-sm cursor-pointer"
                            onClick={togglePlay}
                        >
                            <motion.div
                                whileHover={{ scale: 1.1 }}
                                whileTap={{ scale: 0.9 }}
                                className="w-24 h-24 bg-white/10 backdrop-blur-md rounded-full flex items-center justify-center border-4 border-white/30"
                            >
                                <Play className="text-white ml-2" size={40} />
                            </motion.div>
                        </motion.div>
                    )}

                    {/* 控制栏 */}
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: showControls ? 1 : 0, y: showControls ? 0 : 20 }}
                        transition={{ duration: 0.3 }}
                        className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 via-black/60 to-transparent p-6"
                    >
                        {/* 进度条 */}
                        <div className="mb-4">
                            <input
                                type="range"
                                min={0}
                                max={duration || 0}
                                value={currentTime}
                                onChange={(e) => handleSeek(Number(e.target.value))}
                                className="w-full h-1 bg-white/20 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:cursor-pointer hover:[&::-webkit-slider-thumb]:scale-125 transition-all"
                            />
                            <div className="flex justify-between text-xs text-white/60 mt-1">
                                <span>{formatTime(currentTime)}</span>
                                <span>{formatTime(duration)}</span>
                            </div>
                        </div>

                        {/* 控制按钮 */}
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-4">
                                {/* 播放/暂停 */}
                                <button
                                    onClick={togglePlay}
                                    className="w-10 h-10 flex items-center justify-center bg-white/10 hover:bg-white/20 rounded-full transition-colors"
                                >
                                    {playing ? <Pause size={20} /> : <Play size={20} className="ml-0.5" />}
                                </button>

                                {/* 快退/快进 */}
                                <button
                                    onClick={() => skip(-10)}
                                    className="w-10 h-10 flex items-center justify-center hover:bg-white/10 rounded-full transition-colors"
                                >
                                    <SkipBack size={20} />
                                </button>
                                <button
                                    onClick={() => skip(10)}
                                    className="w-10 h-10 flex items-center justify-center hover:bg-white/10 rounded-full transition-colors"
                                >
                                    <SkipForward size={20} />
                                </button>

                                {/* 音量控制 */}
                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={toggleMute}
                                        className="w-10 h-10 flex items-center justify-center hover:bg-white/10 rounded-full transition-colors"
                                    >
                                        {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
                                    </button>
                                    <input
                                        type="range"
                                        min={0}
                                        max={1}
                                        step={0.1}
                                        value={volume}
                                        onChange={(e) => handleVolumeChange(Number(e.target.value))}
                                        className="w-20 h-1 bg-white/20 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:cursor-pointer"
                                    />
                                </div>
                            </div>

                            <div className="flex items-center gap-2">
                                {/* 全屏 */}
                                <button
                                    onClick={toggleFullscreen}
                                    className="w-10 h-10 flex items-center justify-center hover:bg-white/10 rounded-full transition-colors"
                                >
                                    <Maximize size={20} />
                                </button>
                            </div>
                        </div>
                    </motion.div>
                </motion.div>

                {/* 视频信息和操作 */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                    className="mt-8 grid grid-cols-1 lg:grid-cols-3 gap-6"
                >
                    {/* 视频信息 */}
                    <div className="lg:col-span-2 bg-gradient-to-br from-slate-800/50 to-slate-900/50 backdrop-blur-sm rounded-2xl p-6 border border-slate-700/50">
                        <h2 className="text-2xl font-bold text-white mb-4">{project.name}</h2>
                        {project.theme && (
                            <p className="text-slate-400 mb-4">{project.theme}</p>
                        )}
                        <div className="flex flex-wrap gap-4 text-sm text-slate-500">
                            <div className="flex items-center gap-2">
                                <Film size={16} />
                                <span>{project.scenes?.length || 0} 个分镜</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <Clock size={16} />
                                <span>{formatTime(duration)}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <Eye size={16} />
                                <span>1080p</span>
                            </div>
                        </div>
                    </div>

                    {/* 操作按钮 */}
                    <div className="space-y-3">
                        <button
                            onClick={handleDownload}
                            className="w-full px-6 py-4 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 rounded-xl text-white font-semibold flex items-center justify-center gap-3 shadow-lg shadow-emerald-500/20 transition-all"
                        >
                            <Download size={20} />
                            <span>下载视频</span>
                        </button>
                        <button
                            className="w-full px-6 py-4 bg-slate-800/50 hover:bg-slate-800 rounded-xl text-white font-semibold flex items-center justify-center gap-3 transition-all"
                        >
                            <Share2 size={20} />
                            <span>分享</span>
                        </button>
                    </div>
                </motion.div>
            </div>
        </div>
    );
};
