import React, { useState } from 'react';
import { platform, type PlatformOverview, type TenantSummary } from '@/api/platform';
import { PageHeader } from '@/components/Shell';
import { ErrorState, Icon, ScopeLabel, SkLines, SkTable } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate } from '@/hooks/useHashRoute';
import { fmtInt } from '@/utils/format';
import { compact, Health, hhmm, Kpi, pct, RoleBadge, SingleTenant } from './common';
import { CreateTenantModal, EnterTenantModal } from './Tenants';

const SCOPE_ORDER = ['user', 'project', 'campaign', 'role', 'organizational', 'enterprise'];
const SCOPE_NAME: Record<string, string> = { user: 'User', project: 'Project', campaign: 'Campaign', role: 'Role', organizational: 'Org', enterprise: 'Enterprise' };

const GlobalOverview: React.FC = () => {
  const { data, error, loading, reload } = useApi<PlatformOverview>(() => platform.overview(), [], 60000);
  const [create, setCreate] = useState(false);
  const [enter, setEnter] = useState<TenantSummary | null>(null);
  const d = data;
  const first = loading && !d;
  const n = d?.tenants.length ?? 0;

  return (
    <>
      <PageHeader
        title="Global overview"
        crumbs={[{ label: 'All tenants' }]}
        description={`Is the whole platform secure, stable and correct? Aggregates across ${d ? d.kpis.active_tenants + d.kpis.suspended + d.kpis.onboarding : '…'} tenants, platform health, security incidents and administrative events — no user content. Opening a tenant asks for confirmation and keeps a permanent tenant-context marker.`}
        actions={
          <>
            <button type="button" className="btn bs" onClick={() => setCreate(true)}>
              Create tenant
            </button>
            <a className="btn bp" href={buildHash('/security')}>
              Open security center
            </a>
          </>
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
            {d?.alert && (
              <div className="alert warn-a" role="alert" style={{ alignItems: 'center' }}>
                <Icon.Warn size={16} />
                <span style={{ flex: 1 }}>
                  <b>{d.alert.title}</b>
                  {d.alert.detail ? ` — ${d.alert.detail}` : ''}
                </span>
                <a href={buildHash('/platform-health')}>Platform health</a>
              </div>
            )}
            <div className="kpi-5">
              <Kpi loading={first} label="Active tenants" value={d?.kpis.active_tenants ?? '—'} sub={d && `${d.kpis.suspended} suspended · ${d.kpis.onboarding} onboarding`} />
              <Kpi
                loading={first}
                label="Active users"
                value={d?.kpis.active_users !== null && d?.kpis.active_users !== undefined ? fmtInt(d.kpis.active_users) : '—'}
                sub={d?.kpis.users_trend_pct !== undefined && d?.kpis.users_trend_pct !== null ? `${d.kpis.users_trend_pct >= 0 ? '▲' : '▼'} ${Math.abs(d.kpis.users_trend_pct).toFixed(1)}% vs. last week` : 'with an active account'}
              />
              <Kpi loading={first} label="Connected agents" value={compact(d?.kpis.agents)} sub={d?.kpis.active_sessions !== null && d ? `${fmtInt(d.kpis.active_sessions ?? 0)} active sessions` : undefined} />
              <Kpi loading={first} label="Memory operations · 24 h" value={compact(d?.kpis.ops_24h)} sub={d?.kpis.search_success !== null && d ? `search success ${pct(d.kpis.search_success)}` : 'searches and writes'} />
              <Kpi
                loading={first}
                label="Availability · 30 d"
                value={d?.kpis.availability_30d !== undefined && d?.kpis.availability_30d !== null ? pct(d.kpis.availability_30d, 2) : '—'}
                sub={d?.kpis.slo ? `SLO ${pct(d.kpis.slo)}` : 'needs the platform service'}
              />
            </div>

            <div className="row-wrap">
              <div className="col-main" style={{ minWidth: 0 }}>
                <section className="card">
                  <div className="card-head">
                    <h2 data-h="3">Tenants</h2>
                    <a href={buildHash('/tenants')}>All tenants</a>
                  </div>
                  {first ? (
                    <SkTable rows={5} cols={8} />
                  ) : (
                    <div className="scroll">
                      <table className="tbl mid" style={{ minWidth: 720, marginTop: 8 }}>
                        <thead>
                          <tr>
                            <th>Tenant</th>
                            <th>PAs</th>
                            <th>Users</th>
                            <th>Agents</th>
                            <th>Ops · 24 h</th>
                            <th>Search</th>
                            <th>Storage</th>
                            <th>Health</th>
                            <th>
                              <span className="vh">Actions</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {(d?.tenants ?? []).slice(0, 8).map((t) => {
                            const susp = t.status === 'suspended';
                            return (
                              <tr key={t.id}>
                                <td>
                                  <b>{t.id}</b>
                                  {t.current && <div className="sm muted">this deployment</div>}
                                </td>
                                <td>{t.platform_admins.length}</td>
                                <td>{susp ? '—' : t.users ?? '—'}</td>
                                <td>{susp ? '—' : t.agents ?? '—'}</td>
                                <td>{susp ? '—' : compact(t.ops_24h)}</td>
                                <td>{susp ? '—' : pct(t.search_success)}</td>
                                <td>{t.storage_pct !== null ? `${Math.round(t.storage_pct)}%` : '—'}</td>
                                <td>
                                  <Health health={t.health} label={t.health_label} suspended={susp} />
                                </td>
                                <td style={{ whiteSpace: 'nowrap' }}>
                                  {susp ? (
                                    <a className="link-btn" href={buildHash('/tenants', { tab: 'suspended', tenant: t.id })}>
                                      Resume…
                                    </a>
                                  ) : (
                                    <button type="button" className="link-btn" onClick={() => setEnter(t)}>
                                      Open console
                                    </button>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {d && d.tenants.length > 8 && (
                    <a className="sm" href={buildHash('/tenants')} style={{ display: 'inline-block', marginTop: 10 }}>
                      {n - 8} more tenants →
                    </a>
                  )}
                </section>

                <section className="card">
                  <div className="card-head">
                    <h2 data-h="3">Memories by scope · all tenants</h2>
                    <span className="sm muted">counts only</span>
                  </div>
                  {first ? (
                    <SkLines lines={2} />
                  ) : (
                    <div className="scope-counts">
                      {SCOPE_ORDER.map((s) => (
                        <div key={s}>
                          <ScopeLabel scope={s}>{SCOPE_NAME[s]}</ScopeLabel>
                          <div className="n">{compact(d?.scopes.find((x) => x.scope === s)?.count ?? 0)}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                <section className="card">
                  <div className="card-head">
                    <h2 data-h="3">Global administrative events</h2>
                    <a href={buildHash('/global-audit')}>Global audit</a>
                  </div>
                  {first ? (
                    <SkLines lines={4} />
                  ) : (d?.events ?? []).length === 0 ? (
                    <p className="sm muted" style={{ marginTop: 10 }}>
                      No administrative events in the last days.
                    </p>
                  ) : (
                    <ul className="ev-list">
                      {d!.events.slice(0, 6).map((e) => (
                        <li key={e.id}>
                          <span className="mono muted" style={{ minWidth: 52 }}>
                            {hhmm(e.timestamp)}
                          </span>
                          <span>
                            {e.actor} <RoleBadge role={e.actor_role} /> <span className="mono sm">{e.event}</span> · {e.target}
                            {e.reason && e.reason !== '—' ? ` · ${e.reason}` : ''} · <span className="muted">{e.tenant}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>

              <aside className="col-side" style={{ flex: '1 1 300px', maxWidth: 400 }}>
                <section className="card">
                  <div className="card-head">
                    <h2 data-h="3">Security</h2>
                    <a href={buildHash('/security')}>Security center</a>
                  </div>
                  {first ? (
                    <SkLines lines={5} />
                  ) : (
                    <dl className="detail-kv nums">
                      <dt>Open incidents</dt>
                      <dd>{d!.security.open_incidents}</dd>
                      <dt>Cross-tenant attempts · 24 h</dt>
                      <dd>{d!.security.cross_tenant_24h ? `${d!.security.cross_tenant_24h} · denied` : 0}</dd>
                      <dt>Active incident grants</dt>
                      <dd>
                        {d!.security.active_grants ? (
                          <a href={buildHash('/incident')}>
                            {d!.security.active_grants}
                            {d!.security.grant_expires ? ` · expires ${hhmm(d!.security.grant_expires)}` : ''}
                          </a>
                        ) : (
                          0
                        )}
                      </dd>
                      <dt>Pending grant approvals</dt>
                      <dd>{d!.security.pending_approvals}</dd>
                      <dt>Revoked clients · 24 h</dt>
                      <dd>{d!.security.revoked_clients_24h}</dd>
                    </dl>
                  )}
                </section>
                <section className="card">
                  <div className="card-head">
                    <h2 data-h="3">Administrators</h2>
                    <a href={buildHash('/admins')}>Manage</a>
                  </div>
                  {first ? (
                    <SkLines lines={3} />
                  ) : (
                    <dl className="detail-kv nums">
                      <dt>Super Admins</dt>
                      <dd>
                        {d!.admins.super_admins} · set by {d!.admins.super_source ?? 'deployment'}
                      </dd>
                      <dt>Platform Admins</dt>
                      <dd>
                        {d!.admins.platform_admins} across {d!.admins.tenants} tenant{d!.admins.tenants === 1 ? '' : 's'}
                      </dd>
                      <dt>Without MFA</dt>
                      <dd className={d!.admins.without_mfa ? 'err' : ''}>{d!.admins.without_mfa ?? '—'}</dd>
                    </dl>
                  )}
                </section>
                <section className="card">
                  <div className="card-head">
                    <h2 data-h="3">Release</h2>
                    <a className="sm" href={buildHash('/platform-health')}>
                      Deployments
                    </a>
                  </div>
                  <dl className="detail-kv nums">
                    <dt>MCP</dt>
                    <dd className="mono">{d?.release.mcp ?? '—'}</dd>
                    <dt>UI</dt>
                    <dd className="mono">{d?.release.ui ?? '—'}</dd>
                    <dt>Migrations</dt>
                    <dd className="mono">{d?.release.migrations ?? '—'}</dd>
                  </dl>
                </section>
              </aside>
            </div>
          </>
        )}
      </div>
      {create && (
        <CreateTenantModal
          onClose={() => setCreate(false)}
          onCreated={() => {
            setCreate(false);
            reload();
            navigate('/tenants', { tab: 'onboarding' });
          }}
        />
      )}
      {enter && <EnterTenantModal tenant={enter} onClose={() => setEnter(null)} />}
    </>
  );
};

export default GlobalOverview;
