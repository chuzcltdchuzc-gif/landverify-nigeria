import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api } from './api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [wallet, setWallet] = useState(null);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        try {
            const { data } = await api.get('/auth/me');
            setUser(data.user);
            setWallet(data.wallet);
            return data.user;
        } catch {
            setUser(null);
            setWallet(null);
            return null;
        }
    }, []);

    useEffect(() => {
        // If returning from OAuth callback, AuthCallback will exchange session_id first.
        if (typeof window !== 'undefined' && window.location.hash?.includes('session_id=')) {
            setLoading(false);
            return;
        }
        refresh().finally(() => setLoading(false));
    }, [refresh]);

    const logout = useCallback(async () => {
        try { await api.post('/auth/logout'); } catch { /* no-op */ }
        localStorage.removeItem('lv_session_token');
        setUser(null);
        setWallet(null);
    }, []);

    const devLogin = useCallback(async (role) => {
        const { data } = await api.post('/auth/dev-login', { role });
        if (data.session_token) localStorage.setItem('lv_session_token', data.session_token);
        setUser(data.user);
        return data.user;
    }, []);

    return (
        <AuthContext.Provider value={{ user, wallet, loading, refresh, logout, devLogin, setUser }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error('useAuth outside provider');
    return ctx;
};

export const ROLE_ROUTES = {
    CITIZEN: '/dashboard',
    COMMUNITY_VALIDATOR: '/validator',
    SURVEYOR: '/surveyor',
    LEGAL: '/dashboard',
    INSTITUTIONAL: '/dashboard',
    GOVERNMENT_OBSERVER: '/dashboard',
    ADMIN: '/admin',
    SUPER_ADMIN: '/admin',
};
