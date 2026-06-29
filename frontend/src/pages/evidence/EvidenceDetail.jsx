import React, { useCallback, useEffect, useState } from 'react';
import { Link, useParams, NavLink, Outlet } from 'react-router-dom';
import { Copy, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useSdk } from '../../hooks/useSdk';
import { StatusBadge } from './EvidenceList';

const TABS = [
  { to: '', label: 'Overview', end: true, testId: 'tab-overview' },
  { to: 'timeline', label: 'Timeline', testId: 'tab-timeline' },
  { to: 'seal', label: 'Seal', testId: 'tab-seal' },
  { to: 'integrity', label: 'Integrity', testId: 'tab-integrity' },
  { to: 'custody', label: 'Custody', testId: 'tab-custody' },
  { to: 'versions', label: 'Versions', testId: 'tab-versions' },
  { to: 'legal-holds', label: 'Legal Hold', testId: 'tab-legal-holds' },
];

const EvidenceContext = React.createContext(null);
export const useEvidence = () => React.useContext(EvidenceContext);

export default function EvidenceDetail() {
  const { evidenceId } = useParams();
  const sdk = useSdk();
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const it = await sdk.evidence.get(evidenceId);
      setItem(it);
    } catch (e) {
      setError(e?.detail || e?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [evidenceId, sdk]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading) {
    return (
      <div className="text-slate-400 py-12 text-center" data-testid="evidence-detail-loading">
        <Loader2 className="inline w-5 h-5 mr-2 animate-spin" aria-hidden />
        Loading evidence…
      </div>
    );
  }
  if (error) {
    return (
      <div className="text-rose-300 py-12 text-center" data-testid="evidence-detail-error">
        {error}
      </div>
    );
  }
  if (!item) return null;

  return (
    <EvidenceContext.Provider value={{ item, refresh, evidenceId }}>
      <section data-testid="evidence-detail" className="space-y-6">
        <DetailHeader item={item} />
        <nav
          aria-label="Evidence sections"
          className="flex flex-wrap gap-1 border-b border-slate-800"
        >
          {TABS.map((t) => (
            <NavLink
              key={t.label}
              to={t.to}
              end={t.end}
              data-testid={t.testId}
              className={({ isActive }) =>
                [
                  'px-4 py-2 text-sm border-b-2 transition-colors -mb-px',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400',
                  isActive
                    ? 'border-amber-400 text-amber-300'
                    : 'border-transparent text-slate-400 hover:text-slate-200',
                ].join(' ')
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
        <Outlet />
      </section>
    </EvidenceContext.Provider>
  );
}

function DetailHeader({ item }) {
  const copy = (v) => {
    navigator.clipboard?.writeText(v);
    toast.success('Copied');
  };
  return (
    <header className="bg-slate-900/40 border border-slate-800 rounded-lg p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-slate-500 uppercase tracking-wider">
              Evidence
            </span>
            <StatusBadge status={item.status} />
          </div>
          <h2 className="text-xl font-medium text-slate-100 font-mono break-all">
            {item.evidence_id}
          </h2>
          <button
            type="button"
            onClick={() => copy(item.evidence_id)}
            className="mt-1 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded"
            data-testid="copy-evidence-id"
          >
            <Copy className="w-3 h-3" aria-hidden />
            copy id
          </button>
        </div>
      </div>
      <dl className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
        <Field label="Registry">
          <Link
            to={`/evidence?registry_id=${item.registry_id}`}
            className="text-amber-300 hover:underline font-mono"
          >
            {item.registry_id?.slice(0, 14)}…
          </Link>
        </Field>
        <Field label="Kind">{item.kind}</Field>
        <Field label="Media type">{item.media_type || '—'}</Field>
        <Field label="Size">{item.total_size != null ? `${item.total_size} B` : '—'}</Field>
        <Field label="Created">{fmt(item.created_at)}</Field>
        <Field label="Updated">{fmt(item.updated_at)}</Field>
        <Field label="Storage">{item.storage_provider || '—'}</Field>
        <Field label="Version">v{item.version}</Field>
      </dl>
    </header>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <dt className="text-slate-500 uppercase tracking-wider">{label}</dt>
      <dd className="text-slate-200 mt-1 font-mono break-all">{children}</dd>
    </div>
  );
}

function fmt(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// ============================ Overview Tab ============================

export function OverviewTab() {
  const { item } = useEvidence();
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="overview-tab">
      <Section title="Composite hash" testId="overview-composite">
        {item.composite_sha256 ? (
          <code className="text-xs text-emerald-300 break-all">{item.composite_sha256}</code>
        ) : (
          <span className="text-slate-500 text-sm">Not yet computed</span>
        )}
      </Section>
      <Section title="Verification" testId="overview-verification">
        {item.verification ? (
          <div className="text-sm">
            <span
              className={
                item.verification.verified
                  ? 'text-emerald-300'
                  : 'text-rose-300'
              }
            >
              {item.verification.verified ? 'Verified' : 'Not verified'}
            </span>
            <div className="text-xs text-slate-400 mt-1">
              {fmt(item.verification.verified_at)}
            </div>
          </div>
        ) : (
          <span className="text-slate-500 text-sm">No verification yet</span>
        )}
      </Section>
      <Section title="Parts" testId="overview-parts">
        {item.parts_meta?.length ? (
          <ul className="text-xs space-y-1">
            {item.parts_meta.map((p) => (
              <li key={p.part_no} className="font-mono text-slate-300">
                #{p.part_no} · {p.size_bytes} B ·{' '}
                <span className="text-slate-500">{p.sha256?.slice(0, 16)}…</span>
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-slate-500 text-sm">No parts metadata</span>
        )}
      </Section>
      <Section title="Storage" testId="overview-storage">
        <code className="text-xs text-slate-300 break-all">{item.storage_uri || '—'}</code>
      </Section>
    </div>
  );
}

function Section({ title, children, testId }) {
  return (
    <div
      className="border border-slate-800 rounded-lg p-4 bg-slate-900/40"
      data-testid={testId}
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">{title}</h3>
      {children}
    </div>
  );
}

// ============================ Timeline Tab ============================

export function TimelineTab() {
  return <ChainTab fetch="timeline" testId="timeline-tab" titleField="kind" />;
}

// ============================ Custody Tab ============================

export function CustodyTab() {
  return <ChainTab fetch="custody" testId="custody-tab" titleField="action" />;
}

function ChainTab({ fetch, testId, titleField }) {
  const sdk = useSdk();
  const { evidenceId } = useEvidence();
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    sdk.evidence[fetch](evidenceId)
      .then((r) => alive && setChain(r.chain || []))
      .catch((e) => alive && setError(e?.detail || e?.message || 'Failed'));
    return () => {
      alive = false;
    };
  }, [evidenceId, sdk, fetch]);

  if (error) return <div className="text-rose-300" data-testid={`${testId}-error`}>{error}</div>;
  if (chain === null) return <SkeletonChain />;
  if (chain.length === 0) {
    return (
      <p className="text-slate-500 text-sm" data-testid={`${testId}-empty`}>
        No entries — the projection has not received matching events yet.
      </p>
    );
  }
  return (
    <ol
      className="space-y-3"
      data-testid={testId}
      aria-label={`${fetch} chain, ${chain.length} entries`}
    >
      {chain.map((e) => (
        <li
          key={`${e.seq}-${e.entry_hash}`}
          className="border-l-2 border-amber-400/30 pl-4 py-2"
          data-testid={`${testId}-entry-${e.seq}`}
        >
          <div className="flex items-baseline justify-between gap-4">
            <div>
              <span className="text-xs font-mono text-slate-500">#{e.seq}</span>
              <span className="ml-2 text-sm text-slate-100">{e[titleField]}</span>
              {e.actor && (
                <span className="ml-2 text-xs text-slate-500">by {e.actor}</span>
              )}
            </div>
            <time className="text-xs text-slate-500 font-mono">{fmt(e.occurred_at)}</time>
          </div>
          {e.summary && (
            <div className="text-xs text-slate-400 mt-1">{e.summary}</div>
          )}
          {e.justification && (
            <div className="text-xs text-slate-400 mt-1 italic">{e.justification}</div>
          )}
          <div className="text-[10px] font-mono text-slate-600 mt-1 break-all">
            entry_hash {e.entry_hash}
          </div>
        </li>
      ))}
    </ol>
  );
}

function SkeletonChain() {
  return (
    <div className="space-y-3" aria-busy="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-12 bg-slate-900/60 border border-slate-800 rounded animate-pulse" />
      ))}
    </div>
  );
}

// ============================ Seal Status Tab ============================

export function SealTab() {
  const sdk = useSdk();
  const { evidenceId, item } = useEvidence();
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    // Anchor batch lookup is by-seal but we don't have the seal_id on the
    // evidence item DTO — the projection lookup happens via the SDK and
    // the backend joins on the latest seal for the evidence.
    sdk.evidence
      .timeline(evidenceId)
      .then((tl) => {
        if (!alive) return;
        const seal = (tl.chain || []).find((e) => e.kind === 'seal');
        const sealId = seal?.payload?.ref?.seal_id || seal?.payload?.seal_id;
        if (!sealId) return;
        return sdk.evidence.anchorBatchForSeal(sealId).then((b) => alive && setBatch(b));
      })
      .catch((e) => alive && setError(e?.detail || e?.message || 'Failed'));
    return () => {
      alive = false;
    };
  }, [evidenceId, sdk]);

  return (
    <div className="space-y-4" data-testid="seal-tab">
      <Section title="Seal status" testId="seal-status">
        <div className="text-sm text-slate-300">
          Current item status: <StatusBadge status={item.status} />
        </div>
      </Section>
      <Section title="Anchor batch" testId="seal-anchor">
        {error && <div className="text-rose-300 text-sm">{error}</div>}
        {batch ? (
          <div className="text-xs space-y-1 font-mono">
            <div>batch_id: <span className="text-slate-100">{batch.batch_id}</span></div>
            <div>status: <span className="text-amber-300">{batch.status}</span></div>
            <div className="break-all">merkle_root: {batch.merkle_root}</div>
            {batch.confirmed_at && <div>confirmed_at: {fmt(batch.confirmed_at)}</div>}
          </div>
        ) : (
          <span className="text-slate-500 text-sm">No anchor batch yet</span>
        )}
      </Section>
    </div>
  );
}

