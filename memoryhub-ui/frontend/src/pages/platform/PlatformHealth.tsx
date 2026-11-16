import React from 'react';
import { platform, type HealthResponse } from '@/api/platform';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, SkLines, SkTable } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import { fmtInt } from '@/utils/format';
import { hhmm, Kpi, Note, SingleTenant } from './common';

const STATUS: Record<string, { cls: string; label: string }> = {
  healthy: { cls: 'ok', label: 'Healthy' },
  degraded: { cls: 'warn', label: 'Degraded' },
  down: { cls: 'err', label: 'Down' },
  not_configured: { cls: 'muted', label: 'Not configured' },
};
const DEPLOY: Record<string, { cls: string; label: string }> = {
  done: { cls: 'grn', label: 'Done' },
  running: { cls: 'ylw', label: 'Running' },
  failed: { cls: 'red', label: 'Failed' },
  rolled_back: { cls: 'g', label: 'Rolled back' },
};

const PlatformHealth: React.FC = () => {
  const { data, error, loading, reload } = useApi<HealthResponse>(() => platform.health(), [], 30000);
  const d = data;
  const first = loading && !d;
  const bad = (d?.components ?? []).filter((c) => c.status === 'degraded' || c.status === 'down');
  const failedJobs = (d?.jobs ?? []).reduce((a, j) => a + j.failed, 0);
  return (
    <>
      <PageHeader
        title="Platform health & deployments"
        crumbs={[{ label: 'Platform health & deployments' }]}
        description="Shared services every tenant depends on — MCP, auth, embedding, reranker, database, cache — with the tenants each problem touches, the release that runs, and recent deployments. Aggregates only."
        actions={
          <button type="button" className="btn bs" onClick={reload}>
            Refresh
          </button>
        }
      />
      <div className="body">
        <SingleTenant source={d?.source} />
        {error && !d ? (
          <section className="card">
            <ErrorState error={error} onRetry={reload} />
          </section>
        ) : (
          <>
            <div className="grid-kpi">
              <Kpi loading={first} label="Services" value={d ? `${d.components.length - bad.length} / ${d.components.length}` : '—'} sub="healthy" />
              <Kpi loading={first} label="Degraded or down" value={bad.length} sub={bad.length ? bad.map((b) => b.name).join(' · ') : 'nothing to act on'} />
              <Kpi loading={first} label="Tenants affected" value={bad.reduce((a, b) => Math.max(a, b.tenants_affected ?? 0), 0)} sub="by the worst problem" />
              <Kpi loading={first} label="Failed jobs · 7 d" value={failedJobs} sub="across tenants" />
            </div>
            <div className="row-wrap">
              <div className="col-main" style={{ minWidth: 0 }}>
                <section className="card">
                  <h3>Services</h3>
                  {first ? (
                    <SkTable rows={5} cols={4} />
                  ) : (
                    <table className="tbl mid" style={{ marginTop: 8 }}>
                      <thead>
                        <tr>
                          <th>Service</th>
                          <th>Status</th>
                          <th>Latency</th>
                          <th>Tenants affected</th>
                          <th>Detail</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d!.components.map((c) => (
                          <tr key={c.name}>
                            <td>
                              <b>{c.name}</b>
                            </td>
                            <td className={STATUS[c.status]?.cls}>● {STATUS[c.status]?.label ?? c.status}</td>
                            <td>{c.latency_ms !== null && c.latency_ms !== undefined ? `${fmtInt(c.latency_ms)} ms` : '—'}</td>
                            <td>{c.tenants_affected ?? '—'}</td>
                            <td className="sm muted">{c.detail ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
                <section className="card">
                  <h3>Deployments</h3>
                  {first ? (
                    <SkLines lines={4} />
                  ) : d!.deployments.length === 0 ? (
                    <Empty compact title="No deployment history">The deployment pipeline reports here once the platform service is connected to it.</Empty>
                  ) : (
                    <table className="tbl mid" style={{ marginTop: 8 }}>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Component</th>
                          <th>Version</th>
                          <th>By</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d!.deployments.map((x) => (
                          <tr key={x.id}>
                            <td className="mono">{hhmm(x.time)}</td>
                            <td>{x.component}</td>
                            <td className="mono">{x.version}</td>
                            <td>{x.by}</td>
                            <td>
                              <span className={`lbl ${DEPLOY[x.status]?.cls ?? 'g'}`}>{DEPLOY[x.status]?.label ?? x.status}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
              <aside className="col-side" style={{ flex: '1 1 300px', maxWidth: 400 }}>
                <section className="card">
                  <h3>Release</h3>
                  <dl className="detail-kv nums">
                    <dt>MCP</dt>
                    <dd className="mono">{d?.release.mcp ?? '—'}</dd>
                    <dt>UI</dt>
                    <dd className="mono">{d?.release.ui ?? '—'}</dd>
                    <dt>Migrations</dt>
                    <dd className="mono">{d?.release.migrations ?? '—'}</dd>
                  </dl>
                </section>
                <section className="card">
                  <h3>Background jobs · 7 d</h3>
                  {first ? (
                    <SkLines lines={4} />
                  ) : d!.jobs.length === 0 ? (
                    <p className="sm muted" style={{ marginTop: 10 }}>
                      No jobs reported.
                    </p>
                  ) : (
                    <dl className="detail-kv nums">
                      {d!.jobs.map((j) => (
                        <React.Fragment key={j.kind}>
                          <dt>{j.label}</dt>
                          <dd className={j.failed ? 'err' : ''}>
                            {j.ok} ok{j.failed ? ` · ${j.failed} failed` : ''}
                            {j.running ? ` · ${j.running} running` : ''}
                          </dd>
                        </React.Fragment>
                      ))}
                    </dl>
                  )}
                </section>
                <Note>
                  Model changes are made in <a href={buildHash('/policies', { tab: 'models' })}>Global policies &amp; models</a>; each tenant sees its own retrieval health in its console.
                </Note>
              </aside>
            </div>
          </>
        )}
      </div>
    </>
  );
};

export default PlatformHealth;
