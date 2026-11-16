import React from 'react';
import { Icon, SkLines } from '@/components/ui';
import type { TenantHealth } from '@/api/platform';

export const compact = (n: number | null | undefined) => {
  if (n === null || n === undefined) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)} M`;
  if (n >= 1e4) return `${Math.round(n / 1e3)}k`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
};
export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(d)}%`);

export const hhmm = (iso: string | null | undefined) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (d.toDateString() === new Date().toDateString()) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};
export const dateShort = (iso: string | null | undefined, year = false) =>
  iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(year ? { year: 'numeric' } : {}) }) : '—';

export const Kpi: React.FC<{ label: string; value: React.ReactNode; sub?: React.ReactNode; loading?: boolean }> = ({ label, value, sub, loading }) => (
  <section className="card">
    <div className="sm muted">{label}</div>
    {loading ? (
      <SkLines lines={2} />
    ) : (
      <>
        <div className="kpi">{value}</div>
        {sub && <div className="sm">{sub}</div>}
      </>
    )}
  </section>
);

export const Health: React.FC<{ health: TenantHealth; label?: string | null; suspended?: boolean }> = ({ health, label, suspended }) => {
  if (suspended) return <span className="muted">● Suspended</span>;
  if (!health) return <span className="muted">● —</span>;
  const cls = health === 'healthy' ? 'ok' : health === 'down' ? 'err' : 'warn';
  return <span className={cls}>● {health === 'healthy' ? 'Healthy' : label ?? (health === 'quota' ? 'Quota' : health === 'down' ? 'Down' : 'Degraded')}</span>;
};

export const RoleBadge: React.FC<{ role?: 'superuser' | 'admin' | null; long?: boolean }> = ({ role, long }) =>
  role === 'superuser' ? <span className="lbl sa">{long ? 'Super Admin' : 'SA'}</span> : role === 'admin' ? <span className="lbl role-pa">{long ? 'Platform Admin' : 'PA'}</span> : null;

export const Sev: React.FC<{ s: 'high' | 'medium' | 'low' | 'info' }> = ({ s }) => (
  <span className={`lbl ${s === 'high' ? 'red' : s === 'medium' ? 'ylw' : 'blue'}`}>{s[0].toUpperCase() + s.slice(1)}</span>
);

export const Note: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="alert" role="note">
    <Icon.Info size={16} />
    <span className="sm">{children}</span>
  </div>
);

/** Said once per screen when the server has no platform API and the view shows this deployment's tenant only. */
export const SingleTenant: React.FC<{ source?: string }> = ({ source }) =>
  source === 'single-tenant' ? (
    <div className="alert warn-a" role="status">
      <span className="sm">
        This server does not run the platform API yet (/api/platform), so Platform Operations shows the one tenant this deployment serves, built from its own data.
        Cross-tenant figures appear once the platform service is deployed.
      </span>
    </div>
  ) : null;
