import React, { useState } from 'react';
import { platform, type AdminRow } from '@/api/platform';
import { PageHeader, Tabs } from '@/components/Shell';
import { Empty, ErrorState, Icon, Modal, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import { errorMessage } from '@/utils/format';
import { dateShort, hhmm, RoleBadge, SingleTenant } from './common';

type Tab = 'all' | 'super' | 'platform' | 'attention';
const MFA: Record<string, string> = { webauthn: 'WebAuthn', totp: 'TOTP' };
const soon = (iso?: string | null) => !!iso && Date.parse(iso) - Date.now() < 14 * 86400000;
const needsAttention = (a: AdminRow) => !a.mfa || soon(a.valid_until);

const Administrators: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const p = route.params;
  const tab = (['all', 'super', 'platform', 'attention'].includes(p.get('tab') ?? '') ? p.get('tab') : 'all') as Tab;
  const { data, error, loading, reload } = useApi(() => platform.admins(), []);
  const tenants = useApi(() => platform.tenants(), []);
  const [form, setForm] = useState<null | { role: 'admin' | 'superuser'; tenant?: string }>(p.get('assign') ? { role: 'admin', tenant: p.get('assign')! } : null);
  const [revoke, setRevoke] = useState<AdminRow | null>(null);
  const [scopeFor, setScopeFor] = useState<AdminRow | null>(null);
  const items = data?.items ?? [];
  const rows = items.filter((a) => (tab === 'super' ? a.role === 'superuser' : tab === 'platform' ? a.role === 'admin' : tab === 'attention' ? needsAttention(a) : true));
  const setTab = (t: string) => {
    const next = new URLSearchParams();
    if (t !== 'all') next.set('tab', t);
    navigate('/admins', next, { replace: true });
  };
  const requireMfa = async (a: AdminRow) => {
    try {
      await platform.requireMfa(a.username);
      toast(`${a.name} must enrol MFA before the next admin action.`);
      reload();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };

  return (
    <>
      <PageHeader
        title="Administrators"
        crumbs={[{ label: 'Administrators' }]}
        description="Who holds administrative authority, where, and until when. Assign and revoke Platform Admins per tenant and Super Admins for the platform. Nobody can grant a role to themselves from this interface."
        actions={
          <>
            <button type="button" className="btn bs" onClick={() => setForm({ role: 'superuser' })}>
              Assign Super Admin…
            </button>
            <button type="button" className="btn bp" onClick={() => setForm({ role: 'admin' })}>
              <Icon.Plus /> Assign Platform Admin
            </button>
          </>
        }
        tabs={
          <Tabs
            label="Administrators"
            value={tab}
            onChange={setTab}
            tabs={[
              { value: 'all', label: 'All', count: data ? items.length : null },
              { value: 'super', label: 'Super Admins', count: data ? items.filter((a) => a.role === 'superuser').length : null },
              { value: 'platform', label: 'Platform Admins', count: data ? items.filter((a) => a.role === 'admin').length : null },
              { value: 'attention', label: 'Needs attention', count: data ? items.filter(needsAttention).length : null },
            ]}
          />
        }
      />
      <div className="body">
        <SingleTenant source={data?.source} />
        <section className="card" style={{ padding: '6px 12px' }}>
          {error && !data ? (
            <ErrorState error={error} onRetry={reload} />
          ) : loading && !data ? (
            <SkTable rows={5} cols={7} />
          ) : rows.length === 0 ? (
            <Empty compact title={tab === 'attention' ? 'Nothing needs attention' : 'No administrators'}>
              {tab === 'attention' ? 'Every administrator has MFA and no role expires in the next two weeks.' : 'Assign one with the buttons above.'}
            </Empty>
          ) : (
            <div className="scroll">
              <table className="tbl mid" style={{ minWidth: 820 }}>
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Role</th>
                    <th>Scope</th>
                    <th>Granted by</th>
                    <th>Valid until</th>
                    <th>MFA</th>
                    <th>Last admin action</th>
                    <th>
                      <span className="vh">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={`${a.username}-${a.scope}`}>
                      <td>
                        <b>{a.name}</b>
                        {a.you && <div className="sm muted">you</div>}
                      </td>
                      <td>
                        <RoleBadge role={a.role} long />
                      </td>
                      <td>{a.scope}</td>
                      <td>
                        {a.granted_by ?? '—'}
                        {a.granted_at && a.granted_by !== 'deployment config' ? ` · ${dateShort(a.granted_at)}` : ''}
                      </td>
                      <td className={soon(a.valid_until) ? 'warn' : ''}>{a.valid_until ? dateShort(a.valid_until, true) : '—'}</td>
                      <td>{a.mfa ? <span className="lbl grn">{MFA[a.mfa]}</span> : <span className="lbl red">Not set</span>}</td>
                      <td className="sm">{hhmm(a.last_action)}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {a.you ? (
                          <span className="sm muted" style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
                            <Icon.Lock size={12} /> Can’t edit own role
                          </span>
                        ) : (
                          <span className="row-links">
                            {!a.mfa ? (
                              <button type="button" className="link-btn" onClick={() => requireMfa(a)}>
                                Require MFA
                              </button>
                            ) : (
                              a.role === 'admin' && (
                                <button type="button" className="link-btn" onClick={() => setScopeFor(a)}>
                                  Edit scope
                                </button>
                              )
                            )}
                            <button type="button" className="link-btn" onClick={() => setRevoke(a)}>
                              Revoke…
                            </button>
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <div className="acc-cards two">
          {form ? (
            <AssignForm
              key={`${form.role}-${form.tenant ?? ''}`}
              role={form.role}
              tenant={form.tenant}
              tenants={(tenants.data?.items ?? []).map((t) => t.id)}
              onClose={() => setForm(null)}
              onDone={() => {
                setForm(null);
                reload();
              }}
            />
          ) : (
            <section className="card">
              <h2 data-h="3">Assign an administrator</h2>
              <p className="sm muted" style={{ margin: '10px 0 14px' }}>
                A Platform Admin runs one tenant’s console. A Super Admin runs the platform and approves incident grants; further Super Admins need another Super Admin.
              </p>
              <button type="button" className="btn bp sm-btn" onClick={() => setForm({ role: 'admin' })}>
                Assign Platform Admin
              </button>
            </section>
          )}
          <section className="card">
            <h2 data-h="3">Rules</h2>
            <ul className="rule-list">
              <li>Super Admins are seeded by deployment config; further SAs need another SA.</li>
              <li>No one can assign or extend their own administrative role.</li>
              <li>MFA is required for every administrator; missing MFA blocks admin actions.</li>
              <li>Admin roles add Tenant Console or Platform Operations; they never change what the person can read in Memory Workspace.</li>
            </ul>
          </section>
        </div>
      </div>
      {revoke && <RevokeModal admin={revoke} onClose={() => setRevoke(null)} onDone={() => { setRevoke(null); reload(); }} />}
      {scopeFor && (
        <Modal title={`Edit scope · ${scopeFor.name}`} onClose={() => setScopeFor(null)}>
          <p className="sm" style={{ marginTop: 0 }}>
            A Platform Admin role is per tenant. To move {scopeFor.name} to another tenant, assign the new tenant and revoke {scopeFor.scope}; both steps are recorded in Global audit.
          </p>
          <div className="rq-actions">
            <button
              type="button"
              className="btn bp"
              onClick={() => {
                setForm({ role: 'admin' });
                setScopeFor(null);
              }}
            >
              Assign another tenant
            </button>
            <button
              type="button"
              className="btn bs"
              onClick={() => {
                setRevoke(scopeFor);
                setScopeFor(null);
              }}
            >
              Revoke {scopeFor.scope}…
            </button>
          </div>
        </Modal>
      )}
    </>
  );
};

const AssignForm: React.FC<{ role: 'admin' | 'superuser'; tenant?: string; tenants: string[]; onClose: () => void; onDone: () => void }> = ({ role, tenant, tenants, onClose, onDone }) => {
  const toast = useToast();
  const [person, setPerson] = useState('');
  const [t, setT] = useState(tenant ?? tenants[0] ?? '');
  const [until, setUntil] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const validUntil = until ? new Date(Date.now() + Number(until) * 86400000).toISOString() : null;
      await platform.assignAdmin({ username: person.trim(), role, tenant: role === 'admin' ? t : undefined, valid_until: validUntil, reason: reason.trim() });
      toast(role === 'admin' ? `${person} is now a Platform Admin of ${t}.` : `${person} was proposed as Super Admin — another Super Admin confirms it.`);
      onDone();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card">
      <h2 data-h="3">{role === 'admin' ? 'Assign Platform Admin' : 'Assign Super Admin'}</h2>
      <div className="f set-f">
        <label htmlFor="as-p">Person</label>
        <input id="as-p" className="in" value={person} onChange={(e) => setPerson(e.target.value)} placeholder="Priya Shah (pshah)" autoFocus />
      </div>
      {role === 'admin' && (
        <div className="f set-f">
          <label htmlFor="as-t">Tenant</label>
          <select id="as-t" className="in" value={t} onChange={(e) => setT(e.target.value)}>
            {[...new Set([...tenants, ...(tenant ? [tenant] : [])])].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </div>
      )}
      <div className="f set-f">
        <label htmlFor="as-u">Valid until</label>
        <select id="as-u" className="in" value={until} onChange={(e) => setUntil(e.target.value)}>
          <option value="">No end date</option>
          <option value="30">30 days</option>
          <option value="90">90 days</option>
          <option value="180">180 days</option>
          <option value="365">1 year</option>
        </select>
      </div>
      <div className="f set-f">
        <label htmlFor="as-r">Reason</label>
        <input id="as-r" className="in" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Second admin for cold-chain rollout" />
      </div>
      <div className="rq-actions" style={{ marginTop: 16 }}>
        <button type="button" className="btn bp" disabled={busy || !person.trim() || reason.trim().length < 4 || (role === 'admin' && !t)} onClick={save}>
          Assign · audited
        </button>
        <button type="button" className="link-btn" onClick={onClose}>
          Cancel
        </button>
      </div>
      {role === 'superuser' && <p className="sm muted" style={{ margin: '10px 0 0' }}>A second Super Admin confirms the assignment in their own session.</p>}
    </section>
  );
};

const RevokeModal: React.FC<{ admin: AdminRow; onClose: () => void; onDone: () => void }> = ({ admin, onClose, onDone }) => {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title={`Revoke ${admin.role === 'superuser' ? 'Super Admin' : 'Platform Admin'} · ${admin.name}?`}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bd"
            disabled={busy || reason.trim().length < 4}
            onClick={async () => {
              setBusy(true);
              try {
                await platform.revokeAdmin(admin.username, admin.scope, reason.trim());
                toast(`${admin.name} no longer administers ${admin.scope}.`);
                onDone();
              } catch (e) {
                toast(errorMessage(e), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            Revoke · audited
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <p className="sm" style={{ marginTop: 0 }}>
        {admin.name} keeps their own account and memory; only the {admin.scope === 'Platform' ? 'Platform Operations' : `${admin.scope} console`} access goes. Open admin sessions end at the next request.
      </p>
      <div className="f">
        <label htmlFor="rv-r">Reason</label>
        <input id="rv-r" className="in" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
      </div>
    </Modal>
  );
};

export default Administrators;