// ============================ Integrity Tab ============================

export function IntegrityTab() {
  const sdk = useSdk();
  const { evidenceId } = useEvidence();
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    sdk.evidence
      .integrityForEvidence(evidenceId)
      .then((r) => alive && setChain(r.checks || []))
      .catch((e) => alive && setError(e?.detail || e?.message || 'Failed'));
    return () => {
      alive = false;
    };
  }, [evidenceId, sdk]);

  if (error) return <div className="text-rose-300" data-testid="integrity-error">{error}</div>;
  if (chain === null) return <SkeletonChain />;
  return (
    <div data-testid="integrity-tab">
      <p className="text-xs text-slate-400 mb-3">
        Server-side periodic integrity verification — read from projection.
      </p>
      {chain.length === 0 ? (
        <p className="text-slate-500 text-sm" data-testid="integrity-empty">
          No integrity checks recorded.
        </p>
      ) : (
        <ul className="space-y-2">
          {chain.map((c) => (
            <li
              key={c.check_id}
              className="border border-slate-800 rounded p-3 bg-slate-900/40 text-xs font-mono flex items-center justify-between"
              data-testid={`integrity-check-${c.check_id}`}
            >
              <span
                className={
                  c.status === 'PASSED'
                    ? 'text-emerald-300'
                    : c.status === 'FAILED'
                    ? 'text-rose-300'
                    : 'text-slate-300'
                }
              >
                {c.status}
              </span>
              <span className="text-slate-500">{fmt(c.attempted_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ============================ Supersession Tab ============================

export function VersionsTab() {
  const sdk = useSdk();
  const { evidenceId } = useEvidence();
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    sdk.evidence
      .supersessionChain(evidenceId)
      .then((r) => alive && setChain(r.chain || []))
      .catch((e) => alive && setError(e?.detail || e?.message || 'Failed'));
    return () => {
      alive = false;
    };
  }, [evidenceId, sdk]);

  if (error) return <div className="text-rose-300" data-testid="versions-error">{error}</div>;
  if (chain === null) return <SkeletonChain />;
  return (
    <div data-testid="versions-tab">
      <p className="text-xs text-slate-400 mb-3">
        Constitutional invariant: superseded records are never hidden — they remain in the chain.
      </p>
      <ol className="space-y-2">
        {chain.map((link, i) => (
          <li
            key={link.evidence_id}
            className="border border-slate-800 rounded p-3 bg-slate-900/40 text-xs"
            data-testid={`version-${i}`}
          >
            <Link
              to={`/evidence/items/${link.evidence_id}`}
              className="text-amber-300 hover:underline font-mono"
            >
              {link.evidence_id}
            </Link>
            {link.previous_version_id && (
              <div className="text-slate-500 mt-1">
                supersedes {link.previous_version_id.slice(0, 14)}…
              </div>
            )}
            {link.superseded_by && (
              <div className="text-rose-300 mt-1 font-mono">
                superseded by {link.superseded_by.slice(0, 14)}…
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

// ============================ Legal Hold Tab ============================

export function LegalHoldTab() {
  const sdk = useSdk();
  const { evidenceId } = useEvidence();
  const [holds, setHolds] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [caseRef, setCaseRef] = useState('');
  const [reason, setReason] = useState('');

  const refresh = useCallback(async () => {
    try {
      const r = await sdk.evidence.listLegalHolds(evidenceId);
      setHolds(r.holds || []);
    } catch (e) {
      setError(e?.detail || e?.message || 'Failed');
    }
  }, [evidenceId, sdk]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const apply = async (e) => {
    e.preventDefault();
    if (!caseRef.trim() || !reason.trim()) return;
    setCreating(true);
    try {
      await sdk.evidence.applyLegalHold(evidenceId, {
        case_reference: caseRef.trim(),
        reason: reason.trim(),
      });
      setCaseRef('');
      setReason('');
      await refresh();
      toast.success('Legal hold applied');
    } catch (err) {
      toast.error(err?.detail || err?.message || 'Failed to apply');
    } finally {
      setCreating(false);
    }
  };

  const release = async (h) => {
    const r = window.prompt('Release reason?');
    if (!r) return;
    try {
      await sdk.evidence.releaseLegalHold(h.hold_id, { release_reason: r });
      await refresh();
      toast.success('Released');
    } catch (e) {
      toast.error(e?.detail || e?.message || 'Failed');
    }
  };

  if (error) return <div className="text-rose-300" data-testid="legal-holds-error">{error}</div>;
  if (holds === null) return <SkeletonChain />;
  return (
    <div data-testid="legal-holds-tab" className="space-y-6">
      <form
        onSubmit={apply}
        className="border border-slate-800 rounded-lg p-4 bg-slate-900/40 grid grid-cols-1 md:grid-cols-3 gap-3"
        data-testid="legal-hold-apply-form"
      >
        <label className="md:col-span-1 flex flex-col gap-1 text-xs text-slate-300">
          <span>Case reference</span>
          <input
            type="text"
            value={caseRef}
            onChange={(e) => setCaseRef(e.target.value)}
            placeholder="FHC/L/2026/001"
            data-testid="legal-hold-case-ref"
            className="px-2 py-1.5 bg-slate-950 border border-slate-700 rounded text-sm text-slate-100 font-mono focus:outline-none focus:border-amber-400/60"
          />
        </label>
        <label className="md:col-span-1 flex flex-col gap-1 text-xs text-slate-300">
          <span>Reason</span>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Federal High Court order"
            data-testid="legal-hold-reason"
            className="px-2 py-1.5 bg-slate-950 border border-slate-700 rounded text-sm text-slate-100 focus:outline-none focus:border-amber-400/60"
          />
        </label>
        <div className="md:col-span-1 flex items-end">
          <button
            type="submit"
            disabled={creating}
            data-testid="legal-hold-apply-btn"
            className="w-full px-3 py-1.5 bg-rose-400/20 border border-rose-400/40 text-rose-200 text-sm rounded hover:bg-rose-400/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300 disabled:opacity-50"
          >
            {creating ? 'Applying…' : 'Apply hold'}
          </button>
        </div>
      </form>

      {holds.length === 0 ? (
        <p className="text-slate-500 text-sm" data-testid="legal-holds-empty">
          No legal holds on this evidence.
        </p>
      ) : (
        <ul className="space-y-3">
          {holds.map((h) => (
            <li
              key={h.hold_id}
              className="border border-slate-800 rounded p-4 bg-slate-900/40 text-sm"
              data-testid={`legal-hold-${h.hold_id}`}
            >
              <div className="flex items-baseline justify-between gap-4">
                <div>
                  <div className="font-mono text-xs text-slate-500">{h.hold_id}</div>
                  <div className="text-slate-100 mt-1">
                    Case: <span className="font-mono">{h.case_reference}</span>
                  </div>
                  <div className="text-slate-400 text-xs mt-1">{h.reason}</div>
                </div>
                <div className="text-right">
                  <span
                    className={
                      h.status === 'active'
                        ? 'text-rose-300'
                        : 'text-emerald-300'
                    }
                    data-testid={`legal-hold-status-${h.hold_id}`}
                  >
                    {h.status}
                  </span>
                  <div className="text-xs text-slate-500 mt-1">
                    issued {fmt(h.issued_at)}
                  </div>
                  {h.released_at && (
                    <div className="text-xs text-slate-500">released {fmt(h.released_at)}</div>
                  )}
                </div>
              </div>
              {h.status === 'active' && (
                <button
                  type="button"
                  onClick={() => release(h)}
                  data-testid={`legal-hold-release-${h.hold_id}`}
                  className="mt-3 px-3 py-1 text-xs rounded border border-emerald-400/30 text-emerald-300 hover:bg-emerald-400/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
                >
                  Release
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
