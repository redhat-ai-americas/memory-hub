import React, { useState } from 'react';
import { ApiError } from '@/api/client';
import { platform, type TenantSummary } from '@/api/platform';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, Modal, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import { errorMessage, fmtInt } from '@/utils/format';
import { dateShort, Health, SingleTenant } from './common';

type Tab = 'active' | 'onboarding' | 'suspended';

const Tenants: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const p = route.params;
  const tab = (['active', 'onboarding', 'suspended'].includes(p.get('tab') ?? '') ? p.get('tab') : 'active') as Tab;
  const { data, error, loading, reload } = useApi(() => platform.tenants(), []);
  const [q, setQ] = useState('');
  const [health, setHealth] = useState('');
  const [quota, setQuota] = useState('');
  const [create, setCreate] = useState(false);
  const [enter, setEnter] = useState(false);
  const [limits, setLimits] = useState<TenantSummary | null>(null);
  const [suspend, setSuspend] = useState<TenantSummary | null>(null);
  const [assign, setAssign] = useState<TenantSummary | null>(null);

  const set = (c: Record<string, string | undefined>) => {
    const next = new URLSearchParams(p);
    Object.entries(c).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    navigate('/tenants', next, { replace: true });
  };
  const all = data?.items ?? [];
  const rows = all.filter((t) => {
    if (t.status !== tab) return false;
    if (q && !t.id.toLowerCase().includes(q.toLowerCase()) && !t.platform_admins.join(' ').toLowerCase().includes(q.toLowerCase())) return false;
    if (health === 'healthy' && t.health !== 'healthy') return false;
    if (health === 'attention' && (t.health === 'healthy' || !t.health)) return false;
    if (quota === '80' && (t.storage_pct ?? 0) < 80) return false;
    return true;
  });
  const sel = rows.find((t) => t.id === p.get('tenant')) ?? rows[0] ?? null;
  const count = (s: Tab) => all.filter((t) => t.status === s).length;

  return (
    <>
      <PageHeader
        title="Tenants"
        crumbs={[{ label: 'Tenants' }]}
        description="Create, suspend and resume tenants, set their limits and assign Platform Admins. Opening a tenant’s console switches you into an explicit, always-visible tenant context."
        actions={
          <button type="button" className="btn bp" onClick={() => setCreate(true)}>
            <Icon.Plus /> Create tenant
          </button>
        }
        tabs={
          <Tabs
            label="Tenant status"
            value={tab}
            onChange={(t) => set({ tab: t === 'active' ? undefined : t, tenant: undefined })}
            tabs={[
              { value: 'active', label: 'Active', count: data ? count('active') : null },
              { value: 'onboarding', label: 'Onboarding', count: data ? count('onboarding') : null },
              { value: 'suspended', label: 'Suspended', count: data ? count('suspended') : null },
            ]}
          />
        }
      />
      <div className="body">
        <SingleTenant source={data?.source} />
        <div className="filters">
          <span className="in-icon">
            <Icon.Search size={15} />
            <label htmlFor="tn-q" className="vh">
              Search tenants
            </label>
            <input id="tn-q" className="in" placeholder="Search tenants" value={q} onChange={(e) => setQ(e.target.value)} />
          </span>
          <label htmlFor="tn-h" className="vh">
            Health
          </label>
          <select id="tn-h" className="in auto" value={health} onChange={(e) => setHealth(e.target.value)}>
            <option value="">Health: any</option>
            <option value="healthy">Health: healthy</option>
            <option value="attention">Health: needs attention</option>
          </select>
          <label htmlFor="tn-qt" className="vh">
            Quota
          </label>
          <select id="tn-qt" className="in auto" value={quota} onChange={(e) => setQuota(e.target.value)}>
            <option value="">Quota: any</option>
            <option value="80">Quota &gt; 80%</option>
          </select>
        </div>
        <div className="row-wrap">
          <section className="card col-main" style={{ padding: '6px 12px', minWidth: 0 }}>
            {error && !data ? (
              <ErrorState error={error} onRetry={reload} />
            ) : loading && !data ? (
              <SkTable rows={5} cols={7} />
            ) : rows.length === 0 ? (
              <Empty compact title={`No ${tab} tenants`}>
                {tab === 'onboarding' ? 'A tenant is onboarding from creation until its first Platform Admin signs in.' : 'Nothing matches these filters.'}
              </Empty>
            ) : (
              <div className="scroll">
                <table className="tbl mid" style={{ minWidth: 680 }}>
                  <thead>
                    <tr>
                      <th>Tenant</th>
                      <th>Platform Admins</th>
                      <th>Users</th>
                      <th>Memory quota</th>
                      <th>Rate limit</th>
                      <th>Health</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((t) => (
                      <tr key={t.id} className={`clickable ${sel?.id === t.id ? 'is-sel' : ''}`} onClick={() => set({ tenant: t.id })}>
                        <td>
                          <a
                            href={`#/tenants?tenant=${encodeURIComponent(t.id)}`}
                            onClick={(e) => {
                              e.preventDefault();
                              set({ tenant: t.id });
                            }}
                          >
                            {t.id}
                          </a>
                        </td>
                        <td>{t.platform_admins.length > 2 || t.platform_admins.length === 0 ? t.platform_admins.length : t.platform_admins.join(', ')}</td>
                        <td>{t.status === 'suspended' ? '—' : t.users ?? '—'}</td>
                        <td>
                          {t.storage_pct !== null ? `${Math.round(t.storage_pct)}%` : '—'}
                          {t.memory_quota ? ` of ${t.memory_quota >= 1000 ? `${Math.round(t.memory_quota / 1000)}k` : t.memory_quota}` : ''}
                        </td>
                        <td>{t.rate_limit ? `${fmtInt(t.rate_limit)}/min` : '—'}</td>
                        <td>
                          <Health health={t.status === 'suspended' ? null : t.health} label={t.health_label?.replace(/ \d+%$/, '')} />
                        </td>
                        <td>
                          <span className={`lbl ${t.status === 'active' ? 'grn' : t.status === 'onboarding' ? 'blue' : 'g'}`}>
                            {t.status[0].toUpperCase() + t.status.slice(1)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <aside className="col-side" style={{ flex: '1 1 320px', maxWidth: 420 }}>
            {sel && (
              <section className="card">
                <div className="card-head">
                  <h3>{sel.id}</h3>
                  <span className={`lbl ${sel.status === 'active' ? 'grn' : sel.status === 'onboarding' ? 'blue' : 'g'}`}>{sel.status[0].toUpperCase() + sel.status.slice(1)}</span>
                </div>
                <dl className="detail-kv">
                  <dt>Created</dt>
                  <dd>{dateShort(sel.created_at, true)}</dd>
                  <dt>Platform Admins</dt>
                  <dd>
                    {sel.platform_admins.length}
                    {sel.admins_mfa === true ? ' · MFA on' : sel.admins_mfa === false ? ' · MFA missing' : ''}
                  </dd>
                  <dt>Memories</dt>
                  <dd>{sel.memories !== null ? `${fmtInt(sel.memories)} (counts only)` : '—'}</dd>
                  <dt>Agents</dt>
                  <dd>{sel.agents ?? '—'}</dd>
                  <dt>Active incident grants</dt>
                  <dd>{sel.incident_grants ?? '—'}</dd>
                </dl>
                <div className="rq-actions" style={{ marginTop: 16, gap: 10 }}>
                  {sel.status === 'suspended' ? (
                    <button type="button" className="btn bp sm-btn" onClick={() => setSuspend(sel)}>
                      Resume…
                    </button>
                  ) : (
                    <button type="button" className="btn bp sm-btn" onClick={() => setEnter(true)}>
                      Open tenant console…
                    </button>
                  )}
                  <button type="button" className="btn bs sm-btn" onClick={() => setAssign(sel)}>
                    Assign Platform Admin
                  </button>
                  <button type="button" className="btn bs sm-btn" onClick={() => setLimits(sel)}>
                    Edit limits
                  </button>
                  {sel.status !== 'suspended' && (
                    <button type="button" className="btn bs sm-btn danger-outline" onClick={() => setSuspend(sel)}>
                      Suspend…
                    </button>
                  )}
                </div>
              </section>
            )}
            {sel && enter && <EnterTenantCard tenant={sel} onCancel={() => setEnter(false)} />}
          </aside>
        </div>
      </div>
      {create && (
        <CreateTenantModal
          onClose={() => setCreate(false)}
          onCreated={() => {
            setCreate(false);
            reload();
          }}
        />
      )}
      {limits && (
        <LimitsModal
          tenant={limits}
          onClose={() => setLimits(null)}
          onSaved={() => {
            setLimits(null);
            toast('Limits saved · recorded in Global audit.');
            reload();
          }}
        />
      )}
      {suspend && (
        <SuspendModal
          tenant={suspend}
          onClose={() => setSuspend(null)}
          onDone={() => {
            setSuspend(null);
            reload();
          }}
        />
      )}
      {assign && <AssignFromTenant tenant={assign} onClose={() => setAssign(null)} />}
    </>
  );
};

/** Asks for a reason, records the switch, then opens the tenant console in an explicit tenant context. */
const useEnter = (tenant: TenantSummary) => {
  const { enterTenant } = useApp();
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await platform.enterTenant(tenant.id, reason.trim());
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404 && tenant.current)) {
        toast(errorMessage(e), 'err');
        setBusy(false);
        return;
      }
      // Single-tenant server: this deployment is that tenant; the console needs no switch on the server.
    }
    enterTenant(tenant.id, reason.trim());
  };
  return { reason, setReason, busy, go };
};

