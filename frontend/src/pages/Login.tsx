import { useState } from 'react';
import { Film, LogIn } from 'lucide-react';
import { useAuthStore } from '../store/authStore';
import { authApi, errorText } from '../api/client';
export function Login() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    return <main className="workbench" style={{maxWidth: 450, paddingTop: 100}}>
        <h1 className="wb-row"><Film size={26}/>短剧工作台</h1>
        <form style={{marginTop: 30}} onSubmit={async e => {
            e.preventDefault(); setBusy(true); setError('');
            try { const response = await authApi.login(username, password); useAuthStore.getState().login(response.access_token, response.user); }
            catch(e) { setError(errorText(e)); }
            finally { setBusy(false); }
        }}>
            <label>用户名<input autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)}/></label>
            <label style={{marginTop: 20}}>密码<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)}/></label>
            {error && <p role="alert" className="wb-alert">{error}</p>}
            <button type="submit" className="wb-button primary" style={{marginTop: 24}} disabled={busy}><LogIn size={17}/>{busy ? '登录中' : '登录'}</button>
        </form>
    </main>;
}
