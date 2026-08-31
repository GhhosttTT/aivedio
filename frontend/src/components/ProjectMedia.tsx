import { useEffect, useState } from 'react';
import { projectApi, errorText } from '../api/client';

export function useMediaUrl(projectId: number, path?: string | null) {
    const [url, setUrl] = useState('');
    const [error, setError] = useState('');
    useEffect(() => {
        let active = true;
        setUrl(''); setError('');
        if (path) projectApi.mediaUrl(projectId, path).then(value => { if (active) setUrl(value); }).catch(e => { if (active) setError(errorText(e)); });
        return () => { active = false; };
    }, [projectId, path]);
    return { url, error };
}

export function ProjectImage({projectId, path, alt}: {projectId: number; path: string; alt: string}) {
    const {url, error} = useMediaUrl(projectId, path);
    return url ? <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={alt} loading="lazy" /></a> : <span role={error ? 'alert' : 'status'}>{error || '图像加载中'}</span>;
}
