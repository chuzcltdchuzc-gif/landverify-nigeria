import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Loader2, Camera, Play } from 'lucide-react';
import { toast } from 'sonner';
import { useSdk } from '../../hooks/useSdk';

export default function ProjectionsAdmin() {
  const sdk = useSdk();
  const [projections, setProjections] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const r = await sdk.projections.list();
      setProjections(r.projections || []);
    } catch (e) {
      const code = e?.problem?.code;
      if (e?.status === 401 || e?.status === 403) {
        setError('super_admin only — log in with a privileged account.');
      } else {
        setError(e?.detail || e?.message || 'Failed');
      }
    }
  }, [sdk]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const replay = async (name) => {
    if (!window.confirm(`Replay projection "${name}"? This wipes its rows and rebuilds from the outbox.`)) return;
    setBusy(`replay-${name}`);
    try {
      await sdk.projections.replay(name);
      toast.success(`Replayed ${name}`);
      await refresh();
    } catch (e) {
      toast.error(e?.detail || e?.message || 'Replay failed');
    } finally {
      setBusy(null);
    }
  };

  const snapshot = async (name) => {
    setBusy(`snap-${name}`);
    try {
      await sdk.projections.snapshot(name);
      toast.success(`Snapshot recorded`);
      await refresh();
    } catch (e) {
      toast.error(e?.detail || e?.message || 'Snapshot failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <section data-testid="projections-admin-section">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-medium text-slate-100">Projections</h2>
          <p className="text-sm text-slate-400 mt-1">
            ADR-0010 read models — cursor, lag, snapshot, replay. Super admin
            only.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          data-testid="projections-refresh"
          className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-md border border-slate-700 text-slate-300 hover:text-slate-100 focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <RefreshCw className="w-4 h-4" aria-hidden /> Refresh
        </button>
      </header>

      {error && (
        <div
          className="text-rose-300 text-sm bg-rose-500/10 border border-rose-500/30 rounded p-3 mb-4"
          role="alert"
          data-testid="projections-error"
        >
          {error}
        </div>
      )}

      {projections === null && !error && (
        <div className="text-slate-400">
          <Loader2 className="inline w-4 h-4 animate-spin mr-2" aria-hidden /> Loading…
        </div>
      )}

      {projections && (
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full text-sm" data-testid="projections-table">
            <caption className="sr-only">
              Registered projections, health, lag, replay actions.
            </caption>
            <thead className="bg-slate-900/80 text-slate-400 text-left text-xs uppercase tracking-wider">
              <tr>
                <th scope="col" className="px-4 py-3">Name</th>
                <th scope="col" className="px-4 py-3">v</th>
                <th scope="col" className="px-4 py-3">Delivered</th>
                <th scope="col" className="px-4 py-3">Lag</th>
                <th scope="col" className="px-4 py-3">Rebuilding</th>
                <th scope="col" className="px-4 py-3">Last event</th>
                <th scope="col" className="px-4 py-3">Snapshot</th>
                <th scope="col" className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {projections.map((p) => (
                <tr key={p.name} data-testid={`projection-row-${p.name}`}>
                  <td className="px-4 py-3 font-mono text-amber-300">{p.name}</td>
                  <td className="px-4 py-3 font-mono text-slate-400">{p.version}</td>
                  <td className="px-4 py-3 font-mono text-slate-300">
                    {p.delivered_count}
                  </td>
                  <td className="px-4 py-3 font-mono">
                    <span
                      className={
                        p.lag_events > 0
                          ? 'text-amber-300'
                          : 'text-emerald-300'
                      }
                    >
                      {p.lag_events}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {p.rebuilding ? (
                      <span className="text-amber-300">yes</span>
                    ) : (
                      <span className="text-slate-500">no</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-slate-400">
                    {p.last_event_type || '—'}
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-slate-400">
                    {p.last_snapshot_at ? p.last_snapshot_at.slice(0, 19) : '—'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex gap-2">
                      <button
                        type="button"
                        onClick={() => snapshot(p.name)}
                        disabled={busy?.startsWith('snap')}
                        data-testid={`projection-snapshot-${p.name}`}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded border border-slate-700 text-slate-300 hover:border-slate-500 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-amber-400"
                      >
                        <Camera className="w-3 h-3" aria-hidden />
                        Snapshot
                      </button>
                      <button
                        type="button"
                        onClick={() => replay(p.name)}
                        disabled={busy?.startsWith('replay')}
                        data-testid={`projection-replay-${p.name}`}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded border border-amber-400/40 text-amber-300 hover:bg-amber-400/10 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-amber-400"
                      >
                        <Play className="w-3 h-3" aria-hidden />
                        Replay
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
