import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ProjectList } from './pages/ProjectList';
import { ProjectDetail } from './pages/ProjectDetail';
import { VideoPreview } from './pages/VideoPreview';
import { LocalizationDashboard } from './pages/LocalizationDashboard';
import { Login } from './pages/Login';
import { Navigation } from './components/Navigation';
import { useAuthStore } from './store/authStore';
import './workbench.css';

export default function App() {
    const {isAuthenticated} = useAuthStore();
    return <BrowserRouter><div style={{minHeight: '100vh', background: '#191b1d'}}>
        {isAuthenticated && <Navigation/>}
        <Routes>
            <Route path="/login" element={isAuthenticated ? <Navigate to="/projects" replace/> : <Login/>}/>
            <Route path="/projects" element={isAuthenticated ? <ProjectList/> : <Navigate to="/login" replace/>}/>
            <Route path="/projects/:id" element={isAuthenticated ? <ProjectDetail/> : <Navigate to="/login" replace/>}/>
            <Route path="/projects/:id/video" element={isAuthenticated ? <VideoPreview/> : <Navigate to="/login" replace/>}/>
            <Route path="/localization" element={isAuthenticated ? <LocalizationDashboard/> : <Navigate to="/login" replace/>}/>
            <Route path="*" element={<Navigate to="/projects" replace/>}/>
        </Routes>
    </div></BrowserRouter>;
}
