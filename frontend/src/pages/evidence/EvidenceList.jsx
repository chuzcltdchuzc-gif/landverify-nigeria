import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, Search, Filter, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { useSdk } from '../../hooks/useSdk';

const STATUS_FILTERS = [
  'ALL',
  'PENDING_UPLOAD',
  'PENDING_VERIFICATION',
  'VERIFIED',
  'SEALED',
  'WORM_LOCKED',
  'ARCHIVED_REPLACED',
];

const PAGE_SIZE = 25;

export default function EvidenceList() {
  const sdk = useSdk();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await sdk.evidence.list({
        status: statusFilter === 'ALL' ? undefined : statusFilter,
        page,
        page_size: PAGE_SIZE,
      });
      setItems(res.items || []);
      setTotal(res.total || 0);
    } catch (e) {
      const msg = e?.detail || e?.message || 'Failed to load evidence';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [sdk, statusFilter, page]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!search) return items;
    const s = search.toLowerCase();
    return items.filter(
      (i) =>
        i.evidence_id.toLowerCase().includes(s) ||
        (i.registry_id || '').toLowerCase().includes(s) ||
        (i.kind || '').toLowerCase().includes(s)
    );
  }, [items, search]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section data-testid="evidence-list-section">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-medium text-slate-100">Evidence</h2>
          <p className="text-sm text-slate-400 mt-1">
            Backed by the <code className="text-amber-400">evidence.items</code> read
            model. Projection rebuilds are deterministic.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          data-testid="evidence-refresh-btn"
          aria-label="Refresh list"
          className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-md border border-slate-700 text-slate-300 hover:text-slate-100 hover:border-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <RefreshCw className="w-4 h-4" aria-hidden />
          Refresh
        </button>
      </header>

      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <label className="relative flex-1">
          <span className="sr-only">Search evidence</span>
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500"
            aria-hidden
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by id, registry, kind…"
            data-testid="evidence-search-input"
            className="w-full pl-10 pr-3 py-2 bg-slate-900/80 border border-slate-700 rounded-md text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-amber-400/60 focus:ring-1 focus:ring-amber-400/40"
          />
        </label>
        <label className="inline-flex items-center gap-2 px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-md text-sm text-slate-300">
          <Filter className="w-4 h-4 text-slate-500" aria-hidden />
          <span className="sr-only">Filter by status</span>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            data-testid="evidence-status-filter"
            className="bg-transparent text-slate-100 focus:outline-none"
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s} className="bg-slate-900">
                {s.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-800">
        <table
          className="w-full text-sm"
          data-testid="evidence-table"
          aria-busy={loading ? 'true' : 'false'}
        >
          <caption className="sr-only">
            Evidence items list, paginated server-side from projections.
          </caption>
          <thead className="bg-slate-900/80 text-slate-400 text-left text-xs uppercase tracking-wider">
            <tr>
              <th scope="col" className="px-4 py-3">Evidence</th>
              <th scope="col" className="px-4 py-3">Registry</th>
              <th scope="col" className="px-4 py-3">Kind</th>
              <th scope="col" className="px-4 py-3">Status</th>
              <th scope="col" className="px-4 py-3">Updated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {loading && (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-slate-400">
                  <Loader2 className="w-5 h-5 animate-spin inline-block mr-2" aria-hidden />
                  Loading projection…
                </td>
              </tr>
            )}
            {!loading && error && (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-12 text-center text-rose-300"
                  data-testid="evidence-error"
                >
                  {error}
                </td>
              </tr>
            )}
            {!loading && !error && filtered.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-12 text-center text-slate-500"
                  data-testid="evidence-empty"
                >
                  No evidence items found.
                </td>
              </tr>
            )}
            {!loading &&
              !error &&
              filtered.map((it) => (
                <tr
                  key={it.evidence_id}
                  className="hover:bg-slate-900/40 transition-colors"
                  data-testid={`evidence-row-${it.evidence_id}`}
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/evidence/items/${it.evidence_id}`}
                      className="text-amber-300 hover:text-amber-200 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 font-mono text-xs"
                      data-testid={`evidence-link-${it.evidence_id}`}
                    >
                      {it.evidence_id.slice(0, 18)}…
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">
                    {(it.registry_id || '').slice(0, 18)}…
                  </td>
                  <td className="px-4 py-3 text-slate-300">{it.kind}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={it.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs">
                    {fmt(it.updated_at)}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <nav
        aria-label="Pagination"
        className="flex items-center justify-between mt-4 text-sm text-slate-400"
      >
        <div data-testid="evidence-total">
          {total} item{total !== 1 ? 's' : ''} · page {page} / {totalPages}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            data-testid="evidence-page-prev"
            className="px-3 py-1.5 rounded border border-slate-700 hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            data-testid="evidence-page-next"
            className="px-3 py-1.5 rounded border border-slate-700 hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            Next
          </button>
        </div>
      </nav>
    </section>
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

export function StatusBadge({ status }) {
  const cls =
    {
      VERIFIED: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
      SEALED: 'bg-amber-400/15 text-amber-300 border-amber-400/30',
      WORM_LOCKED: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
      PENDING_UPLOAD: 'bg-slate-700/40 text-slate-300 border-slate-600',
      PENDING_VERIFICATION:
        'bg-violet-500/15 text-violet-300 border-violet-500/30',
      ARCHIVED_REPLACED: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    }[status] || 'bg-slate-700/40 text-slate-300 border-slate-600';
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded border text-[11px] font-mono uppercase tracking-wider ${cls}`}
      data-testid={`status-${status}`}
    >
      {status}
    </span>
  );
}
