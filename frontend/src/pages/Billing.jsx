import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Wallet, CreditCard, Banknote, Sparkles, CheckCircle2, ArrowRight } from 'lucide-react';
import AppShell from '../components/AppShell.jsx';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { toast } from 'sonner';
import { api, NGN } from '../lib/api';
import { TID } from '../lib/testIds';
import { useAuth } from '../lib/auth.jsx';

export default function Billing() {
    const [plans, setPlans] = useState([]);
    const [packs, setPacks] = useState([]);
    const [config, setConfig] = useState({ stripe: { enabled: false, mode: 'DISABLED' }, paystack: { enabled: false, mode: 'DISABLED' } });
    const [busy, setBusy] = useState(null);
    const { wallet, refresh } = useAuth();

    useEffect(() => {
        api.get('/public/plans').then(({ data }) => { setPlans(data.plans); setPacks(data.credit_packs); }).catch(() => {});
        api.get('/payments/config').then(({ data }) => setConfig(data)).catch(() => {});
    }, []);

    const stripeCheckout = async (kind, code) => {
        if (!config.stripe.enabled) { toast.error('Stripe is not configured'); return; }
        try {
            setBusy(`${kind}-${code}`);
            const body = kind === 'pack' ? { pack_code: code, origin_url: window.location.origin }
                                        : { plan_code: code, billing_cycle: 'monthly', origin_url: window.location.origin };
            const { data } = await api.post('/payments/stripe/checkout', body);
            window.location.href = data.url;
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Stripe checkout failed');
            setBusy(null);
        }
    };

    const paystackCheckout = async (code) => {
        if (!config.paystack.enabled) { toast.error('Paystack is not configured'); return; }
        try {
            setBusy(`paystack-${code}`);
            const { data } = await api.post('/payments/paystack/init',
                { pack_code: code, origin_url: window.location.origin });
            window.location.href = data.authorization_url;
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Paystack init failed');
            setBusy(null);
        }
    };

    return (
        <AppShell title="Plans & Credits" subtitle="Billing">
            <div className="space-y-8">
                <Card className="lv-card p-6 flex flex-wrap items-center gap-4" data-testid="billing-wallet">
                    <div className="w-12 h-12 rounded-xl bg-[#2e7d52]/10 grid place-items-center text-[#2e7d52]"><Wallet size={20}/></div>
                    <div>
                        <div className="text-[10px] font-mono uppercase tracking-widest text-[#2e7d52]">Wallet balance</div>
                        <div className="font-display text-3xl text-[#1a2e1a]">{wallet?.balance ?? 0} <span className="text-base text-[#546e7a] font-sans">credits</span></div>
                    </div>
                    <div className="ml-auto text-xs text-[#546e7a] font-mono flex flex-wrap gap-2">
                        <span className="px-2 py-1 rounded-full border border-[#2e7d52]/20" data-testid="stripe-mode-pill">
                            Stripe: {config.stripe.enabled ? config.stripe.mode : 'NOT CONFIGURED'}
                        </span>
                        <span className="px-2 py-1 rounded-full border border-[#1565c0]/20" data-testid="paystack-mode-pill">
                            Paystack: {config.paystack.enabled ? config.paystack.mode : 'NOT CONFIGURED'}
                        </span>
                    </div>
                </Card>

                {(!config.stripe.enabled || !config.paystack.enabled) && (
                    <Card className="lv-card p-4 border-l-4 border-[#f57f17]" data-testid="payments-not-configured-banner">
                        <div className="text-sm text-[#1a2e1a]">
                            <strong className="font-display">Payment system not fully configured.</strong>
                            <ul className="mt-1 list-disc pl-5 text-[#546e7a] text-xs space-y-0.5">
                                {!config.stripe.enabled && <li>Set <code className="font-mono">STRIPE_SECRET_KEY</code> (and optionally <code className="font-mono">STRIPE_WEBHOOK_SECRET</code>) in the backend env.</li>}
                                {!config.paystack.enabled && <li>Set <code className="font-mono">PAYSTACK_SECRET_KEY</code> (and optionally <code className="font-mono">PAYSTACK_PUBLIC_KEY</code> + <code className="font-mono">PAYSTACK_WEBHOOK_SECRET</code>) in the backend env.</li>}
                            </ul>
                        </div>
                    </Card>
                )}

                <section>
                    <h2 className="font-display text-2xl text-[#1a2e1a]">Credit packs</h2>
                    <p className="text-sm text-[#546e7a] mt-1">Top-up your wallet — credits are spent on actions like parcel upload, attestations, reports.</p>
                    <div className="grid md:grid-cols-3 gap-5 mt-5">
                        {packs.map((p) => (
                            <Card key={p.code} className="lv-card p-6" data-testid={TID.creditPack(p.code)}>
                                <Badge className="bg-[#1565c0]/10 text-[#1565c0] border border-[#1565c0]/20">{p.name}</Badge>
                                <div className="font-display text-4xl text-[#1a2e1a] mt-3">{p.credits}<span className="text-base text-[#546e7a] font-sans"> credits</span></div>
                                <div className="font-mono text-sm text-[#546e7a] mt-1">{NGN(p.price_ngn)} · one-time</div>
                                <div className="mt-5 space-y-2">
                                    <Button onClick={() => stripeCheckout('pack', p.code)}
                                        disabled={!!busy || !config.stripe.enabled}
                                        title={!config.stripe.enabled ? 'Stripe not configured' : ''}
                                        data-testid={TID.creditCheckout(p.code)}
                                        className="w-full rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a] disabled:opacity-50">
                                        <CreditCard size={14} className="mr-2"/>
                                        {config.stripe.enabled ? 'Pay with card (Stripe)' : 'Stripe not configured'}
                                    </Button>
                                    <Button onClick={() => paystackCheckout(p.code)}
                                        disabled={!!busy || !config.paystack.enabled}
                                        title={!config.paystack.enabled ? 'Paystack not configured' : ''}
                                        data-testid={`paystack-${p.code}`}
                                        variant="outline"
                                        className="w-full rounded-full border-[#1565c0] text-[#1565c0] disabled:opacity-50">
                                        <Banknote size={14} className="mr-2"/>
                                        {config.paystack.enabled ? 'Pay with Paystack (NGN)' : 'Paystack not configured'}
                                    </Button>
                                </div>
                            </Card>
                        ))}
                    </div>
                </section>

                <section>
                    <h2 className="font-display text-2xl text-[#1a2e1a]">Subscriptions</h2>
                    <p className="text-sm text-[#546e7a] mt-1">Upgrade your tier for richer access and discounts.</p>
                    <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5 mt-5">
                        {plans.map((p) => (
                            <Card key={p.code} className="lv-card p-6 flex flex-col" data-testid={`billing-plan-${p.code}`}>
                                <Badge className="self-start bg-[#2e7d52]/10 text-[#2e7d52] border border-[#2e7d52]/20">{p.code.replaceAll('_',' ')}</Badge>
                                <h3 className="font-display text-xl text-[#1a2e1a] mt-3">{p.name}</h3>
                                <p className="text-sm text-[#546e7a] mt-1 min-h-[40px]">{p.description}</p>
                                <div className="font-display text-2xl text-[#1a2e1a] mt-3">
                                    {p.monthly_ngn ? NGN(p.monthly_ngn) : 'Invite-only'}
                                    {p.monthly_ngn ? <span className="text-sm text-[#546e7a] font-sans"> /mo</span> : null}
                                </div>
                                <ul className="text-sm text-[#1a2e1a] mt-4 space-y-1.5 flex-1">
                                    {p.features.map((f) => (
                                        <li key={f} className="flex gap-2"><CheckCircle2 size={14} className="text-[#2e7d52] mt-0.5 shrink-0"/>{f}</li>
                                    ))}
                                </ul>
                                <Button onClick={() => stripeCheckout('plan', p.code)}
                                    disabled={!!busy || !p.monthly_ngn || !config.stripe.enabled}
                                    data-testid={`subscribe-${p.code}`}
                                    className="mt-5 rounded-full bg-[#2e7d52] hover:bg-[#1f5a3a] disabled:opacity-50">
                                    {!p.monthly_ngn ? 'Request access'
                                        : !config.stripe.enabled ? 'Stripe not configured'
                                        : <>Subscribe <ArrowRight size={14} className="ml-1"/></>}
                                </Button>
                            </Card>
                        ))}
                    </div>
                </section>
            </div>
        </AppShell>
    );
}

