import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Shield, ScanSearch, CheckCircle2, XCircle, ArrowLeft } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { api, statusColor, formatDate } from '../lib/api';
import { TID } from '../lib/testIds';
import Footer from '../components/Footer.jsx';
import { Disclaimer } from '../components/AppShell.jsx';

export default function PublicVerify() {
    const [pn, setPn] = useState('');
    const [result, setResult] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);

    const verify = async (e) => {
        e?.preventDefault?.();
        if (!pn.trim()) return;
        setBusy(true); setError(null); setResult(null);
        try {
            const { data } = await api.get(`/public/verify`, { params: { parcel_number: pn.trim() } });
            setResult(data);
        } catch (err) {
            setError(err?.response?.data?.detail || 'Verification failed');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="min-h-screen flex flex-col lv-gradient">
            <header className="px-6 py-4 max-w-[1400px] mx-auto w-full flex items-center justify-between">
                <Link to="/" className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#2e7d52] to-[#1565c0] grid place-items-center text-white"><Shield size={16}/></div>
                    <div>
                        <div className="font-display text-base text-[#1a2e1a]">LandVault</div>
                        <div className="text-[9px] tracking-widest uppercase text-[#546e7a] font-mono">Public Verify</div>
                    </div>
                </Link>
                <Link to="/" className="text-sm text-[#1565c0] hover:underline flex items-center gap-1"><ArrowLeft size={14}/> Back</Link>
            </header>

            <main className="flex-1 max-w-3xl mx-auto w-full px-6 py-8">
                <div className="text-center mb-8">
                    <span className="lv-stamp"><ScanSearch size={12} /> Public Portal</span>
                    <h1 className="font-display text-4xl md:text-5xl text-[#1a2e1a] mt-4">Verify a parcel.</h1>
                    <p className="text-[#546e7a] mt-2 text-sm max-w-md mx-auto">
                        Enter a parcel number to see its evidence status. No personal data is shown.
                    </p>
                </div>

                <Card className="lv-card p-6">
                    <form onSubmit={verify} className="flex flex-col sm:flex-row gap-3">
                        <Input
                            data-testid={TID.verifyInput}
                            value={pn}
                            onChange={(e) => setPn(e.target.value.toUpperCase())}
                            placeholder="AS-LV-2026-XXXX"
                            className="rounded-lg font-mono text-base h-12 border-[#2e7d52]/20 focus:border-[#2e7d52] focus:ring-2 focus:ring-[#2e7d52]/30"
                        />
                        <Button type="submit" disabled={busy}
                            data-testid={TID.verifyBtn}
                            className="rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a] h-12 px-6">
                            {busy ? 'Searching…' : 'Verify'}
                        </Button>
                    </form>
                    <p className="text-xs text-[#546e7a] mt-3 font-mono">
                        Try one of the demo numbers: AS-LV-2026-1000, AS-LV-2026-1001, AS-LV-2026-1002, AS-LV-2026-1003
                    </p>
                </Card>

                {error && (
                    <Card className="lv-card p-4 mt-5 border-l-4 border-[#c62828]">
                        <div className="flex gap-3 items-start text-[#c62828]">
                            <XCircle size={18}/> <div className="text-sm">{error}</div>
                        </div>
                    </Card>
                )}

                {result && (
                    <Card className="lv-card p-6 mt-6" data-testid={TID.verifyResult}>
                        {result.exists ? (
                            <div>
                                <div className="flex items-center justify-between gap-4 flex-wrap">
                                    <span className="lv-stamp" data-testid="verify-stamp-found">
                                        <CheckCircle2 size={12}/> Parcel exists in LandVault
                                    </span>
                                    <Badge className={`${statusColor(result.status)} font-mono`}>{result.status}</Badge>
                                </div>
                                <div className="mt-5 grid sm:grid-cols-2 gap-4">
                                    <Field label="Parcel number" value={<span className="font-mono">{result.parcel_number}</span>} />
                                    <Field label="Confidence score" value={
                                        <span className="font-mono">{result.confidence_score}/100</span>
                                    } />
                                    <Field label="Community" value={result.community} />
                                    <Field label="LGA · State" value={`${result.lga} · ${result.state}`} />
                                    <Field label="Evidence on record" value={`${result.evidence_count}`} />
                                    <Field label="Has attestations" value={result.has_attestations ? 'Yes' : 'No'} />
                                    <Field label="Last update" value={formatDate(result.verified_at)} />
                                </div>
                                <Disclaimer />
                            </div>
                        ) : (
                            <div className="text-center py-8">
                                <XCircle size={40} className="mx-auto text-[#c62828]"/>
                                <div className="font-display text-xl mt-3 text-[#1a2e1a]">Not found</div>
                                <p className="text-sm text-[#546e7a] mt-1">No parcel matches that number in the registry.</p>
                            </div>
                        )}
                    </Card>
                )}
            </main>
            <Footer />
        </div>
    );
}

const Field = ({ label, value }) => (
    <div>
        <div className="text-[10px] uppercase tracking-widest font-mono text-[#546e7a]">{label}</div>
        <div className="text-[#1a2e1a] mt-1 text-sm font-medium">{value || '—'}</div>
    </div>
);
