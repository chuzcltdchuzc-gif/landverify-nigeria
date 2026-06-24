import React, { useEffect, useState } from 'react';
import { Map, Activity, Wallet, BadgeCheck } from 'lucide-react';
import AppShell from '../components/AppShell.jsx';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import { api, statusColor, formatDate, NGN } from '../lib/api';
import { TID } from '../lib/testIds';

export default function SurveyorDashboard() {
    const [data, setData] = useState(null);
    const [selected, setSelected] = useState('');
    const [busy, setBusy] = useState(false);

    const load = async () => {
        try {
            const { data } = await api.get('/dashboard/surveyor');
            setData(data);
            if (!selected && data.assignments.length) setSelected(data.assignments[0].id);
        } catch { toast.error('Load failed'); }
    };
    useEffect(() => { load(); }, []);

    const submit = async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const body = Object.fromEntries(fd);
        body.parcel_id = selected;
        try {
            setBusy(true);
            await api.post('/surveyor/upload-plan', body);
            toast.success('Survey plan recorded.');
            e.target.reset();
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Upload failed');
        } finally { setBusy(false); }
    };

    if (!data) return <AppShell title="Loading…" subtitle="Surveyor"/>;
    const { kpis, assignments, recent_surveys } = data;

    return (
        <AppShell title="Field Operations" subtitle="Surveyor Partner">
            <div data-testid={TID.surveyorDashboard} className="space-y-8">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <Kpi icon={Map} label="Open assignments" value={kpis.open_assignments}/>
                    <Kpi icon={BadgeCheck} label="Completed" value={kpis.completed_surveys}/>
                    <Kpi icon={Activity} label="Credits earned" value={kpis.credits_earned}/>
                    <Kpi icon={Wallet} label="Estimated revenue" value={NGN(kpis.revenue_ngn)}/>
                </div>

                <div className="grid lg:grid-cols-[1fr_1.1fr] gap-6">
                    <Card className="lv-card p-5">
                        <h2 className="font-display text-lg text-[#1a2e1a]">Assignments</h2>
                        <div className="mt-3 space-y-2 max-h-[480px] overflow-y-auto pr-1">
                            {assignments.length === 0 && <p className="text-sm text-[#546e7a]">No open assignments right now.</p>}
                            {assignments.map((p) => (
                                <button key={p.id} onClick={() => setSelected(p.id)}
                                    data-testid={`survey-assignment-${p.id}`}
                                    className={`w-full text-left p-3 rounded-xl border transition
                                        ${selected === p.id ? 'border-[#2e7d52] bg-[#2e7d52]/5' : 'border-[#2e7d52]/10 hover:bg-[#2e7d52]/3'}`}>
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="font-mono text-sm text-[#1565c0]">{p.parcel_number}</span>
                                        <Badge className={`${statusColor(p.status)} text-[10px] font-mono`}>{p.status}</Badge>
                                    </div>
                                    <div className="text-sm text-[#1a2e1a]">{p.community} · {p.lga}, {p.state}</div>
                                </button>
                            ))}
                        </div>
                    </Card>

                    <Card className="lv-card p-6">
                        <h2 className="font-display text-lg text-[#1a2e1a]">Upload survey plan</h2>
                        <p className="text-xs text-[#546e7a] mt-1">GPS-stamped survey plans raise confidence by 20 points.</p>
                        <form onSubmit={submit} data-testid={TID.surveyUploadForm} className="mt-4 space-y-3">
                            <Field><Label>Parcel</Label>
                                <Input value={selected} readOnly className="font-mono" data-testid={TID.surveyParcelSelect}/>
                            </Field>
                            <Field><Label>Survey plan URL (PDF / image)</Label>
                                <Input name="plan_url" required placeholder="https://…"
                                    data-testid={TID.surveyPlanUrl}/>
                            </Field>
                            <Field><Label>Field notes</Label>
                                <Textarea name="notes" rows={3} data-testid={TID.surveyNotes} placeholder="Boundary markers, beacon numbers, observations…"/>
                            </Field>
                            <Button type="submit" disabled={busy || !selected}
                                data-testid={TID.surveySubmit}
                                className="w-full rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a]">
                                {busy ? 'Uploading…' : 'Submit survey plan'}
                            </Button>
                        </form>
                    </Card>
                </div>

                <Card className="lv-card p-6">
                    <h2 className="font-display text-lg text-[#1a2e1a]">Recent surveys</h2>
                    <div className="mt-3 space-y-2">
                        {recent_surveys.length === 0 && <p className="text-sm text-[#546e7a]">No completed surveys yet.</p>}
                        {recent_surveys.map((s) => (
                            <div key={s.id} className="flex items-start gap-4 border border-[#2e7d52]/10 rounded-xl p-3">
                                <Badge className={`${statusColor(s.status)} font-mono text-[10px]`}>{s.status}</Badge>
                                <div className="flex-1 min-w-0 text-sm">
                                    <div className="font-mono text-xs text-[#1565c0]">{s.parcel_id}</div>
                                    <div className="text-[#1a2e1a]">{s.notes || 'No notes provided.'}</div>
                                    <div className="text-[11px] text-[#546e7a] font-mono">{formatDate(s.created_at)}</div>
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
