import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../lib/auth.jsx';

export default function ProtectedRoute({ children, minRole }) {
    const { user, loading } = useAuth();
    if (loading) {
        return (
            <div className="min-h-screen grid place-items-center">
                <div className="lv-glass p-6 rounded-xl text-sm font-mono">Verifying session…</div>
            </div>
        );
    }
    if (!user) return <Navigate to="/" replace />;
    const ROLE_RANK = { CITIZEN: 1, COMMUNITY_VALIDATOR: 2, SURVEYOR: 3, LEGAL: 4, INSTITUTIONAL: 5, GOVERNMENT_OBSERVER: 6, ADMIN: 7, SUPER_ADMIN: 8 };
    if (minRole && (ROLE_RANK[user.role] || 0) < ROLE_RANK[minRole]) {
        return <Navigate to="/dashboard" replace />;
    }
    return children;
}
