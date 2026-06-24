import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Shield, ArrowLeft, Globe2, Users, BadgeCheck } from 'lucide-react';
import { api } from '../lib/api';
import Footer from '../components/Footer.jsx';
import { Disclaimer } from '../components/AppShell.jsx';

export default function CommunityTransparency() {
    const [data, setData] = useState({ by_state: [] });
    useEffect(() => { api.get('/public/transparency').then(({ data }) => setData(data)).catch(()=>{}); }, []);

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
                <span className="lv-stamp"><Globe2 size={12}/> Community Transparency</span>
                <h1 className="font-display text-4xl mt-4 text-[#1a2e1a]">Aggregate activity across Nigeria.</h1>
                <p className="text-[#546e7a] mt-2 max-w-xl">Anonymised state-level overview. Personal data is never exposed.</p>

                <div className="grid md:grid-cols-2 gap-5 mt-8">
                    {data.by_state.map((s) => (
                        <div key={s.state} className="lv-card p-6">
                            <div className="flex items-center justify-between">
                                <div>
                                    <div className="text-xs font-mono uppercase tracking-widest text-[#2e7d52]">State</div>
                                    <h3 className="font-display text-2xl text-[#1a2e1a] mt-1">{s.state}</h3>
                                </div>
                                <BadgeCheck size={22} className="text-[#2e7d52]"/>
                            </div>
                            <div className="mt-4 grid grid-cols-3 gap-3">
                                <Cell label="Parcels" value={s.parcels}/>
                                <Cell label="Verified" value={s.verified}/>
                                <Cell label="Attestations" value={s.attestations}/>
                            </div>
                        </div>
                    ))}
                    {data.by_state.length === 0 && (
                        <div className="lv-card p-8 text-center text-sm text-[#546e7a] md:col-span-2">
                            <Users size={24} className="mx-auto text-[#2e7d52]"/>
                            <p className="mt-3">Community activity will appear as the registry grows.</p>
                        </div>
                    )}
                </div>
                <div className="mt-10"><Disclaimer/></div>
            </main>
            <Footer/>
        </div>
    );
}

const Cell = ({ label, value }) => (
    <div>
        <div className="text-[10px] uppercase font-mono tracking-widest text-[#546e7a]">{label}</div>
        <div className="font-display text-xl text-[#1a2e1a]">{value}</div>
    </div>
);
