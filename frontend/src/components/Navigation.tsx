import { NavLink } from 'react-router-dom';
import { Film, Globe2, LogOut } from 'lucide-react';
import { useAuthStore } from '../store/authStore';
export function Navigation() {
    const {user, logout} = useAuthStore();
    return <nav className="wb-nav" aria-label="主导航"><NavLink className="brand" to="/projects"><Film size={22}/>短剧工作台</NavLink><div className="wb-row">
        <NavLink to="/projects">生成短剧</NavLink><NavLink to="/localization"><Globe2 size={16}/>出海译制</NavLink>
        <span className="username wb-muted">{user?.username}</span>
        <button className="wb-icon" title="退出登录" aria-label="退出登录" onClick={logout}><LogOut size={16}/></button>
    </div></nav>;
}
