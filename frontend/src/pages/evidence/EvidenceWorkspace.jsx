import React from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  FileText,
  Upload as UploadIcon,
  ShieldCheck,
  Activity,
  History,
  Users,
  Gavel,
  Database,
  ChevronRight,
} from 'lucide-react';
import { useSdkMeta } from '../../hooks/useSdk';

const NAV = [
  { to: '/evidence', end: true, label: 'List', icon: FileText, testId: 'nav-evidence-list' },
  { to: '/evidence/upload', label: 'Upload', icon: UploadIcon, testId: 'nav-evidence-upload' },
];

const ADMIN_NAV = [
  { to: '/evidence/admin/projections', label: 'Projections', icon: Database, testId: 'nav-projections' },
];

export default function EvidenceWorkspace() {
  const meta = useSdkMeta();
  const location = useLocation();
  return (
    <div
      data-testid="evidence-workspace"
      className="min-h-screen bg-slate-950 text-slate-100"
    >
      <a
        href="#evidence-main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:bg-amber-400 focus:text-slate-900 focus:px-3 focus:py-1 focus:rounded"
      >
        Skip to main content
      </a>
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-6">
          <NavLink
            to="/"
            className="font-mono text-sm uppercase tracking-widest text-amber-400"
            data-testid="brand-link"
          >
            LandVault
          </NavLink>
          <span className="text-slate-500" aria-hidden>•</span>
          <h1
            className="text-base font-medium text-slate-100"
            data-testid="workspace-title"
          >
            Evidence Bounded Context
          </h1>
          <div className="ml-auto text-xs font-mono text-slate-500" data-testid="sdk-meta">
            SDK {meta.sdkVersion} · contract {meta.contractVersion}
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-8 grid grid-cols-1 md:grid-cols-[200px_1fr] gap-8">
        <nav aria-label="Evidence sections" className="space-y-1">
          {NAV.map((n) => (
            <SideLink key={n.to} {...n} />
          ))}
          <div className="mt-6 mb-2 px-3 text-[10px] font-mono uppercase tracking-wider text-slate-500">
            Admin
          </div>
          {ADMIN_NAV.map((n) => (
            <SideLink key={n.to} {...n} />
          ))}
        </nav>

        <main
          id="evidence-main"
          aria-live="polite"
          aria-busy="false"
          className="min-w-0"
          data-testid="evidence-main"
        >
          <Crumbs path={location.pathname} />
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function SideLink({ to, end, label, icon: Icon, testId }) {
  return (
    <NavLink
      to={to}
      end={end}
      data-testid={testId}
      className={({ isActive }) =>
        [
          'group flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400',
          isActive
            ? 'bg-amber-400/10 text-amber-300 border border-amber-400/30'
            : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/60 border border-transparent',
        ].join(' ')
      }
    >
      <Icon className="w-4 h-4" aria-hidden />
      <span>{label}</span>
    </NavLink>
  );
}

function Crumbs({ path }) {
  const parts = path.split('/').filter(Boolean);
  return (
    <ol
      className="flex items-center gap-1 text-xs text-slate-500 mb-4 font-mono"
      aria-label="Breadcrumb"
    >
      {parts.map((p, i) => (
        <React.Fragment key={i}>
          <li>{p}</li>
          {i < parts.length - 1 && (
            <li aria-hidden>
              <ChevronRight className="w-3 h-3" />
            </li>
          )}
        </React.Fragment>
      ))}
    </ol>
  );
}

// Re-export icons for sub-pages.
export { ShieldCheck, Activity, History, Users, Gavel };