export function BillingSuccess() {
    const [params] = useSearchParams();
    const navigate = useNavigate();
    const { refresh } = useAuth();
    const [status, setStatus] = useState('Verifying payment…');

    useEffect(() => {
        const sessionId = params.get('session_id');
        if (!sessionId) { setStatus('Missing session_id'); return; }
        let attempts = 0;
        const poll = async () => {
            attempts += 1;
            try {
                const { data } = await api.get(`/payments/stripe/status/${sessionId}`);
                if (data.payment_status === 'paid') {
                    setStatus('Payment successful — credits added.');
                    await refresh();
                    setTimeout(() => navigate('/billing', { replace: true }), 1200);
                    return;
                }
                if (data.status === 'expired' || attempts > 6) {
                    setStatus('Payment not completed.'); return;
                }
            } catch { /* ignore */ }
            setTimeout(poll, 2000);
        };
        poll();
    }, [params, navigate, refresh]);

    return (
        <div className="min-h-screen grid place-items-center px-4">
            <div className="lv-glass p-8 rounded-xl max-w-md text-center">
                <Sparkles size={28} className="mx-auto text-[#2e7d52]"/>
                <div className="font-display text-xl mt-3 text-[#1a2e1a]" data-testid="stripe-status">{status}</div>
            </div>
        </div>
    );
}

export function BillingCancel() {
    const navigate = useNavigate();
    useEffect(() => { setTimeout(() => navigate('/billing', { replace: true }), 1500); }, [navigate]);
    return <div className="min-h-screen grid place-items-center"><div className="lv-glass p-6 rounded-xl">Payment cancelled — returning…</div></div>;
}

export function PaystackSuccess() {
    const [params] = useSearchParams();
    const navigate = useNavigate();
    const { refresh } = useAuth();
    const [status, setStatus] = useState('Verifying Paystack…');
    useEffect(() => {
        const reference = params.get('reference') || params.get('trxref');
        if (!reference) { setStatus('Missing reference'); return; }
        api.get(`/payments/paystack/verify/${reference}`).then(async ({ data }) => {
            if (data.verified || data.status === 'success') {
                setStatus('Paystack payment confirmed.');
                await refresh();
                setTimeout(() => navigate('/billing', { replace: true }), 1200);
            } else {
                setStatus(data.message || 'Payment not completed.');
            }
        }).catch(() => setStatus('Verification failed'));
    }, [params, navigate, refresh]);
    return (
        <div className="min-h-screen grid place-items-center px-4">
            <div className="lv-glass p-8 rounded-xl max-w-md text-center">
                <Banknote size={28} className="mx-auto text-[#1565c0]"/>
                <div className="font-display text-xl mt-3 text-[#1a2e1a]" data-testid="paystack-status">{status}</div>
            </div>
        </div>
    );
}
