import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { copyText, Empty, ErrorState, Icon, Modal, SkLines, SkTable, Switch, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import type { AccountRow, AccountsResponse, InviteCreated, SettingsResponse, SignupMode, TeamsResponse, TenantSettingsValues } from '@/types';
import { buildHash, navigate } from '@/hooks/useHashRoute';
import { TeamsTable } from './Teams';
import { errorMessage, fmtRelative } from '@/utils/format';

/**
 * Platform admins only: who has a dashboard account, who is waiting for
 * approval, invite codes, and the tenant's sign-up and privacy policy.
 * Shown when local accounts are enabled (MEMORYHUB_UI_LOCAL_ACCOUNTS=true).
 */
type Tab = 'people' | 'teams' | 'invites' | 'policy';

const MODE_LABEL: Record<SignupMode, string> = { invite: 'Invite only', domain: 'Company email domains', open: 'Open', closed: 'Closed' };

const Accounts: React.FC = () => {
  const toast = useToast();
  const { me } = useApp();
  const [tab, setTab] = useState<Tab>('people');
  const { data, error, loading, reload } = useApi<AccountsResponse>(() => api.accounts(), []);
  // Tenant overview › Invite users links here with ?invite=1.
  const [inviteOpen, setInviteOpen] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('invite') === '1');
  const [created, setCreated] = useState<InviteCreated | null>(null);
  const [statusF, setStatusF] = useState('');
  useEffect(() => {
    const h = (e: Event) => setTab((e as CustomEvent<Tab>).detail);
    window.addEventListener('memoryhub:accounts-tab', h);
    return () => window.removeEventListener('memoryhub:accounts-tab', h);
  }, []);
  const teams = useApi<TeamsResponse>(() => api.teams(), []);

  const change = async (a: AccountRow, body: { status?: 'active' | 'disabled'; role?: 'admin' | 'user' }, done: string) => {
    try {
      await api.updateAccount(a.id, body);
      toast(done);
      reload();
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  };


  return (
    <>
      <PageHeader
        title="Users & access"
        crumbs={[{ label: 'Users & access' }]}
        description={`People in ${me?.tenant_id ?? 'this tenant'}, invitations, who can create an account, and what each role sees.`}
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
              { value: 'people', label: 'People', count: data?.counts?.all ?? null },
              { value: 'teams', label: 'Teams', count: teams.data?.items ? teams.data.items.length : null },
              { value: 'invites', label: 'Invites', count: data?.invites ? data.invites.filter((i) => i.state === 'open').length : null },
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
            {(data!.invites ?? []).length === 0 ? (
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
                      <th><span className="vh">Actions</span></th>
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
                        <td className="sm">
                          {i.state === 'used'
                            ? `Used by ${i.used_by}`
                            : i.state === 'expired'
                              ? 'Expired'
                              : i.state === 'revoked'
                                ? `${i.revoke_reason === 'superseded' ? 'Superseded' : 'Revoked'}${i.revoked_by ? ` by ${i.revoked_by}` : ''}`
                                : 'Open'}
                        </td>
                        <td className="sm muted">
                          {fmtRelative(i.created_at)} · {i.created_by}
                        </td>
                        <td className="sm muted">{fmtRelative(i.expires_at)}</td>
                        <td>
                          {i.state === 'open' && (
                            <button
                              type="button"
                              className="btn bs"
                              onClick={async () => {
                                try {
                                  await api.revokeInvite(i.id);
                                  toast('Invite revoked');
                                  reload();
                                } catch (e) {
                                  toast(errorMessage(e), 'err');
                                }
                              }}
                            >
                              Revoke
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ) : tab === 'teams' ? (
          <TeamsTab />
        ) : (
          <PeopleTab data={data!} me={me?.username} change={change} reload={reload} onReview={() => setStatusF('pending')} statusF={statusF} setStatusF={setStatusF} />
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

const ROLE_FILTERS: [string, string][] = [
  ['', 'Role: any'],
  ['user', 'Role: user'],
  ['admin', 'Role: platform admin'],
];
const STATUS_FILTERS: [string, string][] = [
  ['active', 'Status: active'],
  ['', 'Status: any'],
  ['pending', 'Status: waiting for approval'],
  ['incident', 'Status: under incident'],
  ['disabled', 'Status: disabled'],
];

const PeopleTab: React.FC<{
  data: AccountsResponse;
  me?: string;
  change: (a: AccountRow, body: { status?: 'active' | 'disabled'; role?: 'admin' | 'user' }, done: string) => Promise<void>;
  reload: () => void;
  onReview: () => void;
  statusF: string;
  setStatusF: (v: string) => void;
}> = ({ data, me, change, onReview, statusF, setStatusF }) => {
  const settings = useApi<SettingsResponse>(() => api.settings(), []);
  const [q, setQ] = useState('');
  const [roleF, setRoleF] = useState('');
  const [roleFor, setRoleFor] = useState<AccountRow | null>(null);
  const rows = (data.items ?? []).filter((a) => {
    if (roleF && a.role !== roleF) return false;
    if (statusF === 'incident' && !a.incident_ref) return false;
    if (statusF && statusF !== 'incident' && a.status !== statusF) return false;
    if (q && !`${a.display_name} ${a.username} ${a.email}`.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });
  const signup = settings.data?.values.signup;
  return (
    <>
      {(data.counts?.pending ?? 0) > 0 && (
        <div className="alert warn-a" role="status" style={{ alignItems: 'center' }}>
          <Icon.Clock size={16} />
          <span style={{ flex: 1 }}>
            <b>
              {data.counts.pending} account{data.counts.pending === 1 ? ' is' : 's are'} waiting for approval.
            </b>{' '}
            {signup ? `Self sign-up is set to “${signup.mode === 'invite' ? 'invite only' : signup.require_approval ? 'approval required' : MODE_LABEL[signup.mode].toLowerCase()}”.` : ''}
          </span>
          <button type="button" className="btn bs sm-btn" onClick={onReview}>
            Review
          </button>
        </div>
      )}
      <div className="filters">
        <span className="in-icon">
          <Icon.Search size={15} />
          <label htmlFor="pp-q" className="vh">
            Search people
          </label>
          <input id="pp-q" className="in" placeholder="Search people" value={q} onChange={(e) => setQ(e.target.value)} />
        </span>
        <label htmlFor="pp-r" className="vh">
          Role
        </label>
        <select id="pp-r" className="in auto" value={roleF} onChange={(e) => setRoleF(e.target.value)}>
          {ROLE_FILTERS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <label htmlFor="pp-s" className="vh">
          Status
        </label>
        <select id="pp-s" className="in auto" value={statusF} onChange={(e) => setStatusF(e.target.value)}>
          {STATUS_FILTERS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </div>
      <section className="card" style={{ padding: '6px 12px' }}>
        {rows.length === 0 ? (
          <Empty compact title="No people match">
            {statusF === 'pending' ? 'Nobody is waiting for approval.' : 'People appear here when they sign up or accept an invite.'}
          </Empty>
        ) : (
          <div className="scroll">
            <table className="tbl mid">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Tenant role</th>
                  <th>Projects</th>
                  <th>Agents</th>
                  <th>Last active</th>
                  <th>Status</th>
                  <th>
                    <span className="vh">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const self = a.username === me;
                  const last = a.last_active_at ?? a.last_login_at;
                  return (
                    <tr key={a.id}>
                      <td>
                        <b>{a.display_name}</b>
                        {self && <span className="muted sm"> (you)</span>}
                        <div className="sm muted">{a.username}</div>
                      </td>
                      <td>
                        {a.superuser ? (
                          <span className="lbl org">Super Admin</span>
                        ) : a.role === 'admin' ? (
                          <span className="lbl role-pa">Platform Admin</span>
                        ) : (
                          'User'
                        )}
                      </td>
                      <td>{a.status === 'pending' ? '—' : a.projects ?? '—'}</td>
                      <td>{a.status === 'pending' ? '—' : a.agents ?? '—'}</td>
                      <td className="sm">{a.status === 'pending' || !last ? '—' : fmtRelative(last)}</td>
                      <td>
                        {a.incident_ref ? (
                          <span className="lbl ylw">Under incident {a.incident_ref}</span>
                        ) : a.status === 'pending' ? (
                          <span className="lbl blue">Waiting for approval</span>
                        ) : a.status === 'disabled' ? (
                          <span className="lbl g">Disabled</span>
                        ) : (
                          <span className="lbl grn">Active</span>
                        )}
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <span className="row-links">
                          {a.status === 'pending' ? (
                            <>
                              <button type="button" className="btn bs sm-btn" onClick={() => change(a, { status: 'active' }, `${a.username} approved.`)}>
                                Approve
                              </button>
                              <button type="button" className="link-btn" onClick={() => change(a, { status: 'disabled' }, `${a.username} declined.`)}>
                                Decline
                              </button>
                            </>
                          ) : a.status === 'disabled' ? (
                            <button type="button" className="link-btn" onClick={() => change(a, { status: 'active' }, `${a.username} re-enabled.`)}>
                              Enable
                            </button>
                          ) : a.incident_ref ? (
                            <button type="button" className="link-btn" onClick={() => navigate('/identities', new URLSearchParams({ q: a.username }))}>
                              Revoke sessions
                            </button>
                          ) : (
                            <>
                              <button type="button" className="link-btn" disabled={self} onClick={() => setRoleFor(a)}>
                                Change role
                              </button>
                              {a.role !== 'admin' && (
                                <a className="link-btn" href={buildHash('/identities', { q: a.username })}>
                                  Sessions
                                </a>
                              )}
                            </>
                          )}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <AccessCards settings={settings} />
      {roleFor && <RoleModal account={roleFor} onClose={() => setRoleFor(null)} change={change} />}
    </>
  );
};

const RoleModal: React.FC<{
  account: AccountRow;
  onClose: () => void;
  change: (a: AccountRow, body: { status?: 'active' | 'disabled'; role?: 'admin' | 'user' }, done: string) => Promise<void>;
}> = ({ account: a, onClose, change }) => {
  const [role, setRole] = useState<'user' | 'admin' | 'disabled'>(a.role);
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title={`Change role · ${a.display_name}`}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className={`btn ${role === 'disabled' ? 'bd' : 'bp'}`}
            disabled={busy || role === a.role}
            onClick={async () => {
              setBusy(true);
              if (role === 'disabled') await change(a, { status: 'disabled' }, `${a.username} disabled.`);
              else await change(a, { role }, role === 'admin' ? `${a.username} is now a platform admin.` : `${a.username} is now a user.`);
              setBusy(false);
              onClose();
            }}
          >
            {role === 'disabled' ? 'Disable account' : 'Save role'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="radio-list">
        {(
          [
            ['user', 'User', 'Own memory and the projects they are a member of.'],
            ['admin', 'Platform Admin', 'Tenant control and moderation; memory metadata only, never personal content.'],
            ['disabled', 'Disable account', 'Signs the person out and blocks their agents; nothing is deleted.'],
          ] as const
        ).map(([v, l, d]) => (
          <label key={v} className={`radio ${role === v ? 'on' : ''}`}>
            <input type="radio" name="acc-role" checked={role === v} onChange={() => setRole(v)} />
            <span>
              <b>{l}</b>
              <span className="hint" style={{ display: 'block' }}>
                {d}
              </span>
            </span>
          </label>
        ))}
      </div>
      <p className="sm muted" style={{ margin: '10px 0 0' }}>
        Super Admin is granted by the platform, not here. The change is recorded as an administrative event.
      </p>
    </Modal>
  );
};

const ALL_SCOPES = ['project', 'campaign', 'role', 'organizational', 'enterprise'] as const;
const SCOPE_NAME: Record<string, string> = { project: 'Project*', campaign: 'Campaign', role: 'Role', organizational: 'Org', enterprise: 'Enterprise' };

/** Sign-up mode, which scopes admins moderate, and what each role sees. */
const AccessCards: React.FC<{ settings: ReturnType<typeof useApi<SettingsResponse>> }> = ({ settings }) => {
  const toast = useToast();
  const [v, setV] = useState<TenantSettingsValues | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (settings.data) setV(structuredClone(settings.data.values));
  }, [settings.data]);
  if (!v || !settings.data)
    return (
      <div className="card">
        <SkLines lines={4} />
      </div>
    );
  const domain = v.signup.allowed_domains[0];
  const mode = v.signup.mode === 'invite' || v.signup.mode === 'closed' ? 'invite' : v.signup.mode === 'domain' ? 'domain' : 'approval';
  const setMode = (m: string) =>
    setV({ ...v, signup: { ...v.signup, mode: m === 'invite' ? 'invite' : m === 'domain' ? 'domain' : 'open', require_approval: m === 'approval' ? true : v.signup.require_approval } });
  const scopes = v.privacy.admin_readable_scopes;
  const dirty = JSON.stringify({ s: v.signup, p: v.privacy }) !== JSON.stringify({ s: settings.data.values.signup, p: settings.data.values.privacy });
  const save = async () => {
    setBusy(true);
    try {
      const res = await api.saveSettings({ signup: v.signup, privacy: v.privacy });
      settings.setData(res);
      toast('Access policy saved.');
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="acc-cards">
        <section className="card">
          <h2 data-h="3">Who can create an account</h2>
          <div className="radio-plain">
            {(
              [
                ['invite', 'Invite only'],
                ['approval', 'Self sign-up, approval required'],
                ['domain', `Self sign-up for ${domain ? `@${domain}` : 'company domains'}`],
              ] as const
            ).map(([m, l]) => (
              <label key={m}>
                <input type="radio" name="who-signup" checked={mode === m} onChange={() => setMode(m)} />
                {l}
              </label>
            ))}
          </div>
          {mode === 'domain' && !domain && <p className="sm muted">Set the allowed domains on the Sign-up &amp; privacy policy tab.</p>}
        </section>
        <section className="card">
          <h2 data-h="3">Admin access to memory content</h2>
          <p className="sm muted" style={{ margin: '8px 0 12px' }}>
            Scopes admins may moderate in this tenant. Personal content is never readable to admins — only through an addressed incident grant approved by two Super Admins.
          </p>
          <div className="scope-checks">
            {ALL_SCOPES.map((sc) => (
              <label key={sc} className="scope-check">
                <input
                  type="checkbox"
                  checked={scopes.includes(sc)}
                  onChange={() => setV({ ...v, privacy: { ...v.privacy, admin_readable_scopes: scopes.includes(sc) ? scopes.filter((x) => x !== sc) : [...scopes, sc] } })}
                />
                {SCOPE_NAME[sc]}
              </label>
            ))}
            <label className="scope-check dis">
              <input type="checkbox" checked={false} disabled />
              Personal
            </label>
          </div>
          <p className="sm muted" style={{ margin: '10px 0 0' }}>
            * moderation actions on all projects; reading project text needs membership or an assigned workflow
          </p>
        </section>
        <section className="card">
          <h2 data-h="3">What each role sees</h2>
          <ul className="role-sees">
            <li>
              <span className="lbl blue">User</span> Own + member scopes
            </li>
            <li>
              <span className="lbl role-pa">PA</span> Tenant control, metadata
            </li>
            <li>
              <span className="lbl org">SA</span> Platform control, incident grants
            </li>
          </ul>
          <a className="sm" href={buildHash('/accounts', { tab: 'policy' })} onClick={(e) => {
            e.preventDefault();
            window.dispatchEvent(new CustomEvent('memoryhub:accounts-tab', { detail: 'policy' }));
          }}>
            Full permission matrix
          </a>
        </section>
      </div>
      {dirty && (
        <div className="savebar" role="status">
          <span style={{ flex: 1 }}>Access policy changed.</span>
          <button type="button" className="btn bg" onClick={() => setV(structuredClone(settings.data!.values))}>
            Discard
          </button>
          <button type="button" className="btn bp" disabled={busy} onClick={save}>
            Save · audited
          </button>
        </div>
      )}
    </>
  );
};

const TeamsTab: React.FC = () => {
  const { data, loading, error, reload } = useApi<TeamsResponse>(() => api.teams(), []);
  const [q, setQ] = useState('');
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  return (
    <>
      <div className="filters">
        <span className="in-icon">
          <Icon.Search size={15} />
          <label htmlFor="tm-q" className="vh">
            Search teams
          </label>
          <input id="tm-q" className="in" placeholder="Search teams or members" value={q} onChange={(e) => setQ(e.target.value)} />
        </span>
        <span className="sm muted" style={{ marginLeft: 'auto' }}>
          Double-click a team for its summary · manage teams in Projects &amp; teams
        </span>
      </div>
      <section className="card" style={{ padding: 0 }}>
        <TeamsTable
          teams={data?.items ?? []}
          loading={loading && !data}
          active={null}
          filter={q}
          onSelect={(id) => navigate(`/team/${id}`)}
          onOpen={(id) => navigate(`/team/${id}`)}
          onCreate={() => navigate('/projects', new URLSearchParams({ kind: 'teams' }))}
        />
      </section>
    </>
  );
};

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
            <h2 data-h="3">Organization</h2>
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
            <h2 data-h="3">Who can create an account</h2>
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
            <h2 data-h="3">Admin access to memory content</h2>
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
          <h2 data-h="3">What each role sees</h2>
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
