import React, { useState } from 'react';
import { platform, type GlobalEvent } from '@/api/platform';
import { PageHeader, Tabs } from '@/components/Shell';
import { Empty, ErrorState, Icon, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import { hhmm, RoleBadge, Sev, SingleTenant } from './common';

const TABS: { value: string; label: string; cat?: GlobalEvent['category'] }[] = [
  { value: 'all', label: 'All events' },
  { value: 'policy', label: 'Policy & config', cat: 'policy' },
  { value: 'deploy', label: 'Deployments', cat: 'deploy' },
  { value: 'admin', label: 'Administrators', cat: 'admin' },
  { value: 'review', label: 'Review oversight', cat: 'review' },
  { value: 'privileged', label: 'Privileged access', cat: 'privileged' },
];

const GlobalAudit: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const p = route.params;
  const tab = TABS.find((t) => t.value === p.get('tab')) ?? TABS[0];
  const [hours, setHours] = useState('24');
  const [tenant, setTenant] = useState('');
  const [sev, setSev] = useState('');
  const [q, setQ] = useState('');
  const { data, error, loading, reload } = useApi(() => platform.audit({ hours: Number(hours), tenant: tenant || undefined }), [hours, tenant]);
  const rows = (data?.items ?? []).filter(
    (e) =>
      (!tab.cat || e.category === tab.cat) &&
      (!sev || e.severity === sev) &&
      (!q || `${e.actor} ${e.tenant} ${e.target} ${e.event}`.toLowerCase().includes(q.toLowerCase())),
  );
  const exportCsv = () => {
    const csv = [['time_utc', 'actor', 'role', 'event', 'tenant', 'target', 'reason', 'severity'], ...rows.map((e) => [e.timestamp, e.actor, e.actor_role ?? '', e.event, e.tenant, e.target, e.reason, e.severity])]
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `memoryhub-global-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    toast(`Exported ${rows.length} events — metadata only.`);
  };
  const r = data?.review;

  return (
    <>
      <PageHeader
        title="Global audit"
        crumbs={[{ label: 'Global audit' }]}
        description="Administrative events across all tenants: policy and deployment changes, admin assignments, review decisions and every use of a privileged grant. Personal text never enters the log."
        actions={
          <button type="button" className="btn bs" onClick={exportCsv} disabled={!data}>
            Export metadata CSV
          </button>
        }
        tabs={<Tabs label="Event type" value={tab.value} onChange={(t) => navigate('/global-audit', t === 'all' ? undefined : { tab: t }, { replace: true })} tabs={TABS.map(({ value, label }) => ({ value, label }))} />}
      />
      <div className="body">
        <SingleTenant source={data?.source} />
        <div className="filters">
          <span className="in-icon">
            <Icon.Search size={15} />
            <label htmlFor="ga-q" className="vh">
              Search
            </label>
            <input id="ga-q" className="in" placeholder="Search actor, tenant, target ID" value={q} onChange={(e) => setQ(e.target.value)} />
          </span>
          <label htmlFor="ga-t" className="vh">
            Tenant
          </label>
          <select id="ga-t" className="in auto" value={tenant} onChange={(e) => setTenant(e.target.value)}>
            <option value="">Tenant: all</option>
            {(data?.tenants ?? []).map((t) => (
              <option key={t} value={t}>
                Tenant: {t}
              </option>
            ))}
          </select>
          <label htmlFor="ga-s" className="vh">
            Severity
          </label>
          <select id="ga-s" className="in auto" value={sev} onChange={(e) => setSev(e.target.value)}>
            <option value="">Severity: all</option>
            <option value="high">Severity: high</option>
            <option value="medium">Severity: medium</option>
            <option value="info">Severity: info</option>
          </select>
          <label htmlFor="ga-h" className="vh">
            Period
          </label>
          <select id="ga-h" className="in auto" value={hours} onChange={(e) => setHours(e.target.value)}>
            <option value="24">Last 24 hours</option>
            <option value="168">Last 7 days</option>
            <option value="720">Last 30 days</option>
          </select>
        </div>
        <section className="card" style={{ padding: '6px 12px' }}>
          {error && !data ? (
            <ErrorState error={error} onRetry={reload} />
          ) : loading && !data ? (
            <SkTable rows={7} cols={7} />
          ) : rows.length === 0 ? (
            <Empty compact title="No events">Nothing matches in this period.</Empty>
          ) : (
            <div className="scroll">
              <table className="tbl mid" style={{ minWidth: 860 }}>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Actor</th>
                    <th>Event</th>
                    <th>Tenant</th>
                    <th>Target</th>
                    <th>Reason</th>
                    <th>Severity</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.id}>
                      <td className="mono">{hhmm(e.timestamp)}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {e.actor} <RoleBadge role={e.actor_role} />
                      </td>
                      <td className="mono sm">{e.event}</td>
                      <td>{e.tenant.replace(/^org-/, '')}</td>
                      <td className="sm">{e.target}</td>
                      <td className="sm">{e.reason}</td>
                      <td>
                        <Sev s={e.severity} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <div className="acc-cards two">
          <section className="card">
            <h2 data-h="3">Review oversight</h2>
            {!r ? (
              <SkLines lines={4} />
            ) : (
              <dl className="detail-kv nums">
                <dt>Decisions · 7 d</dt>
                <dd>{r.decisions_7d ?? '—'}</dd>
                <dt>Overturned on appeal</dt>
                <dd>{r.overturned ?? '—'}</dd>
                <dt>Hard deletes approved</dt>
                <dd>{r.hard_deletes !== null ? `${r.hard_deletes} · both with second admin` : '—'}</dd>
                <dt>Self-decisions blocked</dt>
                <dd>{r.self_blocked ?? '—'}</dd>
              </dl>
            )}
          </section>
          <section className="card">
            <h2 data-h="3">Retention</h2>
            <dl className="detail-kv nums">
              <dt>Administrative events</dt>
              <dd>400 days</dd>
              <dt>Privileged access events</dt>
              <dd>7 years · immutable</dd>
              <dt>Hard-delete entries</dt>
              <dd>sanitized · no deleted text</dd>
            </dl>
          </section>
        </div>
      </div>
    </>
  );
};

export default GlobalAudit;
