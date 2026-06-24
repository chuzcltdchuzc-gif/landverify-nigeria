import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Shield, Layers, FileCheck, Users, Map, Activity, ArrowLeft, CheckCircle2 } from 'lucide-react';
import { api } from '../lib/api';
import Footer from '../components/Footer.jsx';
import { Disclaimer } from '../components/AppShell.jsx';

const LAYERS = [
    { n: 1, title: 'Evidence', desc: 'Files are hashed (SHA-256), versioned, and sealed once approved.', icon: FileCheck },
    { n: 2, title: 'Attestation', desc: 'Recognised community voices (village chairmen, family heads, traditional rulers) record statements.', icon: Users },
    { n: 3, title: 'Survey', desc: 'Registered surveyors validate boundaries and upload survey plans with GPS coordinates.', icon: Map },
    { n: 4, title: 'Consensus', desc: 'Confidence scores recalculate from evidence + attestations + survey + endorsements.', icon: Activity },
    { n: 5, title: 'Public proof', desc: 'Anyone can verify a parcel without seeing any personal data.', icon: Shield },
];

export default function Trust() {
    const [stats, setStats] = useState({ total_parcels: 0, verified_parcels: 0, total_attestations: 0, registered_surveyors: 0 });
    useEffect(() => { api.get('/public/stats').then(({ data }) => setStats(data)).catch(() => {}); }, []);

    return (
        <div className="min-h-screen lv-gradient flex flex-col">
            <header className="px-6 py-4 max-w-[1400px] mx-auto w-full flex items-center justify-between">
                <Link to="/" className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#2e7d52] to-[#1565c0] grid place-items-center text-white"><Shield size={16}/></div>
                    <div className="font-display text-base text-[#1a2e1a]">LandVault</div>
                </Link>
                <Link to="/" className="text-sm text-[#1565c0] hover:underline flex items-center gap-1"><ArrowLeft size={14}/> Back</Link>
            </header>

            <main className="flex-1 max-w-5xl mx-auto px-6 py-8">
                <span className="lv-stamp"><Layers size={12}/> Trust Architecture</span>
                <h1 className="font-display text-4xl md:text-5xl mt-4 text-[#1a2e1a]">How a parcel earns trust.</h1>
                <p className="text-[#546e7a] mt-3 max-w-2xl">
                    Trust is layered. Each layer is independently verifiable and cumulatively raises a parcel’s
                    confidence score from 0 to 100.
                </p>

                <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-8">
                    <Stat label="Parcels recorded" value={stats.total_parcels}/>
                    <Stat label="Verified" value={stats.verified_parcels}/>
                    <Stat label="Attestations" value={stats.total_attestations}/>
                    <Stat label="Surveyors" value={stats.registered_surveyors}/>
                </div>

                <div className="mt-12 grid md:grid-cols-2 gap-5">
                    {LAYERS.map(({ n, title, desc, icon: Icon }) => (
                        <div key={n} className="lv-card p-6 flex gap-4">
                            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[#2e7d52] to-[#1565c0] text-white grid place-items-center font-mono font-bold">L{n}</div>
                            <div>
                                <div className="flex items-center gap-2">
                                    <Icon size={16} className="text-[#2e7d52]"/>
                                    <h3 className="font-display text-lg text-[#1a2e1a]">{title}</h3>
                                </div>
                                <p className="text-sm text-[#546e7a] mt-1">{desc}</p>
                            </div>
                        </div>
                    ))}
                </div>

                <div className="lv-glass p-8 rounded-2xl mt-10">
                    <h2 className="font-display text-2xl text-[#1a2e1a]">Calculation transparency</h2>
                    <p className="text-sm text-[#546e7a] mt-2">
                        Confidence score = evidence (max 30) + attestations (max 30) + survey plan (20) + traditional endorsement (10) + consensus coverage (max 10).
                    </p>
                    <div className="mt-4 grid sm:grid-cols-2 gap-2 text-sm font-mono">
                        <div className="flex items-center gap-2 text-[#2e7d52]"><CheckCircle2 size={14}/> No false 100s — scores reflect real counts.</div>
                        <div className="flex items-center gap-2 text-[#2e7d52]"><CheckCircle2 size={14}/> Tamper-evident SHA-256 chain.</div>
                        <div className="flex items-center gap-2 text-[#2e7d52]"><CheckCircle2 size={14}/> Append-only audit trail.</div>
                        <div className="flex items-center gap-2 text-[#2e7d52]"><CheckCircle2 size={14}/> Public verification, private ownership.</div>
                    </div>
                </div>

                <div className="mt-10"><Disclaimer/></div>
            </main>
            <Footer/>
        </div>
    );
}

const Stat = ({ label, value }) => (
    <div className="lv-card p-4">
        <div className="text-[10px] uppercase tracking-widest font-mono text-[#2e7d52]">{label}</div>
        <div className="font-display text-3xl text-[#1a2e1a] mt-1">{value}</div>
    </div>
);
