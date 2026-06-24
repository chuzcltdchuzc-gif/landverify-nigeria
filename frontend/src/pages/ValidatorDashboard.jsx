import React, { useEffect, useState } from 'react';
import { FileCheck, AlertTriangle, MessageSquareQuote, BadgeCheck } from 'lucide-react';
import AppShell from '../components/AppShell.jsx';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import { api, statusColor, formatDate } from '../lib/api';
import { TID } from '../lib/testIds';

const ROLES = ['FAMILY_HEAD','KINDRED_HEAD','VILLAGE_CHAIRMAN','TRADITIONAL_RULER','CDU','EZE_REPRESENTATIVE',
    'VILLAGE_SECRETARY','LAND_COMMITTEE_MEMBER','RELIGIOUS_LEADER','RECOGNIZED_WITNESS','SURVEYOR_WITNESS','OTHER'];

export default function ValidatorDashboard() {
    const [data, setData] = useState(null);
    const [selectedParcel, setSelectedParcel] = useState(null);
    const [role, setRole] = useState('VILLAGE_CHAIRMAN');
    const [busy, setBusy] = useState(false);

    const load = async () => {
        try { const { data } = await api.get('/dashboard/validator'); setData(data); if (!selectedParcel && data.queue.length) setSelectedParcel(data.queue[0].id); }
        catch (e) { toast.error('Load failed'); }
    };
    useEffect(() => { load(); }, []);

    const submitAttestation = async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const body = Object.fromEntries(fd);
        body.parcel_id = selectedParcel;
        body.role = role;
        body.years_of_knowledge = parseInt(body.years_of_knowledge || '0', 10);
        try {
            setBusy(true);
            await api.post('/attestations', body);
            toast.success('Attestation recorded.');
            e.target.reset();
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Failed to submit attestation');
        } finally { setBusy(false); }
    };

    if (!data) return <AppShell title="Loading…" subtitle="Validator"/>;
    const { kpis, queue, my_attestations, conflicts } = data;

    return (
        <AppShell title="Review Queue" subtitle="Community Validator">
            <div data-testid={TID.validatorDashboard} className="space-y-8">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <Kpi icon={FileCheck} label="In queue" value={kpis.review_queue} />
                    <Kpi icon={MessageSquareQuote} label="My attestations" value={kpis.my_attestations} />
                    <Kpi icon={BadgeCheck} label="Approved" value={kpis.approved} />
                    <Kpi icon={AlertTriangle} label="Conflicts" value={kpis.conflicts} />
                </div>

                <div className="grid lg:grid-cols-[1fr_1.1fr] gap-6">
                    <Card className="lv-card p-5">
                        <h2 className="font-display text-lg text-[#1a2e1a]">Parcels awaiting attestation</h2>
                        <div className="mt-3 space-y-2 max-h-[480px] overflow-y-auto pr-1">
                            {queue.length === 0 && <p className="text-sm text-[#546e7a]">All caught up.</p>}
                            {queue.map((p) => (
                                <button key={p.id}
                                    data-testid={`queue-parcel-${p.id}`}
                                    onClick={() => setSelectedParcel(p.id)}
                                    className={`w-full text-left p-3 rounded-xl border transition
                                        ${selectedParcel === p.id ? 'border-[#2e7d52] bg-[#2e7d52]/5' : 'border-[#2e7d52]/10 hover:bg-[#2e7d52]/3'}`}>
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="font-mono text-sm text-[#1565c0]">{p.parcel_number}</span>
                                        <Badge className={`${statusColor(p.status)} text-[10px] font-mono`}>{p.status}</Badge>
                                    </div>
                                    <div className="text-sm text-[#1a2e1a]">{p.community} · {p.lga}, {p.state}</div>
                                    <div className="text-[11px] text-[#546e7a]">Confidence {p.confidence_score || 0}/100 · {p.attestation_count} attestations</div>
                                </button>
                            ))}
                        </div>
                    </Card>

                    <Card className="lv-card p-6">
                        <h2 className="font-display text-lg text-[#1a2e1a]">Submit attestation</h2>
                        <p className="text-xs text-[#546e7a] mt-1">Minimum 20 characters. Your role and statement become part of the parcel's audit trail.</p>
                        <form onSubmit={submitAttestation} data-testid={TID.attestationForm} className="mt-4 space-y-3">
                            <Field>
                                <Label>Parcel</Label>
                                <Input value={selectedParcel || ''} readOnly data-testid={TID.attestationParcelSelect}
                                    className="font-mono"/>
                            </Field>
                            <Field>
                                <Label>Your role</Label>
                                <Select value={role} onValueChange={setRole}>
                                    <SelectTrigger data-testid={TID.attestationRole}><SelectValue/></SelectTrigger>
                                    <SelectContent>
                                        {ROLES.map((r) => <SelectItem key={r} value={r}>{r.replaceAll('_',' ')}</SelectItem>)}
                                    </SelectContent>
                                </Select>
                            </Field>
                            <Field>
                                <Label>Statement</Label>
                                <Textarea name="statement" required minLength={20} rows={4}
                                    placeholder="I confirm that this land has belonged to the … family for …"
                                    data-testid={TID.attestationStatement}/>
                            </Field>
                            <div className="grid grid-cols-2 gap-3">
                                <Field>
                                    <Label>Relationship to land</Label>
                                    <Input name="relationship_to_land" required placeholder="e.g. Village Chairman"
                                        data-testid={TID.attestationRelationship}/>
                                </Field>
                                <Field>
                                    <Label>Years of knowledge</Label>
                                    <Input name="years_of_knowledge" type="number" min={0} max={100} defaultValue={20} required
                                        data-testid={TID.attestationYears}/>
                                </Field>
                            </div>
                            <Button type="submit" disabled={busy || !selectedParcel}
                                data-testid={TID.attestationSubmit}
                                className="w-full rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a]">
                                {busy ? 'Recording…' : 'Submit attestation'}
                            </Button>
                        </form>
                    </Card>
                </div>

                <Card className="lv-card p-6">
                    <h2 className="font-display text-lg text-[#1a2e1a]">My recent attestations</h2>
                    <div className="mt-3 space-y-2">
                        {my_attestations.length === 0 && <p className="text-sm text-[#546e7a]">No attestations yet.</p>}
                        {my_attestations.slice(0, 10).map((a) => (
                            <div key={a.id} className="flex items-start gap-4 border border-[#2e7d52]/10 rounded-xl p-3">
                                <Badge className={`${statusColor(a.status)} font-mono text-[10px]`}>{a.status}</Badge>
                                <div className="flex-1 min-w-0">
                                    <div className="text-xs font-mono text-[#1565c0]">{a.role} · {a.years_of_knowledge}y</div>
                                    <div className="text-sm text-[#1a2e1a] line-clamp-2">{a.statement}</div>
                                    <div className="text-[11px] text-[#546e7a] mt-1 font-mono">{formatDate(a.created_at)}</div>
                                </div>
                            </div>
                        ))}
                    </div>
                </Card>
            </div>
        </AppShell>
    );
}

const Kpi = ({ icon: Icon, label, value }) => (
    <div className="lv-glass p-5 rounded-xl">
        <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest font-mono text-[#2e7d52]">{label}</span>
            <Icon size={16} className="text-[#2e7d52]"/>
        </div>
        <div className="font-display text-3xl mt-2 text-[#1a2e1a]">{value}</div>
    </div>
);

const Field = ({ children }) => <div className="space-y-1.5">{children}</div>;
