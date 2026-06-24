import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Map, FileText, Users, Shield, Plus, Upload, Wallet, ArrowRight } from 'lucide-react';
import AppShell from '../components/AppShell.jsx';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../components/ui/dialog';
import { Progress } from '../components/ui/progress';
import { toast } from 'sonner';
import { api, statusColor, formatDate } from '../lib/api';
import { TID } from '../lib/testIds';
import { useAuth } from '../lib/auth.jsx';

const EVIDENCE_TYPES = ['SURVEY_PLAN','FAMILY_AGREEMENT','ALLOCATION_LETTER','PHOTO','DEED','AFFIDAVIT','OTHER'];

export default function CitizenDashboard() {
    const { refresh } = useAuth();
    const [data, setData] = useState(null);
    const [parcelDialog, setParcelDialog] = useState(false);
    const [evidenceDialog, setEvidenceDialog] = useState(null); // parcel object or null
    const [evidenceType, setEvidenceType] = useState('FAMILY_AGREEMENT');
    const [busy, setBusy] = useState(false);

    const load = async () => {
        try { const { data } = await api.get('/dashboard/citizen'); setData(data); }
        catch (e) { toast.error('Failed to load dashboard'); }
    };
    useEffect(() => { load(); }, []);

    const createParcel = async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
            setBusy(true);
            await api.post('/parcels', Object.fromEntries(fd), { headers: { 'Idempotency-Key': `parcel-${Date.now()}` } });
            toast.success('Parcel recorded. 5 credits deducted.');
            setParcelDialog(false);
            await Promise.all([load(), refresh()]);
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Could not create parcel');
        } finally { setBusy(false); }
    };

    const uploadEvidence = async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const body = Object.fromEntries(fd);
        body.parcel_id = evidenceDialog.id;
        body.evidence_type = evidenceType;
        try {
            setBusy(true);
            await api.post('/evidence', body);
            toast.success('Evidence sealed with SHA-256.');
            setEvidenceDialog(null);
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Upload failed');
        } finally { setBusy(false); }
    };

    if (!data) return <AppShell title="Loading your vault…" subtitle="Citizen Dashboard" />;

    const { kpis, parcels, wallet, timeline } = data;

    return (
        <AppShell title="Your LandVault" subtitle="Citizen Dashboard">
            <div data-testid={TID.citizenDashboard} className="space-y-8">
                {/* KPI row */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <Kpi testid={TID.kpiMyParcels} icon={Map} label="My parcels" value={kpis.my_parcels}/>
                    <Kpi testid={TID.kpiEvidence} icon={FileText} label="Evidence uploaded" value={kpis.evidence_uploaded}/>
                    <Kpi testid={TID.kpiAttestations} icon={Users} label="Attestations received" value={kpis.attestations_received}/>
                    <Kpi testid={TID.kpiTrust} icon={Shield} label="Avg trust score" value={`${kpis.trust_score}/100`}/>
                </div>

                <div className="grid lg:grid-cols-[1.4fr_1fr] gap-6">
                    {/* Parcels */}
                    <Card className="lv-card p-6">
                        <div className="flex items-center justify-between mb-4">
                            <div>
                                <h2 className="font-display text-xl text-[#1a2e1a]">My parcels</h2>
                                <p className="text-xs text-[#546e7a] mt-1">5 credits per parcel upload</p>
                            </div>
                            <Dialog open={parcelDialog} onOpenChange={setParcelDialog}>
                                <DialogTrigger asChild>
                                    <Button data-testid={TID.createParcelBtn} className="rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a]">
                                        <Plus size={14} className="mr-1"/> Record parcel
                                    </Button>
                                </DialogTrigger>
                                <DialogContent className="sm:max-w-md">
                                    <DialogHeader><DialogTitle className="font-display">Record a new parcel</DialogTitle></DialogHeader>
                                    <form onSubmit={createParcel} data-testid={TID.parcelForm} className="space-y-3">
                                        <Field><Label>Community</Label>
                                            <Input name="community" required data-testid={TID.parcelCommunity}/></Field>
                                        <div className="grid grid-cols-2 gap-3">
                                            <Field><Label>Ward</Label>
                                                <Input name="ward" required data-testid={TID.parcelWard}/></Field>
                                            <Field><Label>LGA</Label>
                                                <Input name="lga" required data-testid={TID.parcelLga}/></Field>
                                        </div>
                                        <Field><Label>State</Label>
                                            <Input name="state" required data-testid={TID.parcelState}/></Field>
                                        <Field><Label>Description (optional)</Label>
                                            <Textarea name="description" rows={3}/></Field>
                                        <Button type="submit" disabled={busy}
                                            data-testid={TID.parcelSubmit}
                                            className="w-full rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a]">
                                            {busy ? 'Saving…' : 'Record parcel (5 credits)'}
                                        </Button>
                                    </form>
                                </DialogContent>
                            </Dialog>
                        </div>

                        <div className="space-y-3">
                            {parcels.length === 0 && (
                                <div className="text-sm text-[#546e7a] py-8 text-center">
                                    No parcels yet. Use "Record parcel" to begin.
                                </div>
                            )}
                            {parcels.map((p) => (
                                <div key={p.id} className="border border-[#2e7d52]/10 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center gap-4"
                                    data-testid={TID.parcelRow}>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="font-mono text-sm text-[#1565c0]">{p.parcel_number}</span>
                                            <Badge className={`${statusColor(p.status)} font-mono text-[10px]`}>{p.status}</Badge>
                                        </div>
                                        <div className="text-sm text-[#1a2e1a] mt-1 truncate">{p.community} · {p.lga}, {p.state}</div>
                                        <div className="text-[11px] text-[#546e7a] mt-1">Created {formatDate(p.created_at)}</div>
                                        <div className="mt-2 flex items-center gap-2">
                                            <Progress value={p.confidence_score || 0} className="h-1.5 flex-1"/>
                                            <span className="font-mono text-[11px] text-[#546e7a]">{p.confidence_score || 0}/100</span>
                                        </div>
                                    </div>
                                    <Button variant="outline" size="sm"
                                        data-testid={TID.uploadEvidenceBtn}
                                        onClick={() => setEvidenceDialog(p)}
                                        className="rounded-full border-[#1565c0] text-[#1565c0]">
                                        <Upload size={12} className="mr-1"/> Upload evidence
                                    </Button>
                                </div>
                            ))}
                        </div>
                    </Card>

                    {/* Right column */}
                    <div className="space-y-6">
                        <Card className="lv-card p-6">
                            <div className="flex items-center justify-between">
                                <h3 className="font-display text-lg text-[#1a2e1a]">Credit wallet</h3>
                                <Wallet size={16} className="text-[#2e7d52]"/>
                            </div>
                            <div className="font-display text-4xl mt-3 text-[#1a2e1a]">{wallet?.balance ?? 0}<span className="text-base text-[#546e7a] font-sans"> credits</span></div>
                            <div className="text-xs text-[#546e7a] mt-1 font-mono">{wallet?.total_consumed ?? 0} consumed · {wallet?.total_purchased ?? 0} purchased</div>
                            <Link to="/billing"><Button className="w-full mt-4 rounded-full bg-[#1565c0] hover:bg-[#0d47a1]"
                                data-testid={TID.buyCreditsBtn}>
                                Buy more credits <ArrowRight size={14} className="ml-1"/>
                            </Button></Link>
                        </Card>

                        <Card className="lv-card p-6">
                            <h3 className="font-display text-lg text-[#1a2e1a]">Recent activity</h3>
                            <div className="mt-3 lv-timeline space-y-3">
                                {timeline.length === 0 && <p className="text-sm text-[#546e7a]">Quiet for now.</p>}
                                {timeline.slice(0, 8).map((t) => (
                                    <div key={t.id} className="relative">
                                        <span className="lv-timeline-dot"/>
                                        <div className="text-[10px] font-mono uppercase tracking-widest text-[#2e7d52]">{t.event_type}</div>
                                        <div className="text-sm text-[#1a2e1a]">{t.description}</div>
                                        <div className="text-[11px] text-[#546e7a] font-mono">{formatDate(t.created_at)}</div>
                                    </div>
                                ))}
                            </div>
                        </Card>
                    </div>
                </div>
            </div>

            {/* Evidence dialog */}
            <Dialog open={!!evidenceDialog} onOpenChange={(v) => !v && setEvidenceDialog(null)}>
                <DialogContent className="sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle className="font-display">
                            Upload evidence for <span className="font-mono text-[#1565c0]">{evidenceDialog?.parcel_number}</span>
                        </DialogTitle>
                    </DialogHeader>
                    {evidenceDialog && (
                        <form onSubmit={uploadEvidence} data-testid={TID.evidenceForm} className="space-y-3">
                            <Field><Label>Evidence type</Label>
                                <Select value={evidenceType} onValueChange={setEvidenceType}>
                                    <SelectTrigger data-testid={TID.evidenceType}><SelectValue/></SelectTrigger>
                                    <SelectContent>
                                        {EVIDENCE_TYPES.map((t) => <SelectItem key={t} value={t}>{t.replaceAll('_',' ')}</SelectItem>)}
                                    </SelectContent>
                                </Select>
                            </Field>
                            <Field><Label>File name</Label>
                                <Input name="file_name" required data-testid={TID.evidenceFileName} placeholder="family-agreement-1998.pdf"/></Field>
                            <Field><Label>File URL (or storage reference)</Label>
                                <Input name="file_url" required data-testid={TID.evidenceFileUrl} placeholder="https://…"/></Field>
                            <Field><Label>Description</Label>
                                <Textarea name="description" rows={2}/></Field>
                            <Button type="submit" disabled={busy}
                                data-testid={TID.evidenceSubmit}
                                className="w-full rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a]">
                                {busy ? 'Sealing…' : 'Seal & submit'}
                            </Button>
                        </form>
                    )}
                </DialogContent>
            </Dialog>
        </AppShell>
    );
}

const Kpi = ({ testid, icon: Icon, label, value }) => (
    <div className="lv-glass p-5 rounded-xl" data-testid={testid}>
        <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest font-mono text-[#2e7d52]">{label}</span>
            <Icon size={16} className="text-[#2e7d52]"/>
        </div>
        <div className="font-display text-3xl mt-2 text-[#1a2e1a]">{value}</div>
    </div>
);

const Field = ({ children }) => <div className="space-y-1.5">{children}</div>;
