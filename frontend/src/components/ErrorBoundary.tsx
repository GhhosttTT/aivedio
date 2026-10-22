import { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryProps {
    children: ReactNode;
}

interface ErrorBoundaryState {
    error: Error | null;
}

/**
 * Keep a render error in one page from blanking the whole workbench.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
    state: ErrorBoundaryState = {error: null};

    static getDerivedStateFromError(error: Error): ErrorBoundaryState {
        return {error};
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        console.error('页面渲染失败', error, info.componentStack);
    }

    render() {
        if (!this.state.error) return this.props.children;
        return (
            <div role="alert" style={{minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#191b1d', color: '#e8e8e8', padding: 24}}>
                <div style={{maxWidth: 560}}>
                    <h1 style={{fontSize: 20, marginBottom: 12}}>页面出错了</h1>
                    <p style={{color: '#b8b8b8', marginBottom: 16}}>{this.state.error.message || '未知错误'}</p>
                    <button className="wb-btn" onClick={() => window.location.reload()}>重新加载</button>
                </div>
            </div>
        );
    }
}
