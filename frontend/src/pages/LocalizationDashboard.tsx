import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
    AlertCircle,
    CheckCircle,
    Download,
    ExternalLink,
    FileText,
    FileVideo,
    Globe2,
    RefreshCw,
    Upload,
} from 'lucide-react';
import { localizationApi, projectApi } from '../api/client';
import type { LocalizationJob, Project, SourceVideo } from '../types';

const defaultLanguages = ['en'];
const apiOrigin = 'http://127.0.0.1:8000';

const toStorageUrl = (path?: string | null) => {
    if (!path) return null;
    const normalized = path.replace(/\\/g, '/').replace(/^\.?\//, '');
    if (!normalized.startsWith('storage/')) return null;
    return `${apiOrigin}/${normalized}`;
};

const buildRenderedVideoUrl = (job: LocalizationJob, language: string) => {
    if (!job.rendered_video_dir) return null;
    return toStorageUrl(`${job.rendered_video_dir}/${language}.mp4`);
};

const buildSubtitleUrl = (job: LocalizationJob, language: string) => {
    if (!job.translated_subtitle_dir) return null;
    return toStorageUrl(`${job.translated_subtitle_dir}/${language}.srt`);
};

const buildStoryContextUrl = (job: LocalizationJob) => {
    if (!job.translated_subtitle_dir) return null;
    return toStorageUrl(`${job.translated_subtitle_dir}/story_context.json`);
};

export const LocalizationDashboard: React.FC = () => {
    const [projects, setProjects] = useState<Project[]>([]);
    const [projectId, setProjectId] = useState<number | null>(null);
    const [sourceVideos, setSourceVideos] = useState<SourceVideo[]>([]);
    const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
    const [selectedLanguages, setSelectedLanguages] = useState(defaultLanguages);
    const [job, setJob] = useState<LocalizationJob | null>(null);
    const [file, setFile] = useState<File | null>(null);
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');

    const selectedProject = useMemo(
        () => projects.find((project) => Number(project.id) === projectId),
        [projects, projectId],
    );

    const primaryLanguage = job?.target_languages[0] || selectedLanguages[0] || 'en';
    const primaryVideoUrl = job ? buildRenderedVideoUrl(job, primaryLanguage) : null;
    const reportUrl = job ? toStorageUrl(job.moderation_report_path) : null;
    const storyContextUrl = job ? buildStoryContextUrl(job) : null;

    useEffect(() => {
        loadProjects();
    }, []);

    useEffect(() => {
        if (projectId) {
            loadSourceVideos(projectId);
        }
    }, [projectId]);

    useEffect(() => {
        if (!job || ['completed', 'failed', 'needs_review'].includes(job.status)) {
            return;
        }

        const timer = window.setInterval(async () => {
            try {
                const latest = await localizationApi.getJob(job.id);
                setJob(latest);
                if (latest.status === 'completed') {
                    setMessage('译制完成，可以直接预览或下载视频');
                } else if (latest.status === 'failed' || latest.status === 'needs_review') {
                    setMessage(`任务需要处理：${latest.error_message || latest.status}`);
                }
            } catch (error) {
                console.error('刷新译制任务状态失败:', error);
            }
        }, 3000);

        return () => window.clearInterval(timer);
    }, [job]);

    const loadProjects = async () => {
        const data = await projectApi.listProjects({ page: 1, page_size: 100 });
        setProjects(data.projects);
        if (data.projects.length > 0) {
            setProjectId(Number(data.projects[0].id));
        }
    };

    const loadSourceVideos = async (id: number) => {
        const [videos, jobs] = await Promise.all([
            localizationApi.listSourceVideos(id),
            localizationApi.listProjectJobs(id),
        ]);
        setSourceVideos(videos);
        setSelectedVideoId(videos[0]?.id ?? null);
        setJob(jobs[0] ?? null);
    };

    const handleUpload = async () => {
        if (!projectId || !file) return;
        setLoading(true);
        setMessage('');
        try {
            const uploaded = await localizationApi.uploadSourceVideo(projectId, file);
            setSelectedVideoId(uploaded.id);
            await loadSourceVideos(projectId);
            setMessage('源片已上传');
        } finally {
            setLoading(false);
        }
    };

    const handleRun = async () => {
        if (!selectedVideoId) return;
        setLoading(true);
        setMessage('');
        try {
            const created = await localizationApi.createJob({
                source_video_id: selectedVideoId,
                target_languages: selectedLanguages,
                auto_start: true,
            });
            setJob(created);
            setMessage(`任务已提交：${created.status} / ${created.current_stage}`);
        } finally {
            setLoading(false);
        }
    };

    const toggleLanguage = (language: string) => {
        setSelectedLanguages((current) =>
            current.includes(language)
                ? current.filter((item) => item !== language)
                : [...current, language],
        );
    };

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
            <div className="relative max-w-7xl mx-auto px-6 py-10">
                <div className="mb-8">
                    <h1 className="text-4xl font-bold text-white mb-3">源片出海译制</h1>
                    <p className="text-slate-400">上传源片后执行 ASR、翻译、字幕烧录和审核，完成后可直接预览成片。</p>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-6">
                    <motion.div
                        initial={{ opacity: 0, y: 16 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="bg-slate-900/80 border border-slate-700/60 rounded-2xl p-6"
                    >
                        <div className="flex items-center gap-2 mb-5">
                            <Globe2 className="text-emerald-400" size={20} />
                            <h2 className="text-lg font-semibold text-white">任务设置</h2>
                        </div>

                        <label className="block text-sm text-slate-400 mb-2">项目</label>
                        <select
                            value={projectId ?? ''}
                            onChange={(event) => setProjectId(Number(event.target.value))}
                            className="w-full mb-5 px-3 py-3 bg-slate-950 border border-slate-700 rounded-lg text-white"
                        >
                            {projects.map((project) => (
                                <option key={project.id} value={project.id}>
                                    {project.name}
                                </option>
                            ))}
                        </select>

                        <label className="block text-sm text-slate-400 mb-2">上传源片</label>
                        <input
                            type="file"
                            accept=".mp4,.mov,.mkv,.avi,video/*"
                            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                            className="w-full mb-3 text-sm text-slate-300"
                        />
                        <button
                            onClick={handleUpload}
                            disabled={!file || !projectId || loading}
                            className="w-full mb-6 px-4 py-3 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded-lg text-white flex items-center justify-center gap-2"
                        >
                            <Upload size={16} />
                            上传源片
                        </button>

                        <label className="block text-sm text-slate-400 mb-2">已上传源片</label>
                        <select
                            value={selectedVideoId ?? ''}
                            onChange={(event) => setSelectedVideoId(Number(event.target.value))}
                            className="w-full mb-5 px-3 py-3 bg-slate-950 border border-slate-700 rounded-lg text-white"
                        >
                            <option value="">请选择源片</option>
                            {sourceVideos.map((video) => (
                                <option key={video.id} value={video.id}>
                                    {video.original_filename}
                                </option>
                            ))}
                        </select>

                        <div className="mb-5">
                            <div className="text-sm text-slate-400 mb-2">目标语言</div>
                            <div className="flex flex-wrap gap-2">
                                {['en', 'es', 'pt', 'ar', 'id', 'th', 'vi', 'ja', 'ko'].map((language) => (
                                    <button
                                        key={language}
                                        type="button"
                                        onClick={() => toggleLanguage(language)}
                                        className={`px-3 py-1.5 rounded-lg text-sm border ${
                                            selectedLanguages.includes(language)
                                                ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                                                : 'bg-slate-800 border-slate-700 text-slate-400'
                                        }`}
                                    >
                                        {language}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <button
                            onClick={handleRun}
                            disabled={!selectedVideoId || selectedLanguages.length === 0 || loading}
                            className="w-full px-4 py-3 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg text-white flex items-center justify-center gap-2"
                        >
                            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
                            开始译制流程
                        </button>
                    </motion.div>

                    <motion.div
                        initial={{ opacity: 0, y: 16 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="bg-slate-900/70 border border-slate-700/60 rounded-2xl p-6"
                    >
                        <div className="flex items-start justify-between mb-6">
                            <div>
                                <h2 className="text-2xl font-semibold text-white mb-2">
                                    {selectedProject?.name || '请选择项目'}
                                </h2>
                                <p className="text-slate-400">完成后优先展示第一种目标语言的视频，可在下方打开其他产物。</p>
                            </div>
                            <FileVideo className="text-slate-500" size={32} />
                        </div>

                        {message && (
                            <div className="mb-5 px-4 py-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-300 flex items-center gap-2">
                                <CheckCircle size={18} />
                                {message}
                            </div>
                        )}

                        {job ? (
                            <div className="space-y-5">
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                    <Metric label="状态" value={job.status} />
                                    <Metric label="阶段" value={job.current_stage} />
                                    <Metric label="进度" value={`${Math.round(job.progress)}%`} />
                                    <Metric label="语言" value={job.target_languages.join(', ')} />
                                </div>

                                {job.status === 'completed' && primaryVideoUrl && (
                                    <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-4">
                                        <div className="flex items-center justify-between gap-3 mb-3">
                                            <div>
                                                <div className="text-sm text-slate-400">成片预览</div>
                                                <div className="text-white font-medium">{primaryLanguage}.mp4</div>
                                            </div>
                                            <div className="flex gap-2">
                                                <a
                                                    href={primaryVideoUrl}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    className="px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-white flex items-center gap-2"
                                                >
                                                    <ExternalLink size={16} />
                                                    打开
                                                </a>
                                                <a
                                                    href={primaryVideoUrl}
                                                    download
                                                    className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-white flex items-center gap-2"
                                                >
                                                    <Download size={16} />
                                                    下载
                                                </a>
                                            </div>
                                        </div>
                                        <video src={primaryVideoUrl} controls className="w-full max-h-[560px] rounded-lg bg-black" />
                                    </div>
                                )}

                                <div className="space-y-3">
                                    {job.target_languages.map((language) => (
                                        <LanguageAssets key={language} job={job} language={language} />
                                    ))}
                                    <Artifact label="剧情理解 JSON" value={storyContextUrl} href={storyContextUrl} />
                                    <Artifact label="转写 JSON" value={job.transcript_path} href={toStorageUrl(job.transcript_path)} />
                                    <Artifact label="审核报告" value={job.moderation_report_path} href={reportUrl} />
                                    {job.status !== 'completed' && job.error_message && (
                                        <Artifact label="错误信息" value={job.error_message} />
                                    )}
                                </div>
                            </div>
                        ) : (
                            <div className="h-80 border border-dashed border-slate-700 rounded-2xl flex flex-col items-center justify-center text-center px-6">
                                <AlertCircle className="text-slate-600 mb-4" size={44} />
                                <h3 className="text-lg font-semibold text-slate-300 mb-2">还没有译制任务</h3>
                                <p className="text-slate-500">选择项目并上传源片后，点击开始译制即可生成一套可检查的出海产物。</p>
                            </div>
                        )}
                    </motion.div>
                </div>
            </div>
        </div>
    );
};

const Metric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
    <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-4">
        <div className="text-xs text-slate-500 mb-1">{label}</div>
        <div className="text-sm text-white break-words">{value}</div>
    </div>
);

const LanguageAssets: React.FC<{ job: LocalizationJob; language: string }> = ({ job, language }) => (
    <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-4">
        <div className="flex items-center justify-between gap-3">
            <div>
                <div className="text-sm text-slate-400 mb-1">{language} 输出</div>
                <div className="text-sm text-slate-200 break-all">{job.rendered_video_dir || '尚未生成'}</div>
            </div>
            <div className="flex flex-wrap gap-2 justify-end">
                <AssetLink icon={<FileVideo size={16} />} label="视频" href={buildRenderedVideoUrl(job, language)} />
                <AssetLink icon={<FileText size={16} />} label="字幕" href={buildSubtitleUrl(job, language)} />
            </div>
        </div>
    </div>
);

const Artifact: React.FC<{ label: string; value?: string | null; href?: string | null }> = ({ label, value, href }) => (
    <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-4">
        <div className="flex items-center justify-between gap-3">
            <div>
                <div className="text-sm text-slate-400 mb-1">{label}</div>
                <div className="text-sm text-slate-200 break-all">{value || '尚未生成'}</div>
            </div>
            <AssetLink icon={<ExternalLink size={16} />} label="打开" href={href} />
        </div>
    </div>
);

const AssetLink: React.FC<{ icon: React.ReactNode; label: string; href?: string | null }> = ({ icon, label, href }) => {
    if (!href) {
        return (
            <span className="px-3 py-2 bg-slate-800/50 text-slate-500 rounded-lg flex items-center gap-2">
                {icon}
                {label}
            </span>
        );
    }

    return (
        <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-white flex items-center gap-2"
        >
            {icon}
            {label}
        </a>
    );
};
