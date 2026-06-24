import React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Shield, LayoutDashboard, Users, Map, FileCheck, Activity, Briefcase, LogOut, Wallet, ScrollText, Search } from 'lucide-react';
import { useAuth, ROLE_ROUTES } from '../lib/auth.jsx';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { TID } from '../lib/testIds';
import { NGN } from '../lib/api';
import Footer from './Footer.jsx';

const NAV_BY_ROLE = {
    CITIZEN: [
        { to: '/dashboard', label: 'My LandVault', icon: LayoutDashboard },
        { to: '/billing', label: 'Credits & Plans', icon: Wallet },
        { to: '/verify', label: 'Public Verify', icon: Search },
    ],
    COMMUNITY_VALIDATOR: [
        { to: '/validator', label: 'Review Queue', icon: FileCheck },
        { to: '/dashboard', label: 'My Parcels', icon: LayoutDashboard },
        { to: '/billing', label: 'Credits & Plans', icon: Wallet },
    ],
    SURVEYOR: [
        { to: '/surveyor', label: 'Assignments', icon: Map },
        { to: '/dashboard', label: 'My Parcels', icon: LayoutDashboard },
        { to: '/billing', label: 'Credits & Plans', icon: Wallet },
    ],
    ADMIN: [
        { to: '/admin', label: 'Command Centre', icon: Activity },
        { to: '/admin/users', label: 'Users', icon: Users },
        { to: '/admin/parcels', label: 'Parcels', icon: Map },
        { to: '/admin/evidence', label: 'Evidence', icon: ScrollText },
        { to: '/admin/jobs', label: 'Jobs', icon: Briefcase },
        { to: '/admin/trust', label: 'Trust', icon: Shield },
    ],
};

export default function AppShell({ children, title, subtitle }) {
    const { user, wallet, logout } = useAuth();
    const loc = useLocation();
    const navigate = useNavigate();

    const nav = NAV_BY_ROLE[user?.role] || NAV_BY_ROLE.CITIZEN;

    const handleLogout = async () => {
        await logout();
        navigate('/');
    };

    return (
        <div className="min-h-screen flex flex-col">
            {/* Top bar */}
            <header className="border-b border-[#2e7d52]/10 bg-white/70 backdrop-blur-xl sticky top-0 z-30">
                <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center justify-between gap-4">
                    <Link to="/" className="flex items-center gap-2.5">
                        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#2e7d52] to-[#1565c0] grid place-items-center text-white">
                            <Shield size={18} />
                        </div>
                        <div className="leading-tight">
                            <div className="font-display text-lg text-[#1a2e1a]">LandVault</div>
                            <div className="text-[10px] tracking-widest uppercase text-[#546e7a] font-mono">Aquasavannah</div>
                        </div>
                    </Link>
                    <div className="hidden md:flex items-center gap-2 text-sm">
                        {nav.map((n) => {
                            const Icon = n.icon;
                            const active = loc.pathname === n.to;
                            return (
                                <Link key={n.to} to={n.to}
                                    className={`flex items-center gap-2 px-3 py-1.5 rounded-full transition
                                        ${active ? 'bg-[#2e7d52] text-white' : 'text-[#1a2e1a] hover:bg-[#2e7d52]/10'}`}>
                                    <Icon size={14} /> {n.label}
                                </Link>
                            );
                        })}
                    </div>
                    <div className="flex items-center gap-3">
                        {wallet && (
                            <div className="hidden sm:flex items-center gap-2 bg-white px-3 py-1.5 rounded-full border border-[#2e7d52]/15">
                                <Wallet size={14} className="text-[#2e7d52]" />
                                <span className="font-mono text-xs text-[#1a2e1a]" data-testid="wallet-balance">
                                    {wallet.balance} cr
                                </span>
                            </div>
                        )}
                        {user && (
                            <div className="hidden md:flex flex-col text-right leading-tight">
                                <span className="text-sm font-semibold text-[#1a2e1a]" data-testid="header-user-name">{user.name}</span>
                                <Badge variant="outline" className="text-[10px] font-mono">{user.role}</Badge>
                            </div>
                        )}
                        <Button size="sm" variant="ghost" onClick={handleLogout}
                            data-testid={TID.logoutBtn} className="rounded-full">
                            <LogOut size={14} className="mr-1" /> Sign out
                        </Button>
                    </div>
                </div>
                {/* mobile nav */}
                <div className="md:hidden flex gap-2 overflow-x-auto px-4 pb-3">
                    {nav.map((n) => {
                        const Icon = n.icon;
                        const active = loc.pathname === n.to;
                        return (
                            <Link key={n.to} to={n.to}
                                className={`whitespace-nowrap flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs
                                    ${active ? 'bg-[#2e7d52] text-white' : 'bg-white border border-[#2e7d52]/15 text-[#1a2e1a]'}`}>
                                <Icon size={12} /> {n.label}
                            </Link>
                        );
                    })}
                </div>
            </header>

            <main className="flex-1 max-w-[1400px] w-full mx-auto px-4 md:px-6 py-8">
                {(title || subtitle) && (
                    <div className="mb-7 lv-fade-up">
                        {subtitle && <div className="text-xs font-mono uppercase tracking-widest text-[#2e7d52]">{subtitle}</div>}
                        {title && <h1 className="font-display text-3xl md:text-4xl text-[#1a2e1a] mt-1">{title}</h1>}
                    </div>
                )}
                {children}
            </main>

            <Footer />
        </div>
    );
}

export const Disclaimer = () => (
    <p className="text-[11px] leading-relaxed text-[#546e7a] italic" data-testid="legal-disclaimer">
        Aquasavannah LandVault records submitted evidence and verification events. It does not determine legal
        ownership, adjudicate disputes, or replace government title systems. All records are evidence
        submissions only. Verification of evidence does not constitute proof of ownership.
    </p>
);
