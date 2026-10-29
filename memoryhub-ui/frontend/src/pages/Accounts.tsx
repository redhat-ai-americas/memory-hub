import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { copyText, Empty, ErrorState, Icon, Modal, SkLines, SkTable, Switch, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import type { AccountRow, AccountsResponse, InviteCreated, SettingsResponse, SignupMode, TenantSettingsValues } from '@/types';
import { errorMessage, fmtRelative } from '@/utils/format';

/**
 * Platform admins only: who has a dashboard account, who is waiting for
 * approval, invite codes, and the tenant's sign-up and privacy policy.
 * Shown when local accounts are enabled (MEMORYHUB_UI_LOCAL_ACCOUNTS=true).
 */
type Tab = 'people' | 'invites' | 'policy';

const MODE_LABEL: Record<SignupMode, string> = { invite: 'Invite only', domain: 'Company email domains', open: 'Open', closed: 'Closed' };

const Accounts: React.FC = () => {
  const toast = useToast();
  const { me } = useApp();
  const [tab, setTab] = useState<Tab>('people');
  const { data, error, loading, reload } = useApi<AccountsResponse>(() => api.accounts(), []);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [created, setCreated] = useState<InviteCreated | null>(null);

  const change = async (a: AccountRow, body: { status?: 'active' | 'disabled'; role?: 'admin' | 'user' }, done: string) => {
    try {
      await api.updateAccount(a.id, body);
      toast(done);
      reload();
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  };

  const pending = data?.items.filter((a) => a.status === 'pending') ?? [];
  const others = data?.items.filter((a) => a.status !== 'pending') ?? [];

  return (
    <>
      <PageHeader
        title="Accounts & sign-up"
        description="Dashboard accounts for people. Agents and service identities live under Users & agents. Admins manage accounts; they never read personal memories."
        actions={
          <button type="button" className="btn bp" onClick={() => setInviteOpen(true)}>
            <Icon.Plus />
            Invite people
          </button>
        }
        tabs={
          <Tabs
            label="Accounts"
            value={tab}
            onChange={setTab}
            tabs={[
              { value: 'people', label: 'People', count: data?.counts.all ?? null },
              { value: 'invites', label: 'Invites', count: data ? data.invites.filter((i) => i.state === 'open').length : null },
              { value: 'policy', label: 'Sign-up & privacy policy' },
            ]}
          />
        }
      />
      <div className="body">
        {tab === 'policy' ? (
          <PolicyEditor />
        ) : error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : loading && !data ? (
          <div className="card">
            <SkTable rows={6} cols={5} />
          </div>
        ) : tab === 'invites' ? (
          <section className="card" style={{ padding: 0 }}>
            {data!.invites.length === 0 ? (
              <Empty title="No invites yet" action={<button type="button" className="btn bs" onClick={() => setInviteOpen(true)}>Invite people</button>}>
                Invite codes are single-use and expire. Invited people skip the approval queue.
              </Empty>
            ) : (
              <div className="scroll">
                <table className="tbl mid">
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>For</th>
                      <th>Role</th>
                      <th>State</th>
                      <th>Created</th>
                      <th>Expires</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data!.invites.map((i) => (
                      <tr key={i.id}>
                        <td className="mono">{i.code}</td>
                        <td className="sm">
                          {i.email ?? 'Anyone with the code'}
                          {i.note && <div className="muted">{i.note}</div>}
                        </td>
                        <td>
                          <span className={`lbl ${i.role === 'admin' ? 'red' : 'g'}`}>{i.role === 'admin' ? 'Platform admin' : 'User'}</span>
                        </td>
                        <td className="sm">{i.state === 'used' ? `Used by ${i.used_by}` : i.state === 'expired' ? 'Expired' : 'Open'}</td>
                        <td className="sm muted">
                          {fmtRelative(i.created_at)} · {i.created_by}
                        </td>
                        <td className="sm muted">{fmtRelative(i.expires_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ) : (
          <>
            <div className="grid-kpi">
              {[
                ['Accounts', data!.counts.all],
                ['Waiting for approval', data!.counts.pending],
                ['Platform admins', data!.counts.admins],
                ['Disabled', data!.counts.disabled],
              ].map(([label, n]) => (
                <div className="card" key={label as string}>
                  <div className="sm muted">{label}</div>
                  <div className="kpi">{(n as number).toLocaleString()}</div>
                </div>
              ))}
            </div>
            {pending.length > 0 && (
              <section className="card" style={{ padding: 0 }}>
                <div className="ch" style={{ padding: '18px 20px 0' }}>
                  <h3>Waiting for approval</h3>
                  <span className="sm muted">Approving gives a user account. Project access still comes from project owners.</span>
                </div>
                <AccountTable
                  rows={pending}
                  me={me?.username}
                  actions={(a) => (
                    <>
                      <button type="button" className="btn bp sm" onClick={() => change(a, { status: 'active' }, `${a.username} approved.`)}>
                        Approve
                      </button>
                      <button type="button" className="btn bl danger sm" onClick={() => change(a, { status: 'disabled' }, `${a.username} declined.`)}>
                        Decline
                      </button>
                    </>
                  )}
                />
              </section>
            )}
            <section className="card" style={{ padding: 0 }}>
              {others.length === 0 ? (
                <Empty title="No accounts yet">People appear here when they sign up or accept an invite.</Empty>
              ) : (
                <AccountTable
                  rows={others}
                  me={me?.username}
                  actions={(a) => (
                    <>
                      {a.status === 'disabled' ? (
                        <button type="button" className="btn bl sm" onClick={() => change(a, { status: 'active' }, `${a.username} re-enabled.`)}>
                          Enable
                        </button>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="btn bl sm"
                            disabled={a.username === me?.username}
                            onClick={() =>
                              change(a, { role: a.role === 'admin' ? 'user' : 'admin' }, a.role === 'admin' ? `${a.username} is now a user.` : `${a.username} is now a platform admin.`)
                            }
                          >
                            {a.role === 'admin' ? 'Make user' : 'Make admin'}
                          </button>
                          <button
                            type="button"
                            className="btn bl danger sm"
                            disabled={a.username === me?.username}
                            onClick={() => change(a, { status: 'disabled' }, `${a.username} disabled.`)}
                          >
                            Disable
                          </button>
                        </>
                      )}
                    </>
                  )}
                />
              )}
            </section>
          </>
        )}
      </div>
      {inviteOpen && (
        <InviteModal
          onClose={() => setInviteOpen(false)}
          onCreated={(inv) => {
            setInviteOpen(false);
            setCreated(inv);
            reload();
          }}
        />
      )}
      {created && (
        <Modal
          title="Invite created"
          onClose={() => setCreated(null)}
          actions={
            <button
              type="button"
              className="btn bp"
              onClick={async () => {
                if (await copyText(created.link)) toast('Invite link copied.');
              }}
            >
              Copy invite link
            </button>
          }
        >
          <p className="sm" style={{ margin: 0 }}>
            Send this link to {created.email ?? 'the person you are inviting'}. It works once, as a {created.role === 'admin' ? 'platform admin' : 'user'}, and expires{' '}
            {fmtRelative(created.expires_at)}. The code is shown only now.
          </p>
          <pre className="small">{created.link}</pre>
        </Modal>
      )}
    </>
  );
};

const AccountTable: React.FC<{ rows: AccountRow[]; me?: string; actions: (a: AccountRow) => React.ReactNode }> = ({ rows, me, actions }) => (
  <div className="scroll">
    <table className="tbl mid">
      <thead>
        <tr>
          <th>Person</th>
          <th>Role</th>
          <th>Status</th>
          <th>Asked for projects</th>
          <th>Joined</th>
          <th>Last sign-in</th>
          <th>
            <span className="vh">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.id}>
            <td>
              <div className="b5">
                {a.display_name}
                {a.username === me && <span className="muted sm"> (you)</span>}
              </div>
              <div className="sm muted">
                <span className="mono">{a.username}</span> · {a.email}
                {a.job_title ? ` · ${a.job_title}` : ''}
              </div>
            </td>
            <td>
              <span className={`lbl ${a.role === 'admin' ? 'red' : 'g'}`}>{a.role === 'admin' ? 'Platform admin' : 'User'}</span>
            </td>
            <td className="sm">
              <span className={a.status === 'active' ? 'ok' : a.status === 'pending' ? 'warn' : 'muted'}>
                {a.status === 'active' ? 'Active' : a.status === 'pending' ? 'Waiting' : 'Disabled'}
              </span>
            </td>
            <td className="sm">
              {a.requested_projects.length ? (
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {a.requested_projects.map((p) => (
                    <span className="tag" key={p}>
                      {p}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="muted">—</span>
              )}
            </td>
            <td className="sm muted" style={{ whiteSpace: 'nowrap' }}>
              {fmtRelative(a.created_at)}
              {a.invited_by && <div>invited by {a.invited_by}</div>}
            </td>
            <td className="sm muted" style={{ whiteSpace: 'nowrap' }}>
              {a.last_login_at ? fmtRelative(a.last_login_at) : 'Never'}
            </td>
            <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>{actions(a)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const InviteModal: React.FC<{ onClose: () => void; onCreated: (i: InviteCreated) => void }> = ({ onClose, onCreated }) => {
  const toast = useToast();
  const [role, setRole] = useState<'user' | 'admin'>('user');
  const [email, setEmail] = useState('');
  const [note, setNote] = useState('');
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title="Invite people"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                onCreated(await api.createInvite({ role, email: email.trim() || undefined, note: note.trim() || undefined, expires_days: days }));
              } catch (err) {
                toast(errorMessage(err), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            Create invite
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <span className="lbl-t">Role</span>
        <div className="seg" role="group" aria-label="Role">
          {(['user', 'admin'] as const).map((r) => (
            <button key={r} type="button" className={role === r ? 'on' : ''} aria-pressed={role === r} onClick={() => setRole(r)}>
              {r === 'admin' ? 'Platform admin' : 'User'}
            </button>
          ))}
        </div>
        {role === 'admin' && <span className="hint">Platform admins manage the platform and moderate every scope except personal memories.</span>}
      </div>
      <div className="f">
        <label htmlFor="ie">Email (optional)</label>
        <input id="ie" className="in" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Locks the invite to this address" />
      </div>
      <div className="f">
        <label htmlFor="inote">Note (optional)</label>
        <input id="inote" className="in" value={note} onChange={(e) => setNote(e.target.value)} placeholder="New SRE on-call" />
      </div>
      <div className="f">
        <label htmlFor="idays">Expires after (days)</label>
        <input id="idays" className="in auto" type="number" min={1} max={30} value={days} onChange={(e) => setDays(Number(e.target.value))} />
      </div>
    </Modal>
  );
};

const PolicyEditor: React.FC = () => {
  const toast = useToast();
  const { data, error, loading, reload, setData } = useApi<SettingsResponse>(() => api.settings(), []);
  const [v, setV] = useState<TenantSettingsValues | null>(null);
  const [domains, setDomains] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data) {
      setV(structuredClone(data.values));
      setDomains((data.values.signup?.allowed_domains ?? []).join(', '));
    }
  }, [data]);

  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if ((loading && !data) || !v) return <div className="card"><SkLines lines={10} /></div>;

  const upd = <K extends 'organization' | 'signup' | 'privacy' | 'security'>(k: K, patch: Partial<TenantSettingsValues[K]>) =>
    setV({ ...v, [k]: { ...v[k], ...patch } });
  const scopes = v.privacy.admin_readable_scopes;

  const save = async () => {
    setBusy(true);
    try {
      const allowed = domains.split(/[\s,]+/).map((d) => d.trim().toLowerCase().replace(/^@/, '')).filter(Boolean);
      const res = await api.saveSettings({ organization: v.organization, signup: { ...v.signup, allowed_domains: allowed }, privacy: v.privacy, security: v.security });
      setData(res);
      toast('Policy saved — audited.');
    } catch (err) {
      toast(errorMessage(err), 'err');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="row-wrap">
      <div className="col-main">
        <section className="card">
          <div className="ch">
            <h3>Organization</h3>
          </div>
          <div className="fg" style={{ marginTop: 0 }}>
            <div className="f">
              <label htmlFor="pon">Name</label>
              <input id="pon" className="in" value={v.organization.name} onChange={(e) => upd('organization', { name: e.target.value })} />
            </div>
            <div className="f">
              <label htmlFor="poc">Security contact</label>
              <input id="poc" className="in" type="email" value={v.organization.contact_email} onChange={(e) => upd('organization', { contact_email: e.target.value })} />
            </div>
          </div>
        </section>
        <section className="card">
          <div className="ch">
            <h3>Who can create an account</h3>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(Object.keys(MODE_LABEL) as SignupMode[]).map((m) => (
              <label key={m} className={`radio ${v.signup.mode === m ? 'on' : ''}`}>
                <input type="radio" name="pmode" checked={v.signup.mode === m} onChange={() => upd('signup', { mode: m })} />
                <span className="sm b6">{MODE_LABEL[m]}</span>
              </label>
            ))}
          </div>
          {v.signup.mode === 'domain' && (
            <div className="f" style={{ marginTop: 14 }}>
              <label htmlFor="pdom">Allowed email domains</label>
              <input id="pdom" className="in mono" value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="acme.com" />
            </div>
          )}
          <div className="swrow" style={{ marginTop: 16 }}>
            <span>Admin approves self-registered accounts</span>
            <Switch on={v.signup.require_approval} onChange={(on) => upd('signup', { require_approval: on })} label="Admin approves accounts" />
          </div>
          <div className="fg">
            <div className="f">
              <label htmlFor="psh">Session length (hours)</label>
              <input id="psh" className="in" type="number" min={1} max={24} value={v.security.session_hours} onChange={(e) => upd('security', { session_hours: Number(e.target.value) })} />
            </div>
            <div className="f">
              <label htmlFor="ppl">Minimum password length</label>
              <input id="ppl" className="in" type="number" min={10} max={64} value={v.security.password_min_length} onChange={(e) => upd('security', { password_min_length: Number(e.target.value) })} />
            </div>
          </div>
        </section>
        <section className="card">
          <div className="ch">
            <h3>Admin access to memory content</h3>
          </div>
          <p className="sm muted" style={{ marginTop: 0 }}>
            Admins moderate the scopes you tick below. User (personal) memories are never readable to admins: only a super-user, with an incident reference and
            for a limited time, can open them.
          </p>
          <div className="fx">
            {(['project', 'campaign', 'role', 'organizational', 'enterprise'] as const).map((s) => (
              <label key={s}>
                <span>
                  <input
                    type="checkbox"
                    checked={scopes.includes(s)}
                    onChange={() => upd('privacy', { admin_readable_scopes: scopes.includes(s) ? scopes.filter((x) => x !== s) : [...scopes, s] })}
                  />{' '}
                  {s[0].toUpperCase() + s.slice(1)} memories readable and moderated by admins
                </span>
              </label>
            ))}
          </div>
          <div className="swrow" style={{ marginTop: 16 }}>
            <span>
              Super-user incident access
              <span className="hint" style={{ display: 'block' }}>
                Super-users are set by the deployment (MEMORYHUB_UI_SUPERUSER_GROUP). Each grant needs an incident reference and is logged with HIGH severity.
              </span>
            </span>
            <Switch on={v.privacy.break_glass} onChange={(on) => upd('privacy', { break_glass: on })} label="Super-user incident access" />
          </div>
          {v.privacy.break_glass && (
            <div className="fg">
              <div className="f">
                <label htmlFor="pbh">A grant lasts at most (hours)</label>
                <input id="pbh" className="in" type="number" min={1} max={72} value={v.privacy.break_glass_hours} onChange={(e) => upd('privacy', { break_glass_hours: Number(e.target.value) })} />
              </div>
            </div>
          )}
          <div className="swrow" style={{ marginTop: 16 }}>
            <span>Tell owners when a super-user opens one of their memories</span>
            <Switch on={v.privacy.notify_owner} onChange={(on) => upd('privacy', { notify_owner: on })} label="Notify owners" />
          </div>
        </section>
        <div>
          <button type="button" className="btn bp" disabled={busy} onClick={save}>
            {busy ? 'Saving…' : 'Save policy'}
          </button>
        </div>
      </div>
      <aside className="col-side">
        <section className="card">
          <h3>What each role sees</h3>
          <dl className="dl wide" style={{ marginTop: 14 }}>
            <dt>User</dt>
            <dd className="sm">Full content of their own memories and of the projects, roles and campaigns they belong to, plus organizational and enterprise memories.</dd>
            <dt>Platform admin</dt>
            <dd className="sm">Everything about the platform. For memories: counts, scopes, owners, writing agents, weights, versions, links, flags and activity — never content.</dd>
          </dl>
          <p className="hint" style={{ marginBottom: 0 }}>
            Enforced by the dashboard backend: content never reaches an admin&apos;s browser.
          </p>
        </section>
        {data?.meta.updated_at && (
          <p className="sm muted">
            Last changed {fmtRelative(data.meta.updated_at)} by {data.meta.updated_by}.
          </p>
        )}
      </aside>
    </div>
  );
};

export default Accounts;
