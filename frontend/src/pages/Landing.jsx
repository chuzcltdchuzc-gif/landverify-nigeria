import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Shield, CheckCircle2, FileText, Map, Users, Activity, ArrowRight, ScanSearch, Globe2, Layers, Sparkles } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { TID } from '../lib/testIds';
import { api, NGN } from '../lib/api';
import { useAuth, ROLE_ROUTES } from '../lib/auth.jsx';
import { toast } from 'sonner';
import { Disclaimer } from '../components/AppShell.jsx';
import Footer from '../components/Footer.jsx';

const TRUST_STATS_DEFAULT = { total_parcels: 0, verified_parcels: 0, total_attestations: 0, registered_surveyors: 0 };

export default function Landing() {
    const navigate = useNavigate();
    const { user, devLogin } = useAuth();
    const [stats, setStats] = useState(TRUST_STATS_DEFAULT);
    const [plans, setPlans] = useState([]);
    const [busy, setBusy] = useState(null);

    useEffect(() => {
        api.get('/public/stats').then(({ data }) => setStats(data)).catch(() => {});
        api.get('/public/plans').then(({ data }) => setPlans(data.plans || [])).catch(() => {});
    }, []);

    useEffect(() => {
        if (user) navigate(ROLE_ROUTES[user.role] || '/dashboard', { replace: true });
    }, [user, navigate]);

    const handleGoogle = () => {
        // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
        const redirectUrl = window.location.origin + '/dashboard';
        window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
    };

    const handleDemo = async (role) => {
        try {
            setBusy(role);
            const u = await devLogin(role);
            toast.success(`Signed in as ${u.name}`);
            navigate(ROLE_ROUTES[u.role] || '/dashboard');
        } catch (e) {
            toast.error('Demo sign-in failed');
        } finally {
            setBusy(null);
        }
    };

    return (
        <div className="min-h-screen lv-gradient">
            {/* Hero */}
            <section className="relative grid lg:grid-cols-[1.1fr_0.9fr] min-h-[88vh]" data-testid={TID.landingHero}>
                {/* Left */}
                <div className="relative px-6 md:px-12 lg:px-20 py-10 lg:py-16 flex flex-col">
                    <div className="flex items-center gap-2.5 mb-12">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#2e7d52] to-[#1565c0] grid place-items-center text-white">
                            <Shield size={18} />
                        </div>
                        <div className="leading-tight">
                            <div className="font-display text-xl text-[#1a2e1a]">LandVault</div>
                            <div className="text-[10px] tracking-[0.2em] uppercase text-[#546e7a] font-mono">Aquasavannah · Nigeria</div>
                        </div>
                    </div>

                    <div className="lv-fade-up max-w-2xl">
                        <span className="lv-stamp" data-testid="hero-stamp">
                            <CheckCircle2 size={12} /> Evidence · Transparency · Trust
                        </span>
                        <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl mt-6 text-[#1a2e1a] leading-[1.05]">
                            Nigeria’s evidence layer for <span className="text-[#2e7d52]">land</span> <span className="text-[#1565c0]">history</span>.
                        </h1>
                        <p className="text-[#546e7a] mt-5 text-base md:text-lg leading-relaxed max-w-xl">
                            Aquasavannah LandVault preserves submitted evidence, captures community attestations, and makes
                            parcel history independently verifiable. We do not determine ownership — we record evidence.
                        </p>

                        <div className="mt-7 flex flex-wrap items-center gap-3">
                            <Link to="/verify">
                                <Button className="rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a] text-white px-6 py-6 h-12"
                                    data-testid={TID.landingVerifyCta}>
                                    <ScanSearch size={16} className="mr-2" /> Verify a parcel
                                </Button>
                            </Link>
                            <Link to="/trust">
                                <Button variant="outline" className="rounded-full border-[#1565c0] text-[#1565c0] hover:bg-[#1565c0]/5 px-6 py-6 h-12">
                                    <Layers size={16} className="mr-2" /> Trust architecture
                                </Button>
                            </Link>
                        </div>
                    </div>

                    {/* Floating stats */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-12 max-w-3xl">
                        <Stat label="Parcels recorded" value={stats.total_parcels} icon={Map} />
                        <Stat label="Verified" value={stats.verified_parcels} icon={CheckCircle2} />
                        <Stat label="Community attestations" value={stats.total_attestations} icon={Users} />
                        <Stat label="Surveyors" value={stats.registered_surveyors} icon={Activity} />
                    </div>

                    <div className="mt-auto pt-10 text-xs font-mono text-[#546e7a] uppercase tracking-widest">
                        AS-LV-2026 · Pilot live in 4 states
                    </div>
                </div>

                {/* Right auth card */}
                <div className="relative bg-white/85 backdrop-blur-xl border-l border-[#2e7d52]/10 px-6 md:px-12 py-10 lg:py-16 flex items-center">
                    <div className="w-full max-w-md mx-auto">
                        <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#2e7d52]">Sign in / Sign up</div>
                        <h2 className="font-display text-3xl text-[#1a2e1a] mt-2">Enter the Vault</h2>
                        <p className="text-sm text-[#546e7a] mt-2 max-w-sm">
                            Choose how you’d like to continue. New here? Your role is selected during onboarding.
                        </p>

                        <Button onClick={handleGoogle}
                            data-testid={TID.googleLogin}
                            className="mt-7 w-full rounded-full h-12 bg-white border border-[#2e7d52]/15 text-[#1a2e1a] hover:bg-[#2e7d52]/5 shadow-none">
                            <GoogleIcon /> <span className="ml-2 font-medium">Continue with Google</span>
                        </Button>

                        <div className="grid grid-cols-3 gap-2 mt-3">
                            <SocialBtn label="Apple" disabled />
                            <SocialBtn label="Microsoft" disabled />
                            <SocialBtn label="Facebook" disabled />
                        </div>

                        <div className="flex items-center gap-3 my-6">
                            <div className="flex-1 h-px bg-[#2e7d52]/10" />
                            <span className="text-[10px] font-mono uppercase tracking-widest text-[#546e7a]">or demo</span>
                            <div className="flex-1 h-px bg-[#2e7d52]/10" />
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                            <DemoBtn label="Citizen demo" role="CITIZEN" testid={TID.devLoginCitizen} onClick={handleDemo} busy={busy} />
                            <DemoBtn label="Validator demo" role="COMMUNITY_VALIDATOR" testid={TID.devLoginValidator} onClick={handleDemo} busy={busy} />
                            <DemoBtn label="Surveyor demo" role="SURVEYOR" testid={TID.devLoginSurveyor} onClick={handleDemo} busy={busy} />
                            <DemoBtn label="Admin demo" role="ADMIN" testid={TID.devLoginAdmin} onClick={handleDemo} busy={busy} />
                        </div>

                        <p className="text-[11px] text-[#546e7a] mt-5">
                            By continuing you accept our <Link to="/trust" className="text-[#1565c0] underline">trust framework</Link> and
                            acknowledge LandVault is an evidence platform, not a title registry.
                        </p>
                    </div>
                </div>
            </section>

            {/* Pricing */}
            <section className="px-6 md:px-12 lg:px-20 py-16" data-testid={TID.landingPricing}>
                <div className="max-w-[1400px] mx-auto">
                    <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-10">
                        <div>
                            <div className="font-mono text-xs uppercase tracking-[0.25em] text-[#2e7d52]">Subscription tiers</div>
                            <h2 className="font-display text-3xl md:text-4xl text-[#1a2e1a] mt-2">Built for every land actor in Nigeria.</h2>
                        </div>
                        <p className="text-sm text-[#546e7a] max-w-md">
                            Six purpose-built tiers. Switch billing anytime. Annual saves 20%.
                        </p>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {plans.map((p) => (
                            <Card key={p.code} className="lv-card p-6 flex flex-col" data-testid={`plan-card-${p.code}`}>
                                <Badge className="self-start bg-[#2e7d52]/10 text-[#2e7d52] border border-[#2e7d52]/20">{p.code.replaceAll('_',' ')}</Badge>
                                <h3 className="font-display text-xl text-[#1a2e1a] mt-3">{p.name}</h3>
                                <p className="text-sm text-[#546e7a] mt-1 min-h-[40px]">{p.description}</p>
                                <div className="mt-4">
                                    <div className="font-display text-2xl text-[#1a2e1a]">
                                        {p.monthly_ngn ? NGN(p.monthly_ngn) : 'Invite-only'}
                                        {p.monthly_ngn ? <span className="text-sm text-[#546e7a] font-sans"> /mo</span> : null}
                                    </div>
                                    {p.annual_ngn ? (
                                        <div className="text-xs text-[#546e7a] mt-1 font-mono">{NGN(p.annual_ngn)} /yr · save 20%</div>
                                    ) : null}
                                </div>
                                <ul className="text-sm text-[#1a2e1a] mt-4 space-y-1.5 flex-1">
                                    {p.features.map((f) => (
                                        <li key={f} className="flex gap-2"><CheckCircle2 size={14} className="text-[#2e7d52] mt-0.5 shrink-0" /> {f}</li>
                                    ))}
                                </ul>
                                <Button onClick={handleGoogle}
                                    data-testid={`plan-cta-${p.code}`}
                                    className="mt-5 rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a]">
                                    {p.monthly_ngn ? 'Subscribe' : 'Request access'} <ArrowRight size={14} className="ml-2" />
                                </Button>
                            </Card>
                        ))}
                    </div>
                </div>
            </section>

            {/* Trust strip */}
            <section className="px-6 md:px-12 lg:px-20 pb-10">
                <div className="max-w-[1400px] mx-auto lv-glass p-8 rounded-2xl">
                    <div className="grid md:grid-cols-3 gap-6">
                        <Feature icon={FileText} title="SHA-256 sealed evidence"
                            desc="Every upload is hashed server-side. Tampering breaks the chain." />
                        <Feature icon={Users} title="Community attestations"
                            desc="Village chairmen, family heads & traditional rulers attest on record." />
                        <Feature icon={Globe2} title="Public verification"
                            desc="Anyone can verify a parcel number — without leaking personal data." />
                    </div>
                </div>
            </section>

            {/* Final CTA */}
            <section className="px-6 md:px-12 lg:px-20 pb-16">
                <div className="max-w-[1400px] mx-auto bg-gradient-to-r from-[#2e7d52] to-[#1565c0] rounded-2xl p-10 md:p-14 text-white">
                    <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
                        <div>
                            <Sparkles size={20} />
                            <h3 className="font-display text-3xl md:text-4xl mt-2 max-w-2xl">
                                Bring your family land into the evidence layer.
                            </h3>
                            <p className="text-white/85 mt-2 max-w-xl text-sm">
                                Upload your first parcel, capture community attestations, and receive a sealed digital certificate.
                            </p>
                        </div>
                        <Button onClick={handleGoogle} className="rounded-full bg-white text-[#2e7d52] hover:bg-white/90 px-6 h-12">
                            Get started <ArrowRight size={14} className="ml-2" />
                        </Button>
                    </div>
                </div>
            </section>

            <div className="max-w-[1400px] mx-auto px-6 md:px-12 lg:px-20 pb-8">
                <Disclaimer />
            </div>
            <Footer />
        </div>
    );
}

const Stat = ({ label, value, icon: Icon }) => (
    <div className="lv-glass p-4 rounded-xl lv-float" style={{ animationDelay: `${Math.random() * 1.5}s` }}>
        <div className="flex items-center gap-2 text-[#2e7d52]">
            <Icon size={16} />
            <span className="text-[10px] uppercase tracking-widest font-mono">{label}</span>
        </div>
        <div className="font-display text-2xl mt-1 text-[#1a2e1a]">{value}</div>
    </div>
);

const Feature = ({ icon: Icon, title, desc }) => (
    <div>
        <div className="w-10 h-10 rounded-xl bg-[#2e7d52]/10 grid place-items-center text-[#2e7d52]">
            <Icon size={18} />
        </div>
        <h4 className="font-display text-lg text-[#1a2e1a] mt-3">{title}</h4>
        <p className="text-sm text-[#546e7a] mt-1">{desc}</p>
    </div>
);

const SocialBtn = ({ label, disabled }) => (
    <button disabled={disabled}
        data-testid={`social-${label.toLowerCase()}`}
        className="text-xs font-medium border border-[#2e7d52]/15 rounded-full py-2 hover:bg-[#2e7d52]/5 disabled:opacity-60 disabled:cursor-not-allowed">
        {label}
    </button>
);

const DemoBtn = ({ label, role, testid, onClick, busy }) => (
    <button data-testid={testid}
        onClick={() => onClick(role)}
        disabled={busy === role}
        className="text-sm font-medium border border-[#1565c0]/25 text-[#1565c0] rounded-full py-2.5 hover:bg-[#1565c0]/5 transition disabled:opacity-60">
        {busy === role ? 'Loading…' : label}
    </button>
);

const GoogleIcon = () => (
    <svg width="18" height="18" viewBox="0 0 48 48" fill="none">
        <path fill="#FFC107" d="M43.6 20.5H42V20.4H24v7.2h11c-1.5 4.2-5.5 7.2-11 7.2-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.1-5.1C33.1 5.7 28.8 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.3-.4-3.5z"/>
        <path fill="#FF3D00" d="M6.3 14.7l5.9 4.3C13.9 15 18.6 12 24 12c3.1 0 5.9 1.2 8 3.1l5.1-5.1C33.1 5.7 28.8 4 24 4 16.3 4 9.7 8.4 6.3 14.7z"/>
        <path fill="#4CAF50" d="M24 44c4.7 0 9-1.6 12.4-4.4l-5.7-4.8C28.9 36 26.6 36.8 24 36.8c-5.4 0-10-3.4-11.6-8l-5.9 4.6C9.7 39.5 16.3 44 24 44z"/>
        <path fill="#1976D2" d="M43.6 20.5H42V20.4H24v7.2h11c-.7 2-2 3.7-3.7 5l5.7 4.8c-.4.4 6-4.4 6-13.4 0-1.2-.1-2.3-.4-3.5z"/>
    </svg>
);
