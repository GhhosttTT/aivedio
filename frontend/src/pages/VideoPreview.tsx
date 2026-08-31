import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Download } from 'lucide-react';
import { projectApi, errorText } from '../api/client';
import { useMediaUrl } from '../components/ProjectMedia';
import type { Project } from '../types';

export function VideoPreview() {
    const {id} = useParams();
    const [project, setProject] = useState<Project | null>(null);
    const [error, setError] = useState('');
    const {url, error: mediaError} = useMediaUrl(Number(id), project?.final_video_path);
    useEffect(() => { projectApi.getProject(Number(id)).then(setProject).catch(e => setError(errorText(e))); }, [id]);
    return <main className="workbench">
        <Link className="wb-row wb-muted" to={`/projects/${id}`}><ArrowLeft size={16}/>返回项目</Link>
        <div className="wb-row wb-between" style={{marginTop: 20}}><h1>{project?.name || '成片预览'}</h1>{url && <a className="wb-button" href={url + '&download=true'} download><Download size={16}/>下载成片</a>}</div>
        {(error || mediaError) && <p role="alert" className="wb-alert">{error || mediaError}</p>}
        {url ? <video className="wb-video" src={url} controls playsInline preload="metadata" aria-label="成片播放器" onError={() => setError('视频无法解码或链接已过期，请刷新页面')}/> : !error && <p role="status" className="wb-muted">{project && !project.final_video_path ? '暂无可播放的成片' : '视频加载中'}</p>}
    </main>;
}