const EnterText: React.FC<{ tenant: TenantSummary }> = ({ tenant }) => (
  <p className="sm" style={{ margin: '10px 0 0', lineHeight: 1.55 }}>
    You will act in <b>{tenant.id}</b> as a Super Admin in tenant context — not as {tenant.platform_admins[0] ?? 'a Platform Admin'} or any user. Personal content stays closed; project
    content still needs membership. Every action is logged with your platform identity.
  </p>
);

const EnterTenantCard: React.FC<{ tenant: TenantSummary; onCancel: () => void }> = ({ tenant, onCancel }) => {
  const { reason, setReason, busy, go } = useEnter(tenant);
  return (
    <section className="card">
      <div className="card-head">
        <h3>Open tenant console?</h3>
        <span className="lbl ylw">confirmation</span>
      </div>
      <EnterText tenant={tenant} />
      <div className="f" style={{ marginTop: 14 }}>
        <label htmlFor="ent-r">Reason</label>
        <input id="ent-r" className="in" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Investigate reranker degradation for this tenant" autoFocus />
      </div>
      <div className="rq-actions" style={{ marginTop: 14 }}>
        <button type="button" className="btn bp" disabled={busy || reason.trim().length < 4} onClick={go}>
          Enter tenant context
        </button>
        <button type="button" className="link-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
};

export const EnterTenantModal: React.FC<{ tenant: TenantSummary; onClose: () => void }> = ({ tenant, onClose }) => {
  const { reason, setReason, busy, go } = useEnter(tenant);
  return (
    <Modal
      title="Open tenant console?"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={busy || reason.trim().length < 4} onClick={go}>
            Enter tenant context
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <EnterText tenant={tenant} />
      <div className="f" style={{ marginTop: 14 }}>
        <label htmlFor="entm-r">Reason</label>
        <input id="entm-r" className="in" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why you need this tenant’s console" autoFocus />
      </div>
    </Modal>
  );
};

export const CreateTenantModal: React.FC<{ onClose: () => void; onCreated: () => void }> = ({ onClose, onCreated }) => {
  const toast = useToast();
  const [id, setId] = useState('org-');
  const [name, setName] = useState('');
  const [admin, setAdmin] = useState('');
  const [quota, setQuota] = useState('100000');
  const [rate, setRate] = useState('800');
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z0-9][a-z0-9-]{2,62}$/.test(id) && name.trim().length > 1;
  const save = async () => {
    setBusy(true);
    try {
      await platform.createTenant({ id, name: name.trim(), admin: admin.trim() || undefined, memory_quota: Number(quota) || null, rate_limit: Number(rate) || null });
      toast(`${id} created · onboarding until its first Platform Admin signs in.`);
      onCreated();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Create tenant"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={!valid || busy} onClick={save}>
            Create · audited
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="rule-edit-grid">
        <div className="f">
          <label htmlFor="ct-id">Tenant ID</label>
          <input id="ct-id" className="in mono" value={id} onChange={(e) => setId(e.target.value.toLowerCase())} />
          <span className="hint">Lowercase letters, digits and dashes · cannot change later</span>
        </div>
        <div className="f">
          <label htmlFor="ct-n">Display name</label>
          <input id="ct-n" className="in" value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Healthcare" />
        </div>
        <div className="f">
          <label htmlFor="ct-a">First Platform Admin</label>
          <input id="ct-a" className="in" value={admin} onChange={(e) => setAdmin(e.target.value)} placeholder="username or email" />
        </div>
        <div className="f">
          <label htmlFor="ct-q">Memory quota</label>
          <input id="ct-q" className="in" type="number" min={0} value={quota} onChange={(e) => setQuota(e.target.value)} />
        </div>
        <div className="f">
          <label htmlFor="ct-r">Rate limit · per minute</label>
          <input id="ct-r" className="in" type="number" min={0} value={rate} onChange={(e) => setRate(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
};

const LimitsModal: React.FC<{ tenant: TenantSummary; onClose: () => void; onSaved: () => void }> = ({ tenant, onClose, onSaved }) => {
  const toast = useToast();
  const [quota, setQuota] = useState(String(tenant.memory_quota ?? ''));
  const [rate, setRate] = useState(String(tenant.rate_limit ?? ''));
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title={`Edit limits · ${tenant.id}`}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy || reason.trim().length < 4}
            onClick={async () => {
              setBusy(true);
              try {
                await platform.setTenantLimits(tenant.id, { memory_quota: quota ? Number(quota) : null, rate_limit: rate ? Number(rate) : null, reason: reason.trim() });
                onSaved();
              } catch (e) {
                toast(errorMessage(e), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            Save · audited
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="rule-edit-grid">
        <div className="f">
          <label htmlFor="lm-q">Memory quota</label>
          <input id="lm-q" className="in" type="number" min={0} value={quota} onChange={(e) => setQuota(e.target.value)} placeholder="No limit" />
          {tenant.memories !== null && <span className="hint">{fmtInt(tenant.memories)} memories stored now</span>}
        </div>
        <div className="f">
          <label htmlFor="lm-r">Rate limit · per minute</label>
          <input id="lm-r" className="in" type="number" min={0} value={rate} onChange={(e) => setRate(e.target.value)} placeholder="Platform default" />
        </div>
        <div className="f" style={{ gridColumn: '1 / -1' }}>
          <label htmlFor="lm-why">Reason</label>
          <input id="lm-why" className="in" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Load growth after onboarding" />
        </div>
      </div>
    </Modal>
  );
};

const SuspendModal: React.FC<{ tenant: TenantSummary; onClose: () => void; onDone: () => void }> = ({ tenant, onClose, onDone }) => {
  const toast = useToast();
  const resume = tenant.status === 'suspended';
  const [reason, setReason] = useState('');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title={resume ? `Resume ${tenant.id}?` : `Suspend ${tenant.id}?`}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className={`btn ${resume ? 'bp' : 'bd'}`}
            disabled={busy || reason.trim().length < 4 || (!resume && typed !== tenant.id)}
            onClick={async () => {
              setBusy(true);
              try {
                await platform.setTenantStatus(tenant.id, resume ? 'active' : 'suspended', reason.trim());
                toast(resume ? `${tenant.id} resumed.` : `${tenant.id} suspended. Its users and agents are signed out.`);
                onDone();
              } catch (e) {
                toast(errorMessage(e), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            {resume ? 'Resume tenant' : 'Suspend tenant'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <p className="sm" style={{ marginTop: 0 }}>
        {resume
          ? 'Users and agents can sign in again with their existing credentials.'
          : 'Every user and agent of this tenant is signed out and refused until you resume it. Memories, settings and audit stay untouched.'}
      </p>
      <div className="f">
        <label htmlFor="sp-r">Reason</label>
        <input id="sp-r" className="in" value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      {!resume && (
        <div className="f" style={{ marginTop: 12 }}>
          <label htmlFor="sp-t">Type the tenant ID to confirm</label>
          <input id="sp-t" className="in mono" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={tenant.id} />
        </div>
      )}
    </Modal>
  );
};

const AssignFromTenant: React.FC<{ tenant: TenantSummary; onClose: () => void }> = ({ tenant, onClose }) => {
  React.useEffect(() => {
    navigate('/admins', { assign: tenant.id });
    onClose();
  }, [tenant.id, onClose]);
  return null;
};

export default Tenants;
