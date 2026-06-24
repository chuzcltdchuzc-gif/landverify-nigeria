import React, { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth, ROLE_ROUTES } from '../lib/auth.jsx';

export default function AuthCallback() {
    const location = useLocation();
    const navigate = useNavigate();
    const processed = useRef(false);
    const { refresh } = useAuth();
    const [error, setError] = useState(null);

    useEffect(() => {
        if (processed.current) return;
        processed.current = true;

        const hash = location.hash || window.location.hash;
        const params = new URLSearchParams(hash.replace(/^#/, ''));
        const session_id = params.get('session_id');
        if (!session_id) {
            setError('Missing session_id'); return;
        }

        (async () => {
            try {
                const { data } = await api.post('/auth/session', { session_id });
                const user = await refresh();
                const target = ROLE_ROUTES[user?.role || data.user?.role] || data.redirect || '/dashboard';
                navigate(target, { replace: true });
            } catch (e) {
                setError(e?.response?.data?.detail || e.message || 'Auth failed');
            }
        })();
    }, [location.hash, navigate, refresh]);

    return (
        <div className="min-h-screen grid place-items-center px-4">
            <div className="lv-glass p-8 rounded-xl max-w-md text-center">
                <div className="font-mono text-xs uppercase tracking-widest text-[#2e7d52]">Aquasavannah · Auth</div>
                <div className="font-display text-xl mt-2 text-[#1a2e1a]">
                    {error ? 'Sign-in failed' : 'Verifying your identity…'}
                </div>
                {error && <p className="text-sm text-[#c62828] mt-3">{error}</p>}
                {!error && <p className="text-sm text-[#546e7a] mt-3">Hold tight, securing your session.</p>}
            </div>
        </div>
    );
}
