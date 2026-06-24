import React, { useEffect, useState } from 'react';
import { Activity, Users, Map, FileText, ShieldCheck, Briefcase, BadgeCheck, Search, Play } from 'lucide-react';
import AppShell from '../components/AppShell.jsx';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';
import { toast } from 'sonner';
import { api, statusColor, formatDate, NGN } from '../lib/api';
import { TID } from '../lib/testIds';

export default function AdminDashboard() {
    const [overview, setOverview] = useState(null);
    const [trust, setTrust] = useState(null);
    const [readiness, setReadiness] = useState(null);
    const [users, setUsers] = useState([]);
    const [parcels, setParcels] = useState([]);
    const [evidence, setEvidence] = useState([]);
    const [jobs, setJobs] = useState([]);
    const [audits, setAudits] = useState([]);
    const [busy, setBusy] = useState(false);

    const loadAll = async () => {
        try {
            const [o, t, r, u, p, e, j, a] = await Promise.all([
                api.get('/admin/overview'),
                api.get('/admin/trust/latest'),
                api.get('/admin/readiness'),
                api.get('/admin/users'),
                api.get('/admin/parcels'),
                api.get('/admin/evidence'),
                api.get('/admin/jobs'),
                api.get('/admin/audit-logs'),
            ]);
            setOverview(o.data); setTrust(t.data.run); setReadiness(r.data);
            setUsers(u.data.items); setParcels(p.data.items); setEvidence(e.data.items);
            setJobs(j.data.items); setAudits(a.data.items);
        } catch (err) { toast.error('Admin load failed'); }
    };
    useEffect(() => { loadAll(); }, []);

    const runTrust = async () => {
        try { setBusy(true); const { data } = await api.post('/admin/trust/run');
            setTrust(data.run); toast.success('Trust validation re-run.'); } finally { setBusy(false); }
    };
    const processJobs = async () => {
        try { setBusy(true); const { data } = await api.post('/admin/jobs/process');
            toast.success(`${data.processed} job(s) processed.`); await loadAll(); } finally { setBusy(false); }
    };
    const securityScan = async () => {
        try { setBusy(true); const { data } = await api.post('/admin/security/scan');
            toast.success(`Scan complete · ${data.issues.length} issue(s).`); } finally { setBusy(false); }
    };
    const approveEvidence = async (id) => {
        try { await api.post(`/admin/evidence/${id}/approve`); toast.success('Evidence approved.'); await loadAll(); }
        catch (e) { toast.error('Approve failed'); }
    };

    if (!overview || !trust || !readiness) return <AppShell title="Loading Command Centre…" subtitle="Admin"/>;

    return (
        <AppShell title="Command Centre" subtitle="Platform Admin">
            <div data-testid={TID.adminDashboard} className="space-y-7">
                {/* Action row */}
                <Card className="lv-card p-4 flex flex-wrap items-center gap-3">
                    <Button onClick={runTrust} disabled={busy}
                        data-testid={TID.adminRunTrust}
                        className="rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a]">
                        <ShieldCheck size={14} className="mr-1"/> Run trust validation
                    </Button>
                    <Button onClick={processJobs} disabled={busy}
                        data-testid={TID.adminProcessJobs}
                        variant="outline"
                        className="rounded-full border-[#1565c0] text-[#1565c0]">
                        <Play size={14} className="mr-1"/> Process job queue
                    </Button>
                    <Button onClick={securityScan} disabled={busy}
                        data-testid={TID.adminSecurityScan}
                        variant="outline"
                        className="rounded-full border-[#c62828] text-[#c62828]">
                        <Search size={14} className="mr-1"/> Run security scan
                    </Button>
                    <div className="ml-auto text-xs font-mono text-[#546e7a]">
                        Version 1.0.0 · NG-PILOT
                    </div>
                </Card>

                {/* KPIs */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <Kpi icon={Users} label="Users" value={overview.kpis.total_users}/>
                    <Kpi icon={Map} label="Parcels" value={`${overview.kpis.verified_parcels}/${overview.kpis.total_parcels}`}/>
                    <Kpi icon={FileText} label="Evidence" value={overview.kpis.total_evidence}/>
                    <Kpi icon={BadgeCheck} label="Open incidents" value={overview.kpis.open_incidents}/>
                </div>

                {/* Trust + Readiness */}
                <div className="grid lg:grid-cols-2 gap-6">
                    <Card className="lv-card p-6">
                        <div className="flex items-center justify-between">
                            <h2 className="font-display text-lg text-[#1a2e1a]">Trust validation</h2>
                            <Badge className={`${statusColor(trust.grade === 'F' ? 'FAILED' : 'OK')} font-mono`}>{trust.grade}</Badge>
                        </div>
                        <div className="flex items-end gap-3 mt-3">
                            <div className="font-display text-5xl text-[#1a2e1a]">{trust.overall_score}</div>
                            <div className="text-sm text-[#546e7a] pb-1">/ 100 · {trust.recommendation}</div>
                        </div>
                        <div className="mt-4 space-y-2">
                            {Object.entries(trust.sub_scores).map(([k,v]) => (
                                <div key={k}>
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="font-mono text-[#546e7a]">{k.replaceAll('_',' ')}</span>
                                        <span className="font-mono text-[#1a2e1a]">{v}%</span>
                                    </div>
                                    <Progress value={v} className="h-1.5"/>
                                </div>
                            ))}
                        </div>
                        {trust.gaps_identified?.length > 0 && (
                            <div className="mt-4 text-xs text-[#546e7a]">
                                <div className="font-mono uppercase tracking-widest text-[10px] text-[#f57f17]">Gaps</div>
                                <ul className="list-disc pl-4 mt-1">{trust.gaps_identified.map((g) => <li key={g}>{g}</li>)}</ul>
                            </div>
                        )}
                    </Card>

                    <Card className="lv-card p-6">
                        <h2 className="font-display text-lg text-[#1a2e1a]">Take-off readiness</h2>
                        <div className="flex items-end gap-3 mt-3">
                            <div className="font-display text-5xl text-[#1a2e1a]">{readiness.overall_score}</div>
                            <div className="text-sm text-[#546e7a] pb-1">/ 100 · {readiness.readiness_level}</div>
                        </div>
                        <div className="mt-4 space-y-2">
                            {Object.entries(readiness.sub_scores).map(([k,v]) => (
                                <div key={k}>
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="font-mono text-[#546e7a]">{k.replaceAll('_',' ')}</span>
                                        <span className="font-mono text-[#1a2e1a]">{v}%</span>
                                    </div>
                                    <Progress value={v} className="h-1.5"/>
                                </div>
                            ))}
                        </div>
                        {(readiness.blocking_gaps?.length || readiness.non_blocking_gaps?.length) > 0 && (
                            <div className="mt-4 text-xs text-[#546e7a]">
                                {readiness.blocking_gaps?.length > 0 && <>
                                    <div className="font-mono uppercase tracking-widest text-[10px] text-[#c62828]">Blocking</div>
                                    <ul className="list-disc pl-4 mt-1">{readiness.blocking_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
                                </>}
                                {readiness.non_blocking_gaps?.length > 0 && <>
                                    <div className="font-mono uppercase tracking-widest text-[10px] text-[#f57f17] mt-2">Non-blocking</div>
                                    <ul className="list-disc pl-4 mt-1">{readiness.non_blocking_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
                                </>}
                            </div>
                        )}
                    </Card>
                </div>

                {/* 13 layers */}
                <Card className="lv-card p-6">
                    <h2 className="font-display text-lg text-[#1a2e1a]">13-layer infrastructure health</h2>
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 mt-4">
                        {overview.layers.map((l) => (
                            <div key={l.id} className="border border-[#2e7d52]/10 rounded-xl p-3 flex items-center gap-3">
                                <div className={`w-2.5 h-2.5 rounded-full ${l.status === 'OK' ? 'bg-[#2e7d52]' : l.status === 'WARN' ? 'bg-[#f57f17]' : 'bg-[#c62828]'}`}/>
                                <div>
                                    <div className="font-mono text-[10px] text-[#546e7a]">L{l.id}</div>
                                    <div className="text-sm text-[#1a2e1a]">{l.name}</div>
                                </div>
                            </div>
                        ))}
                    </div>
                </Card>

                {/* Tabs */}
                <Card className="lv-card p-6">
                    <Tabs defaultValue="users">
                        <TabsList className="bg-[#2e7d52]/5">
                            <TabsTrigger value="users" data-testid={TID.adminTabUsers}>Users</TabsTrigger>
                            <TabsTrigger value="parcels" data-testid={TID.adminTabParcels}>Parcels</TabsTrigger>
                            <TabsTrigger value="evidence" data-testid={TID.adminTabEvidence}>Evidence</TabsTrigger>
                            <TabsTrigger value="jobs" data-testid={TID.adminTabJobs}>Jobs</TabsTrigger>
                            <TabsTrigger value="audit" data-testid="admin-tab-audit">Audit</TabsTrigger>
                        </TabsList>
                        <TabsContent value="users" className="mt-4">
                            <ScrollTable>
                                <TableHeader><TableRow>
                                    <TableHead>Name</TableHead><TableHead>Email</TableHead><TableHead>Role</TableHead><TableHead>Status</TableHead><TableHead>Joined</TableHead>
                                </TableRow></TableHeader>
                                <TableBody>{users.map((u) => (
                                    <TableRow key={u.user_id}>
                                        <TableCell className="font-medium">{u.name}</TableCell>
                                        <TableCell className="font-mono text-xs">{u.email}</TableCell>
                                        <TableCell><Badge variant="outline" className="font-mono text-[10px]">{u.role}</Badge></TableCell>
                                        <TableCell><Badge className={`${statusColor(u.subscription_status)} font-mono text-[10px]`}>{u.subscription_status}</Badge></TableCell>
                                        <TableCell className="text-xs font-mono">{formatDate(u.created_at)}</TableCell>
                                    </TableRow>
                                ))}</TableBody>
                            </ScrollTable>
                        </TabsContent>
                        <TabsContent value="parcels" className="mt-4">
                            <ScrollTable>
                                <TableHeader><TableRow>
                                    <TableHead>Parcel</TableHead><TableHead>Community</TableHead><TableHead>Status</TableHead><TableHead>Confidence</TableHead><TableHead>Evidence</TableHead><TableHead>Created</TableHead>
                                </TableRow></TableHeader>
                                <TableBody>{parcels.map((p) => (
                                    <TableRow key={p.id}>
                                        <TableCell className="font-mono text-xs">{p.parcel_number}</TableCell>
                                        <TableCell>{p.community}, {p.state}</TableCell>
                                        <TableCell><Badge className={`${statusColor(p.status)} font-mono text-[10px]`}>{p.status}</Badge></TableCell>
                                        <TableCell><span className="font-mono">{p.confidence_score || 0}/100</span></TableCell>
                                        <TableCell><span className="font-mono">{p.evidence_count}</span></TableCell>
                                        <TableCell className="text-xs font-mono">{formatDate(p.created_at)}</TableCell>
                                    </TableRow>
                                ))}</TableBody>
                            </ScrollTable>
                        </TabsContent>
                        <TabsContent value="evidence" className="mt-4">
                            <ScrollTable>
                                <TableHeader><TableRow>
                                    <TableHead>File</TableHead><TableHead>Type</TableHead><TableHead>Hash</TableHead><TableHead>Status</TableHead><TableHead></TableHead>
                                </TableRow></TableHeader>
                                <TableBody>{evidence.map((e) => (
                                    <TableRow key={e.id}>
                                        <TableCell className="text-sm">{e.file_name}</TableCell>
                                        <TableCell><Badge variant="outline" className="font-mono text-[10px]">{e.evidence_type}</Badge></TableCell>
                                        <TableCell className="font-mono text-[10px] text-[#546e7a]">{(e.file_hash || '').slice(0,16)}…</TableCell>
                                        <TableCell><Badge className={`${statusColor(e.status)} font-mono text-[10px]`}>{e.status}</Badge></TableCell>
                                        <TableCell>
                                            {e.status === 'PENDING' && (
                                                <Button size="sm" variant="ghost"
                                                    data-testid={TID.adminApproveEvidence(e.id)}
                                                    onClick={() => approveEvidence(e.id)}
                                                    className="text-[#2e7d52]">Approve</Button>
                                            )}
                                        </TableCell>
                                    </TableRow>
                                ))}</TableBody>
                            </ScrollTable>
                        </TabsContent>
                        <TabsContent value="jobs" className="mt-4">
                            <ScrollTable>
                                <TableHeader><TableRow>
                                    <TableHead>Type</TableHead><TableHead>Status</TableHead><TableHead>Attempts</TableHead><TableHead>Started</TableHead><TableHead>Completed</TableHead>
                                </TableRow></TableHeader>
                                <TableBody>{jobs.map((j) => (
                                    <TableRow key={j.id}>
                                        <TableCell><Badge variant="outline" className="font-mono text-[10px]">{j.job_type}</Badge></TableCell>
                                        <TableCell><Badge className={`${statusColor(j.status)} font-mono text-[10px]`}>{j.status}</Badge></TableCell>
                                        <TableCell className="font-mono text-xs">{j.attempts}/{j.max_attempts}</TableCell>
                                        <TableCell className="text-xs font-mono">{formatDate(j.started_at)}</TableCell>
                                        <TableCell className="text-xs font-mono">{formatDate(j.completed_at)}</TableCell>
                                    </TableRow>
                                ))}</TableBody>
                            </ScrollTable>
                        </TabsContent>
                        <TabsContent value="audit" className="mt-4">
                            <ScrollTable>
                                <TableHeader><TableRow>
                                    <TableHead>Action</TableHead><TableHead>Entity</TableHead><TableHead>User</TableHead><TableHead>When</TableHead>
                                </TableRow></TableHeader>
                                <TableBody>{audits.map((a) => (
                                    <TableRow key={a.id}>
                                        <TableCell><Badge variant="outline" className="font-mono text-[10px]">{a.action}</Badge></TableCell>
                                        <TableCell className="text-sm">{a.entity_type} · <span className="font-mono text-xs text-[#546e7a]">{(a.entity_id||'').slice(0,12)}</span></TableCell>
                                        <TableCell className="text-xs">{a.user_email || '—'}</TableCell>
                                        <TableCell className="text-xs font-mono">{formatDate(a.created_at)}</TableCell>
                                    </TableRow>
                                ))}</TableBody>
                            </ScrollTable>
                        </TabsContent>
                    </Tabs>
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

const ScrollTable = ({ children }) => (
    <div className="max-h-[420px] overflow-auto border border-[#2e7d52]/10 rounded-xl">
        <Table>{children}</Table>
    </div>
);
