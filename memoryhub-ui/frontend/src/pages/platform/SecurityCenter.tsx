import React, { useState } from 'react';
import { platform, type SecurityResponse } from '@/api/platform';
import { PageHeader, Tabs } from '@/components/Shell';
import { Empty, ErrorState, Icon, Modal, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import { errorMessage } from '@/utils/format';
import { hhmm, Kpi, Sev, SingleTenant } from './common';

type Tab = 'incidents' | 'alerts' | 'cross' | 'revoked' | 'grants';
const STATUS: Record<string, string> = { investigating: 'ylw', monitoring: 'ylw', closed: 'grn' };

const SecurityCenter: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const tab = (route.params.get('tab') as Tab) || 'incidents';
  const { data, error, loading, reload } = useApi<SecurityResponse>(() => platform.security(), [], 30000);
  const tenants = useApi(() => platform.tenants(), []);
  const [modal, setModal] = useState<null | 'revoke' | 'incident'>(null);
  const d = data;
  const first = loading && !d;
  const setTab = (t: string) => navigate('/security', t === 'incidents' ? undefined : { tab: t }, { replace: true });

  const incidents = (
    <section className="card">
      <h3>Incidents</h3>
      {first ? (
        <SkTable rows={3} cols={7} />
      ) : d!.incidents.length === 0 ? (
        <Empty compact title="No incidents">Open one to request incident access or track a security event.</Empty>
      ) : (
        <div className="scroll">
          <table className="tbl mid" style={{ minWidth: 680, marginTop: 8 }}>
            <thead>
              <tr>
                <th>Incident</th>
                <th>Tenant</th>
                <th>Severity</th>
                <th>Owner</th>
                <th>Grants</th>
                <th>Opened</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {d!.incidents.map((i) => (
                <tr key={i.id}>
                  <td>
                    <a href={buildHash('/incident', { incident: i.id })}>{i.id}</a>
                    <div className="sm muted">{i.title}</div>
                  </td>
                  <td>{i.tenant}</td>
                  <td>
                    <Sev s={i.severity} />
                  </td>
                  <td>{i.owner}</td>
                  <td className="sm">
                    {/^(inspect|remediate)/.test(i.grants) ? (
                      <>
                        <span className={`lbl ${i.grants.split(' ')[0]}`}>{i.grants.split(' ')[0]}</span>
                        <div>{i.grants.split(' ').slice(1).join(' ')}</div>
                      </>
                    ) : (
                      i.grants || '—'
                    )}
                  </td>
                  <td>{hhmm(i.opened_at)}</td>
                  <td>
                    <span className={`lbl ${STATUS[i.status] ?? 'g'}`}>{i.status[0].toUpperCase() + i.status.slice(1)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
  const cross = (
    <section className="card">
      <h3>Denied cross-tenant attempts · 24 h</h3>
      {first ? (
        <SkLines lines={3} />
      ) : d!.cross_tenant.length === 0 ? (
        <p className="sm muted" style={{ marginTop: 10 }}>
          {d!.source === 'single-tenant' ? 'A single-tenant deployment cannot see other tenants; the platform service reports these.' : 'None — no identity tried to reach another tenant.'}
        </p>
      ) : (
        <table className="tbl mid" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Time</th>
              <th>Identity</th>
              <th>From tenant</th>
              <th>Target tenant</th>
              <th>Operation</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {d!.cross_tenant.map((c) => (
              <tr key={c.id}>
                <td className="mono">{hhmm(c.time)}</td>
                <td className="mono sm">{c.identity}</td>
                <td>{c.from}</td>
                <td>{c.to}</td>
                <td className="mono sm">{c.operation}</td>
                <td className="err" style={{ fontWeight: 600 }}>
                  Denied
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
  const revoked = (
    <section className="card">
      <h3>Revoked clients</h3>
      {first ? (
        <SkLines lines={3} />
      ) : d!.revoked.length === 0 ? (
        <p className="sm muted" style={{ marginTop: 10 }}>
          No revoked clients.
        </p>
      ) : (
        <table className="tbl mid" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Time</th>
              <th>Client</th>
              <th>Tenant</th>
              <th>By</th>
              <th>Scope</th>
            </tr>
          </thead>
          <tbody>
            {d!.revoked.map((r) => (
              <tr key={r.id}>
                <td className="mono">{hhmm(r.time)}</td>
                <td>
                  {r.client} <span className="mono sm muted">{r.id.slice(0, 8)}</span>
                </td>
                <td>{r.tenant}</td>
                <td>{r.by}</td>
                <td>
                  <span className={`lbl ${r.scope === 'platform' ? 'red' : 'g'}`}>{r.scope === 'platform' ? 'platform-wide' : 'tenant'}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
  const anomalies = (
    <section className="card">
      <h3>Anomalies</h3>
      {first ? (
        <SkLines lines={3} />
      ) : d!.alerts.length === 0 ? (
        <p className="sm muted" style={{ marginTop: 10 }}>
          Nothing unusual right now.
        </p>
      ) : (
        <ul className="attn">
          {d!.alerts.map((a) => (
            <li key={a.id}>
              <span className="legend-dot" style={{ background: '#f0ab00' }} />
              <div>
                <div>{a.text}</div>
                {a.detail && <div className="sm muted">{a.detail}</div>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
  const grants = (
    <section className="card">
      <div className="card-head">
        <h3>Privileged grants</h3>
        <a href={buildHash('/incident')}>Incident access</a>
      </div>
      {first ? (
        <SkLines lines={4} />
      ) : (
        <dl className="detail-kv nums">
          <dt>Active</dt>
          <dd>{d!.grants.active}</dd>
          <dt>Pending approval</dt>
          <dd>{d!.grants.pending}</dd>
          <dt>Remediate this month</dt>
          <dd>{d!.grants.remediate_month}</dd>
          <dt>Self-approval attempts</dt>
          <dd>{d!.grants.self_approval} · blocked by design</dd>
        </dl>
      )}
    </section>
  );

  return (
    <>
      <PageHeader
        title="Security center"
        crumbs={[{ label: 'Security center' }]}
        description="Denied cross-tenant attempts, anomalies, revoked clients, incidents, privileged grants and their approvals across the platform. Events carry IDs and metadata, never memory text."
        actions={
          <>
            <button type="button" className="btn bs" onClick={() => setModal('revoke')}>
              Revoke client platform-wide…
            </button>
            <button type="button" className="btn bp" onClick={() => setModal('incident')}>
              <Icon.Plus /> Open incident
            </button>
          </>
        }
        tabs={
          <Tabs
            label="Security"
            value={tab}
            onChange={setTab}
            tabs={[
              { value: 'incidents', label: 'Incidents', count: d ? d.kpis.open_incidents : null },
              { value: 'alerts', label: 'Alerts', count: d ? d.alerts.length : null },
              { value: 'cross', label: 'Cross-tenant attempts' },
              { value: 'revoked', label: 'Revoked clients' },
              { value: 'grants', label: 'Privileged grants' },
            ]}
          />
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
              <Kpi loading={first} label="Open incidents" value={d?.kpis.open_incidents ?? '—'} sub={d && `${d.kpis.with_grant} with an active grant`} />
              <Kpi loading={first} label="Cross-tenant attempts · 24 h" value={d?.kpis.cross_tenant_24h ?? '—'} sub="all denied" />
              <Kpi loading={first} label="Failed sign-ins · 24 h" value={d?.kpis.failed_signins_24h ?? '—'} sub={d?.kpis.failed_trend ?? 'from the audit log'} />
              <Kpi loading={first} label="Revoked clients · 24 h" value={d?.kpis.revoked_24h ?? '—'} sub={d && `${d.kpis.revoked_platform} platform-wide`} />
            </div>
            {tab === 'incidents' ? (
              <div className="row-wrap">
                <div className="col-main" style={{ minWidth: 0 }}>
                  {incidents}
                  {cross}
                </div>
                <aside className="col-side" style={{ flex: '1 1 300px', maxWidth: 400 }}>
                  {anomalies}
                  {grants}
                </aside>
              </div>
            ) : tab === 'alerts' ? (
              anomalies
            ) : tab === 'cross' ? (
              cross
            ) : tab === 'revoked' ? (
              revoked
            ) : (
              grants
            )}
          </>
        )}
      </div>
      {modal === 'revoke' && <RevokeModal onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
      {modal === 'incident' && (
        <IncidentModal
          tenants={(tenants.data?.items ?? []).map((t) => t.id)}
          onClose={() => setModal(null)}
          onDone={() => {
            setModal(null);
            toast('Incident opened.');
            reload();
          }}
        />
      )}
    </>
  );
};

const RevokeModal: React.FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const toast = useToast();
  const [client, setClient] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title="Revoke a client platform-wide"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bd"
            disabled={busy || !client.trim() || reason.trim().length < 4}
            onClick={async () => {
              setBusy(true);
              try {
                await platform.revokeClientPlatformWide(client.trim(), reason.trim());
                toast(`${client} is refused in every tenant within 5 seconds.`);
                onDone();
              } catch (e) {
                toast(errorMessage(e), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            Revoke everywhere
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <p className="sm" style={{ marginTop: 0 }}>
        The client can no longer obtain tokens in any tenant; sessions it holds are refused within 5 seconds. Tenants see the revocation in their audit log.
      </p>
      <div className="f">
        <label htmlFor="rc-c">Client ID</label>
        <input id="rc-c" className="in mono" value={client} onChange={(e) => setClient(e.target.value)} placeholder="cli_9b02…" autoFocus />
      </div>
      <div className="f" style={{ marginTop: 12 }}>
        <label htmlFor="rc-r">Reason</label>
        <input id="rc-r" className="in" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Probing foreign tenants" />
      </div>
    </Modal>
  );
};

const IncidentModal: React.FC<{ tenants: string[]; onClose: () => void; onDone: () => void }> = ({ tenants, onClose, onDone }) => {
  const toast = useToast();
  const [title, setTitle] = useState('');
  const [tenant, setTenant] = useState(tenants[0] ?? '');
  const [severity, setSeverity] = useState('high');
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title="Open incident"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy || title.trim().length < 4 || !tenant}
            onClick={async () => {
              setBusy(true);
              try {
                await platform.openIncident({ title: title.trim(), tenant, severity });
                onDone();
              } catch (e) {
                toast(errorMessage(e), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            Open · audited
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="rule-edit-grid">
        <div className="f" style={{ gridColumn: '1 / -1' }}>
          <label htmlFor="oi-t">Title</label>
          <input id="oi-t" className="in" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Suspected PII leak through gpt-reports" autoFocus />
        </div>
        <div className="f">
          <label htmlFor="oi-tn">Tenant</label>
          <select id="oi-tn" className="in" value={tenant} onChange={(e) => setTenant(e.target.value)}>
            {tenants.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <div className="f">
          <label htmlFor="oi-s">Severity</label>
          <select id="oi-s" className="in" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
      </div>
    </Modal>
  );
};

export default SecurityCenter;
