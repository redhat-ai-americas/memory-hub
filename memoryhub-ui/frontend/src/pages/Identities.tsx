import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Modal, SelectMenu, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { IdentityDetail, IdentityRow } from '@/types';
import { avatarColor, errorMessage, fmtInt, fmtRelative, initials, scopeMeta } from '@/utils/format';
import { CreateClientModal } from './Clients';

const TYPE_LABEL: Record<string, { cls: string; label: string }> = {
  user: { cls: 'blue', label: 'user' },
  'user agent': { cls: 'g', label: 'user agent' },
  service: { cls: 'pur', label: 'service' },
};

const Identities: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { role: viewerRole, me } = useApp();
  const isUser = viewerRole === 'user';
  const tab = route.params.get('type') || 'all';
  const selectedId = route.params.get('id');
  const [filter, setFilter] = useState('');
  const [role, setRole] = useState('');
  const [status, setStatus] = useState('');
  const [modal, setModal] = useState<null | 'service' | 'agent' | 'link' | 'role'>(null);
  const { data, error, loading, reload } = useApi(() => api.identities(), []);

  const setParam = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(route.params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    navigate('/identities', next, { replace: true });
  };

  const rows = (data?.items ?? []).filter((i) => {
    if (tab === 'users' && i.type !== 'user') return false;
    if (tab === 'agents' && i.type !== 'user agent') return false;
    if (tab === 'services' && i.type !== 'service') return false;
    if (role && !i.roles.includes(role)) return false;
    if (status === 'active' && !i.active_now) return false;
    if (status === 'inactive' && i.active_now) return false;
    if (status === 'revoked' && i.active) return false;
    const f = filter.toLowerCase();
    return !f || i.id.toLowerCase().includes(f) || i.name.toLowerCase().includes(f);
  });
  const active = rows.find((r) => r.id === selectedId) ?? rows.find((r) => r.type === 'service') ?? rows[0];

  return (
    <>
      <PageHeader
        title={isUser ? 'My agents' : 'Users & agents'}
        crumbs={[{ label: isUser ? 'My agents' : 'Users & agents' }]}
        description={
          isUser
            ? 'You and the agents that act for you. Register a new agent, link one you already run, rotate its credentials or revoke it. Their memories are yours.'
            : 'Every identity that can touch memory. User-bound agents act for a person; service agents such as the curator have their own, narrowly scoped identity.'
        }
        actions={
          isUser ? (
            <>
              <button type="button" className="btn bs" onClick={() => setModal('link')}>
                Link an existing agent
              </button>
              <button type="button" className="btn bp" onClick={() => setModal('agent')}>
                Register an agent
              </button>
            </>
          ) : (
          <>
            <button
              type="button"
              className="btn bs"
              disabled
              title="Group sync is configured in the auth service (MEMORYHUB_OPENSHIFT_ALLOWED_GROUP); the dashboard cannot trigger it."
            >
              Sync from OpenShift groups
            </button>
            <button type="button" className="btn bp" onClick={() => setModal('service')}>
              Add service agent
            </button>
          </>
          )
        }
        tabs={
          <Tabs
            label="Identity type"
            value={tab}
            onChange={(t) => setParam({ type: t === 'all' ? undefined : t, id: undefined })}
            tabs={
              isUser
                ? [
                    { value: 'all', label: 'All', count: data?.counts.all ?? null },
                    { value: 'agents', label: 'My agents', count: data?.counts.user_agents ?? null },
                  ]
                : [
                    { value: 'all', label: 'All', count: data?.counts.all ?? null },
                    { value: 'users', label: 'Users', count: data?.counts.users ?? null },
                    { value: 'agents', label: 'User agents', count: data?.counts.user_agents ?? null },
                    { value: 'services', label: 'Service agents', count: data?.counts.service_agents ?? null },
                    { value: 'roles', label: 'Roles', count: data?.counts.roles ?? null },
                  ]
            }
          />
        }
      />
      <div className="body">
        {data && !data.auth_available && (
          <div className="alert warn-a">
            The auth service did not answer, so identities are inferred from memory owners and audit events only. Scopes and grant types are unavailable.
          </div>
        )}
        <div className="row-wrap">
          <section className="card" style={{ flex: '999 1 560px', padding: 0, minWidth: 0 }}>
            {tab === 'roles' ? (
              <RolesTable roles={data?.roles ?? []} loading={loading && !data} onAssign={() => setModal('role')} />
            ) : (
              <>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: '16px 20px' }}>
                  <label htmlFor="f" className="vh">
                    Filter identities
                  </label>
                  <input id="f" className="in" placeholder="Filter by name or ID" style={{ flex: '1 1 260px' }} value={filter} onChange={(e) => setFilter(e.target.value)} />
                  {!isUser && <SelectMenu
                    label="Role"
                    value={role}
                    onChange={setRole}
                    options={[{ value: '', label: 'Role: any' }, ...(data?.roles ?? []).map((r) => ({ value: r.name, label: `Role: ${r.name}` }))]}
                  />}
                  <SelectMenu
                    label="Status"
                    value={status}
                    onChange={setStatus}
                    options={[
                      { value: '', label: 'Status: any' },
                      { value: 'active', label: 'Status: active now' },
                      { value: 'inactive', label: 'Status: not active' },
                      { value: 'revoked', label: 'Status: revoked' },
                    ]}
                  />
                </div>
                {error && !data ? (
                  <ErrorState error={error} onRetry={reload} />
                ) : loading && !data ? (
                  <SkTable rows={7} cols={5} />
                ) : rows.length === 0 ? (
                  <Empty
                    title={filter || role || status ? 'No identities match' : 'No identities yet'}
                    action={
                      !(filter || role || status) && (
                        <a className="btn bp" href={buildHash('/clients')}>
                          Create an OAuth client
                        </a>
                      )
                    }
                  >
                    {filter || role || status ? 'Clear a filter to see more.' : 'Identities appear when an OAuth client is created or an agent writes its first memory.'}
                  </Empty>
                ) : (
                  <div className="scroll">
                    <table className="tbl" style={{ minWidth: 780 }}>
                      <thead>
                        <tr>
                          <th>Identity</th>
                          <th>Type</th>
                          <th>Operational scopes</th>
                          <th>Roles</th>
                          <th>Memories</th>
                          <th>Last active</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((i) => (
                          <tr key={i.id} className={`clickable ${active?.id === i.id ? 'is-sel' : ''}`} onClick={() => setParam({ id: i.id })}>
                            <td>
                              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                                <span className="idav" style={{ background: avatarColor(i.id) }}>
                                  {initials(i.name)}
                                </span>
                                <div>
                                  <div style={{ fontWeight: 600 }}>{i.name}</div>
                                  <div className="mono muted">{i.bound_to ? `${i.id} → ${i.bound_to}` : i.id}</div>
                                </div>
                              </div>
                            </td>
                            <td>
                              <span className={`lbl ${TYPE_LABEL[i.type]?.cls ?? 'g'}`}>{TYPE_LABEL[i.type]?.label ?? i.type}</span>
                            </td>
                            <td style={{ maxWidth: 280 }}>
                              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                {i.scopes.length ? i.scopes.map((s) => <span className="code" key={s}>{s}</span>) : <span className="sm muted">{i.client ? '—' : 'no OAuth client'}</span>}
                              </div>
                            </td>
                            <td className="sm">{i.roles.length ? i.roles.join(', ') : i.bound_to ? `inherits ${i.bound_to}` : '—'}</td>
                            <td>{fmtInt(i.memory_count)}</td>
                            <td className="sm">
                              {!i.active ? <span className="err">Revoked</span> : i.active_now ? <span className="ok">● Active now</span> : <span className="muted">{fmtRelative(i.last_active)}</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </section>

          <aside className="card" style={{ flex: '1 1 360px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {loading && !data ? (
              <SkLines lines={10} />
            ) : active && tab !== 'roles' ? (
              <IdentityPanel row={active} key={active.id} canAssignOwner={!isUser} self={me?.username} onClose={() => setParam({ id: undefined })} onChanged={reload} />
            ) : (
              <Empty compact title="Select an identity">
                See its scope permissions and the last 24 hours of activity.
              </Empty>
            )}
          </aside>
        </div>
      </div>
      {modal === 'agent' && (
        <CreateClientModal
          defaultType="user"
          onClose={() => setModal(null)}
          onCreated={() => {
            reload();
          }}
        />
      )}
      {modal === 'link' && (
        <LinkAgentModal
          onClose={() => setModal(null)}
          onLinked={(id) => {
            setModal(null);
            toast(`${id} is now linked to you.`);
            reload();
          }}
        />
      )}
      {modal === 'service' && (
        <CreateClientModal
          defaultType="service"
          onClose={() => setModal(null)}
          onCreated={() => {
            reload();
          }}
        />
      )}
      {modal === 'role' && (
        <AssignRoleModal
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Role assigned.');
            reload();
          }}
        />
      )}
    </>
  );
};

const RolesTable: React.FC<{ roles: { name: string; members: number }[]; loading: boolean; onAssign: () => void }> = ({ roles, loading, onAssign }) => (
  <>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px' }}>
      <h3>Roles</h3>
      <button type="button" className="btn bl sm" onClick={onAssign}>
        + Assign role
      </button>
    </div>
    {loading ? (
      <SkTable rows={4} cols={2} />
    ) : roles.length === 0 ? (
      <Empty title="No roles assigned">Role-scoped memories are readable only by holders of that role. Assign one to get started.</Empty>
    ) : (
      <table className="tbl">
        <thead>
          <tr>
            <th>Role</th>
            <th>Holders</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {roles.map((r) => (
            <tr key={r.name}>
              <td className="mono">{r.name}</td>
              <td>{r.members}</td>
              <td>
                <a href={buildHash('/memories', { scope: 'role' })}>Role memories</a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )}
  </>
);

const IdentityPanel: React.FC<{ row: IdentityRow; canAssignOwner: boolean; self?: string; onClose: () => void; onChanged: () => void }> = ({
  row,
  canAssignOwner,
  self,
  onClose,
  onChanged,
}) => {
  const toast = useToast();
  const { data, error, loading, reload } = useApi<IdentityDetail>(() => api.identity(row.id), [row.id]);
  const [owner, setOwner] = useState<string | null>(null);
  const saveOwner = async () => {
    try {
      const res = await api.assignOwner(row.id, owner?.trim() || null);
      toast(res.owner ? `${row.id} now belongs to ${res.owner}.` : `Owner cleared for ${row.id}.`);
      setOwner(null);
      reload();
      onChanged();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };
  const typeLabel = row.type === 'service' ? 'Service agent' : row.type === 'user agent' ? `User agent · acts for ${row.bound_to}` : 'User';
  return (
    <>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <span className="idav" style={{ background: avatarColor(row.id), width: 44, height: 44, fontSize: 14 }}>
          {initials(row.name)}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3 style={{ fontSize: 18 }}>{row.name}</h3>
          <div className="sm muted">{typeLabel}</div>
        </div>
        <button type="button" className="btn bl" aria-label="Close" onClick={onClose}>
          ✕
        </button>
      </div>
      {error && !data ? (
        <ErrorState error={error} onRetry={reload} compact />
      ) : loading && !data ? (
        <SkLines lines={8} />
      ) : (
        data && (
          <>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <span className={`lbl ${TYPE_LABEL[data.type]?.cls ?? 'g'}`}>{TYPE_LABEL[data.type]?.label ?? data.type}</span>
              {data.grant && <span className="lbl g">OAuth {data.grant}</span>}
              {!data.active && <span className="lbl red">Revoked</span>}
              {data.roles.map((r) => (
                <span key={r} className="lbl s-role">
                  {r}
                </span>
              ))}
            </div>
            <div>
              <div className="ch" style={{ marginBottom: 6 }}>
                <b className="sm">Scope permissions</b>
                {data.client && (
                  <a className="btn bl sm" href={buildHash('/clients', { client: data.id })}>
                    Edit
                  </a>
                )}
              </div>
              {data.scope_matrix ? (
                <table className="mx">
                  <thead>
                    <tr>
                      <th>Tier</th>
                      <th>Read</th>
                      <th>Write</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.scope_matrix.map((m) => (
                      <tr key={m.tier}>
                        <td>{scopeMeta(m.tier).label}</td>
                        <td className={m.read ? 'y' : 'n'}>{m.read ? '✓' : '—'}</td>
                        <td className={m.write === 'yes' ? 'y' : m.write === 'no' ? 'n' : 'sm muted'}>
                          {m.write === 'yes' ? '✓' : m.write === 'no' ? '—' : m.write}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="sm muted" style={{ margin: 0 }}>
                  {data.client ? 'This client has no default scopes.' : 'No OAuth client — permissions come from the agent that writes on this identity’s behalf.'}
                </p>
              )}
            </div>
            <div>
              <b className="sm">Last 24 h</b>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10, marginTop: 8, fontSize: 13 }}>
                <div>
                  <div className="muted">Searches</div>
                  <div className="num-lg" style={{ fontSize: 20 }}>{fmtInt(data.activity_24h.searches)}</div>
                </div>
                <div>
                  <div className="muted">Writes</div>
                  <div className="num-lg" style={{ fontSize: 20 }}>{fmtInt(data.activity_24h.writes)}</div>
                </div>
                <div>
                  <div className="muted">Denied</div>
                  <div className="num-lg" style={{ fontSize: 20 }}>{fmtInt(data.activity_24h.denied)}</div>
                </div>
              </div>
              <Spark hourly={data.hourly} />
            </div>
            {row.type !== 'user' && (
              <div>
                <b className="sm">Belongs to</b>
                {owner === null ? (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}>
                    <span className="sm">{row.owner ? (row.owner === self ? `${row.owner} (you)` : row.owner) : <span className="muted">No owner yet</span>}</span>
                    {canAssignOwner && (
                      <button type="button" className="btn bl sm" onClick={() => setOwner(row.owner ?? '')}>
                        {row.owner ? 'Change' : 'Assign owner'}
                      </button>
                    )}
                  </div>
                ) : (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
                    <label className="vh" htmlFor="owner">
                      Owner username
                    </label>
                    <input id="owner" className="in" style={{ flex: '1 1 160px' }} value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="OpenShift username" />
                    <button type="button" className="btn bp sm" onClick={saveOwner}>
                      Save
                    </button>
                    <button type="button" className="btn bl sm" onClick={() => setOwner(null)}>
                      Cancel
                    </button>
                  </div>
                )}
                <p className="hint" style={{ margin: '6px 0 0' }}>
                  The owner sees this agent&apos;s memories as their own and manages its credentials.
                </p>
              </div>
            )}
            {data.agents.length > 0 && (
              <div>
                <b className="sm">Agents acting for {data.name}</b>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                  {data.agents.map((a) => (
                    <a key={a.id} href={buildHash('/identities', { id: a.id })} className="lbl g link-plain">
                      {a.name}
                    </a>
                  ))}
                </div>
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <a className="btn bs" href={buildHash('/audit', { tab: 'log', actor: data.id })}>
                View activity
              </a>
              {data.client && (
                <a className="btn bg" href={buildHash('/clients', { client: data.id })}>
                  Rotate credentials
                </a>
              )}
            </div>
          </>
        )
      )}
    </>
  );
};

/** 24 one-hour bars of audit events. */
const Spark: React.FC<{ hourly: { hour: string; count: number }[] }> = ({ hourly }) => {
  if (!hourly.length) return null;
  const now = new Date();
  now.setMinutes(0, 0, 0);
  const counts = Array.from({ length: 24 }, (_, i) => {
    const t = new Date(now.getTime() - (23 - i) * 3600_000).getTime();
    return hourly.find((h) => Math.abs(new Date(h.hour).getTime() - t) < 1000)?.count ?? 0;
  });
  const max = Math.max(1, ...counts);
  return (
    <svg viewBox="0 0 240 36" style={{ width: '100%', height: 36, marginTop: 10 }} role="img" aria-label="Events per hour, last 24 hours">
      {counts.map((c, i) => (
        <rect key={i} x={i * 10} y={36 - (c / max) * 34} width="7" height={(c / max) * 34 || 1} rx="1.5" fill={c ? '#0066cc' : '#e6e6e6'} />
      ))}
    </svg>
  );
};

const LinkAgentModal: React.FC<{ onClose: () => void; onLinked: (id: string) => void }> = ({ onClose, onLinked }) => {
  const [clientId, setClientId] = useState('');
  const [secret, setSecret] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title="Link an existing agent"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy || !clientId.trim() || !secret}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await api.linkAgent(clientId.trim(), secret);
                onLinked(clientId.trim());
              } catch (e) {
                setErr(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? 'Checking…' : 'Link agent'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <p className="sm muted" style={{ margin: 0 }}>
        Prove the agent is yours with its OAuth client ID and secret. The secret is checked with the auth service and never stored. If you lost it, ask a platform admin to
        assign the agent to you.
      </p>
      <div className="f">
        <label htmlFor="lcid">client_id</label>
        <input id="lcid" className="in mono" value={clientId} onChange={(e) => setClientId(e.target.value)} />
      </div>
      <div className="f">
        <label htmlFor="lsec">Client secret</label>
        <input id="lsec" className="in mono" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" />
      </div>
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

const AssignRoleModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const [user, setUser] = useState('');
  const [role, setRole] = useState('');
  const [err, setErr] = useState<string | null>(null);
  return (
    <Modal
      title="Assign role"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={!user.trim() || !role.trim()}
            onClick={async () => {
              try {
                await api.assignRole(user.trim(), role.trim());
                onSaved();
                onClose();
              } catch (e) {
                setErr(errorMessage(e));
              }
            }}
          >
            Assign
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="ru">User ID</label>
        <input id="ru" className="in" value={user} onChange={(e) => setUser(e.target.value)} />
      </div>
      <div className="f">
        <label htmlFor="rr">Role</label>
        <input id="rr" className="in" value={role} onChange={(e) => setRole(e.target.value)} placeholder="sre-oncall" />
      </div>
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

export default Identities;
