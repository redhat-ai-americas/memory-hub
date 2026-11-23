import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { renderWelcomeEmail } from '@/components/welcomeEmail';
import { copyText, Empty, ErrorState, Icon, Modal, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import type { HashRoute } from '@/hooks/useHashRoute';
import type { ClientResponse, PublicConfig } from '@/types';
import { errorMessage, fmtRelative } from '@/utils/format';
import { ConfirmModal } from './common';

/** Use the client policy published by the BFF for the verified principal. */
const useScopeOptions = () => {
  const { me } = useApp();
  return me?.capabilities.clients.scopes ?? [];
};

/** Freshly issued credentials, shown once. */
export interface Revealed {
  title: string;
  clientId: string;
  clientName: string;
  secret: string | null;
  apiKey: string | null;
  scopes: string[];
}

// QA 2026-11-10 D3 / BR-PA2-04: what revocation really does (memory-hub-mcp core/revocation.py).
const REVOCATION_TIMING =
  'Tokens and API-key sessions it already holds are refused within 5 seconds on every MCP server, and on the next request for admin-level clients.';
const REVOKED_TOAST = 'Client revoked. New tokens are refused now; existing tokens and sessions stop within 5 seconds.';

/**
 * OAuth clients (GET /api/clients, proxied to the auth service). Users see and
 * manage their own agents' clients; admins see the tenant's clients and create
 * service clients. Every client gets a secret and an API key, shown once.
 */
const Clients: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { me, role } = useApp();
  const focusClient = route.params.get('client');
  const { data, error, loading, reload } = useApi(() => api.clients(), []);
  const [revealed, setRevealed] = useState<Revealed | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ClientResponse | null>(null);
  const [confirm, setConfirm] = useState<null | { kind: 'secret' | 'key' | 'revoke' | 'restore'; row: ClientResponse }>(null);
  // QA 2026-11-10 BR-PA2-04: show the confirmed revoke/re-activate at once.
  const [applied, setApplied] = useState<Record<string, boolean>>({});
  useEffect(() => setApplied({}), [data]);
  const rows = (data ?? []).map((c) => (c.client_id in applied ? { ...c, active: applied[c.client_id] } : c));
  const [q, setQ] = useState('');
  const [statusF, setStatusF] = useState('');
  const [typeF, setTypeF] = useState('');
  const shown = rows.filter((c) => {
    if (typeF && c.identity_type !== typeF) return false;
    if (statusF === 'active' && !c.active) return false;
    if (statusF === 'revoked' && c.active) return false;
    if (q && !`${c.client_name} ${c.client_id}`.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });

  const doConfirm = async () => {
    if (!confirm) return;
    const { kind, row } = confirm;
    if (kind === 'secret') {
      const res = await api.rotateSecret(row.client_id);
      setRevealed({ title: `Secret rotated · ${row.client_name}`, clientId: row.client_id, clientName: row.client_name, secret: res.client_secret, apiKey: res.api_key, scopes: row.default_scopes });
    } else if (kind === 'key') {
      const res = await api.rotateApiKey(row.client_id);
      setRevealed({ title: `API key issued · ${row.client_name}`, clientId: row.client_id, clientName: row.client_name, secret: null, apiKey: res.api_key, scopes: row.default_scopes });
    } else {
      await api.updateClient(row.client_id, { active: kind === 'restore' });
      setApplied((prev) => ({ ...prev, [row.client_id]: kind === 'restore' }));
      toast(kind === 'restore' ? 'Client re-activated.' : REVOKED_TOAST);
    }
    reload();
  };

  return (
    <>
      <PageHeader
        title="OAuth clients & keys"
        crumbs={[{ label: 'OAuth clients & keys' }]}
        description={
          role === 'user'
            ? 'Credentials your agents use to reach the MCP server and SDK. A secret and an API key are shown once when they are issued; nobody can view them later.'
            : 'The tenant’s OAuth clients. You create service clients that read the scopes you moderate. Secrets and API keys are shown once; nobody can view them later, including you.'
        }
        actions={
          <button type="button" className="btn bp" disabled={!data || !me?.capabilities.clients.can_create} onClick={() => setCreating(true)}>
            <Icon.Plus /> {role === 'user' ? 'New OAuth client' : 'New service client'}
          </button>
        }
      />
      <div className="body">
        {revealed && <RevealCard revealed={revealed} onDismiss={() => setRevealed(null)} />}
        {data && (
          <div className="filters">
            <span className="in-icon">
              <Icon.Search size={15} />
              <label htmlFor="cl-q" className="vh">
                Search clients
              </label>
              <input id="cl-q" className="in" placeholder="Search clients" value={q} onChange={(e) => setQ(e.target.value)} />
            </span>
            <label htmlFor="cl-s" className="vh">
              Status
            </label>
            <select id="cl-s" className="in auto" value={statusF} onChange={(e) => setStatusF(e.target.value)}>
              <option value="">Status: any</option>
              <option value="active">Status: Active</option>
              <option value="revoked">Status: Revoked</option>
            </select>
            {role !== 'user' && (
              <>
                <label htmlFor="cl-o" className="vh">
                  Identity type
                </label>
                <select id="cl-o" className="in auto" value={typeF} onChange={(e) => setTypeF(e.target.value)}>
                  <option value="">Identity type: any</option>
                  <option value="service">Identity type: service</option>
                  <option value="user">Identity type: user agent</option>
                </select>
              </>
            )}
          </div>
        )}
        <section className="card" style={{ padding: '6px 12px' }}>
          {error && !data ? (
            <ErrorState error={error} onRetry={reload} title="Clients could not be loaded" />
          ) : loading && !data ? (
            <SkTable rows={7} cols={5} />
          ) : shown.length === 0 ? (
            <Empty
              compact
              title={rows.length ? 'Nothing matches' : 'No OAuth clients yet'}
              action={
                !rows.length && (
                  <button type="button" className="btn bp" disabled={!me?.capabilities.clients.can_create} onClick={() => setCreating(true)}>
                    {role === 'user' ? 'New OAuth client' : 'New service client'}
                  </button>
                )
              }
            >
              {rows.length ? 'Clear a filter to see more.' : 'Create a client for each agent or service that should read or write memory.'}
            </Empty>
          ) : (
            <div className="scroll">
              <table className="tbl mid" style={{ minWidth: 760 }}>
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Type</th>
                    <th>Scopes allowed</th>
                    <th>Updated</th>
                    <th>Status</th>
                    <th>
                      <span className="vh">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((c) => (
                    <tr key={c.client_id} className={c.client_id === focusClient ? 'is-sel' : ''}>
                      <td>
                        <b>{c.client_name}</b>
                        <div className="mono sm muted">{c.client_id}</div>
                      </td>
                      <td>{c.identity_type === 'service' ? 'service' : 'user agent'}</td>
                      <td className="sm" style={{ maxWidth: 260 }}>
                        {c.default_scopes.map((x) => x.replace(/^memory:/, '')).join(' · ') || '—'}
                      </td>
                      <td className="sm" style={{ whiteSpace: 'nowrap' }}>
                        {fmtRelative(c.updated_at)}
                      </td>
                      <td>
                        <span className={`lbl ${c.active ? 'grn' : 'g'}`}>{c.active ? 'Active' : 'Revoked'}</span>
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <span className="row-links stack-links">
                          {!c.active ? (
                            role !== 'user' ? (
                              <button type="button" className="link-btn" onClick={() => setConfirm({ kind: 'restore', row: c })}>
                                Re-activate
                              </button>
                            ) : (
                              <span className="sm muted">Ask an admin</span>
                            )
                          ) : (
                            <>
                              {/* The BFF rotates credentials only for clients this person owns. */}
                              {(role === 'user' || c.owned) && (
                                <>
                                  <button type="button" className="link-btn" onClick={() => setConfirm({ kind: 'secret', row: c })}>
                                    Rotate secret
                                  </button>
                                  <button type="button" className="link-btn" onClick={() => setConfirm({ kind: 'key', row: c })}>
                                    Rotate API key
                                  </button>
                                </>
                              )}
                              <button type="button" className="link-btn" onClick={() => setConfirm({ kind: 'revoke', row: c })}>
                                Revoke
                              </button>
                            </>
                          )}
                          <button type="button" className="link-btn muted-link" onClick={() => setEditing(c)}>
                            Edit
                          </button>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {role !== 'user' && (
          <div className="alert" role="note">
            <Icon.Info size={16} />
            <span className="sm">
              Users manage their own agents’ clients in My agents. You can revoke or re-activate any client in the tenant, and rotate credentials only for clients you own.
            </span>
          </div>
        )}
      </div>

      {creating && (
        <CreateClientModal
          onClose={() => setCreating(false)}
          onCreated={(r) => {
            setRevealed(r);
            reload();
          }}
        />
      )}
      {editing && <EditClientModal row={editing} onClose={() => setEditing(null)} onSaved={reload} />}
      {confirm && (
        <ConfirmModal
          title={
            confirm.kind === 'secret'
              ? 'Rotate client secret?'
              : confirm.kind === 'key'
                ? 'Rotate API key?'
                : confirm.kind === 'revoke'
                  ? `Revoke ${confirm.row.client_name}?`
                  : `Re-activate ${confirm.row.client_name}?`
          }
          confirmLabel={confirm.kind === 'revoke' ? 'Revoke' : confirm.kind === 'restore' ? 'Re-activate' : 'Rotate'}
          danger={confirm.kind !== 'restore'}
          onClose={() => setConfirm(null)}
          onConfirm={doConfirm}
        >
          {confirm.kind === 'secret' && (
            <>The current secret for <b>{confirm.row.client_id}</b> stops working immediately. Agents using it fail until you give them the new one. Audited.</>
          )}
          {confirm.kind === 'key' && (
            <>Any existing API key for <b>{confirm.row.client_id}</b> stops working immediately. The new key is shown once. Audited.</>
          )}
          {confirm.kind === 'revoke' && (
            <>
              <b>{confirm.row.client_id}</b> can no longer sign in or obtain tokens. {REVOCATION_TIMING} Its memories stay; it simply loses access.
              {role !== 'user' ? ' You can re-activate it later.' : ' Only a platform admin can re-activate it.'} Audited.
            </>
          )}
          {confirm.kind === 'restore' && <>The client can obtain tokens again with its existing secret.</>}
        </ConfirmModal>
      )}
    </>
  );
};

const RevealCard: React.FC<{ revealed: Revealed; onDismiss: () => void }> = ({ revealed, onDismiss }) => {
  const toast = useToast();
  const { tenant } = useApp();
  const [show, setShow] = useState(false);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  useEffect(() => {
    api.publicConfig().then(setConfig).catch(() => undefined);
  }, []);
  const mask = (v: string) => `${v.slice(0, 4)}${'•'.repeat(22)}${v.slice(-4)}`;
  const copy = async (v: string, what: string) => toast((await copyText(v)) ? `${what} copied.` : 'Copy failed — select the text instead.');
  const mcpUrl = config?.mcp_url ?? 'https://memory-hub-mcp.apps.<cluster>/mcp/';
  return (
    <div className="card" style={{ borderColor: '#afdc8f' }}>
      <div className="ch">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span style={{ width: 28, height: 28, borderRadius: 99, background: '#3d7317', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 700 }}>✓</span>
          <h2 data-h="3">{revealed.title}</h2>
        </div>
        <button type="button" className="btn bl" aria-label="Dismiss" onClick={onDismiss}>
          ✕
        </button>
      </div>
      <p className="sm" style={{ margin: '0 0 12px' }}>
        Copy the secret now. It is shown <b>once</b> and stored only as a hash.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <div className="sm" style={{ fontWeight: 600, marginBottom: 4 }}>
            client_id
          </div>
          <div className="secret">
            <span style={{ flex: 1 }}>{revealed.clientId}</span>
            <button type="button" className="btn bl sm" style={{ padding: '2px 6px' }} onClick={() => copy(revealed.clientId, 'client_id')}>
              Copy
            </button>
          </div>
        </div>
        {revealed.secret && (
          <div>
            <div className="sm" style={{ fontWeight: 600, marginBottom: 4 }}>
              client_secret
            </div>
            <div className="secret">
              <span style={{ flex: 1 }}>{show ? revealed.secret : mask(revealed.secret)}</span>
              <button type="button" className="btn bl sm" style={{ padding: '2px 6px' }} onClick={() => setShow((s) => !s)}>
                {show ? 'Hide' : 'Show'}
              </button>
              <button type="button" className="btn bl sm" style={{ padding: '2px 6px' }} onClick={() => copy(revealed.secret!, 'Secret')}>
                Copy
              </button>
            </div>
          </div>
        )}
        {revealed.apiKey && (
          <div>
            <div className="sm" style={{ fontWeight: 600, marginBottom: 4 }}>
              API key
            </div>
            <div className="secret">
              <span style={{ flex: 1 }}>{show ? revealed.apiKey : mask(revealed.apiKey)}</span>
              <button type="button" className="btn bl sm" style={{ padding: '2px 6px' }} onClick={() => setShow((s) => !s)}>
                {show ? 'Hide' : 'Show'}
              </button>
              <button type="button" className="btn bl sm" style={{ padding: '2px 6px' }} onClick={() => copy(revealed.apiKey!, 'API key')}>
                Copy
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="sm" style={{ fontWeight: 600, margin: '16px 0 6px' }}>
        Connect from Claude Code
      </div>
      <pre className="dark">{`claude mcp add memoryhub --transport http -s user \\\n  ${mcpUrl}`}</pre>
      <div className="sm" style={{ fontWeight: 600, margin: '14px 0 6px' }}>
        Or from the Python SDK
      </div>
      <pre className="dark">{`export MEMORYHUB_CLIENT_ID=${revealed.clientId}\nexport MEMORYHUB_CLIENT_SECRET=…\nclient = MemoryHubClient.from_env()`}</pre>
      {config && (
        <button
          type="button"
          className="btn bl sm"
          style={{ marginTop: 10 }}
          onClick={() =>
            copy(
              renderWelcomeEmail({
                clientId: revealed.clientId,
                clientName: revealed.clientName,
                clientSecret: revealed.secret,
                apiKey: revealed.apiKey,
                tenantId: tenant,
                scopes: revealed.scopes,
                mcpUrl: config.mcp_url,
                authUrl: config.auth_url,
              }),
              'Welcome email',
            )
          }
        >
          Copy welcome email
        </button>
      )}
    </div>
  );
};

/** POST /api/clients: users create user agents, admins create service clients. */
export const CreateClientModal: React.FC<{ onClose: () => void; onCreated: (r: Revealed) => void }> = ({ onClose, onCreated }) => {
  const toast = useToast();
  const { tenant, me } = useApp();
  const options = useScopeOptions();
  const type = me!.capabilities.clients.identity_types[0];
  const [clientId, setClientId] = useState('');
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<string[]>(me!.capabilities.clients.default_scopes);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<Revealed | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const res = await api.createClient({ client_id: clientId.trim(), client_name: name.trim() || clientId.trim(), identity_type: type, tenant_id: tenant, default_scopes: scopes });
      const r: Revealed = {
        title: `Client created · ${res.client_id}`,
        clientId: res.client_id,
        clientName: res.client_name,
        secret: res.client_secret,
        apiKey: res.api_key,
        scopes: res.default_scopes,
      };
      onCreated(r);
      setCreated(r);
      toast('Credentials created — copy them now.');
    } catch (e2) {
      setErr(errorMessage(e2));
    } finally {
      setBusy(false);
    }
  };
  if (created) {
    return (
      <Modal title="Copy these credentials now" onClose={onClose} wide>
        <RevealCard revealed={created} onDismiss={onClose} />
      </Modal>
    );
  }
  return (
    <Modal title={type === 'service' ? 'Create service client' : 'Create OAuth client'} onClose={onClose}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <p className="sm muted" style={{ margin: 0 }}>
          {type === 'service'
            ? 'A service identity of its own, owned by you, that reads only the scopes you moderate.'
            : 'An agent that acts for you, with no more access than you have.'}{' '}
          Its secret and API key are shown once.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="f">
            <label htmlFor="cid">client_id</label>
            <input id="cid" className="in mono" required pattern="[A-Za-z0-9][A-Za-z0-9._:\-]*" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="jenkins-release-bot" />
          </div>
          <div className="f">
            <label htmlFor="cname">Display name</label>
            <input id="cname" className="in" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        </div>
        <div className="f">
          <label>Default scopes</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {options.map((s) => (
              <label key={s} className="tg" style={{ background: scopes.includes(s) ? '#e7f1fa' : '#fff' }}>
                <input type="checkbox" checked={scopes.includes(s)} onChange={() => setScopes(scopes.includes(s) ? scopes.filter((x) => x !== s) : [...scopes, s])} />
                <span className="mono" style={{ fontSize: 12 }}>
                  {s}
                </span>
              </label>
            ))}
          </div>
        </div>
        {err && <div className="alert err-a">{err}</div>}
        <div className="modal-actions">
          <button type="submit" className="btn bp" disabled={busy || !clientId.trim() || scopes.length === 0 || !me?.capabilities.clients.can_create}>
            {busy ? 'Creating…' : 'Create'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
};

/** PATCH /api/clients/{id}: rename; scopes can only shrink (users) or stay within what you moderate (admins). */
const EditClientModal: React.FC<{ row: ClientResponse; onClose: () => void; onSaved: () => void }> = ({ row, onClose, onSaved }) => {
  const toast = useToast();
  const { role } = useApp();
  const options = useScopeOptions();
  // Users may only remove scopes; nobody may add a scope outside the allowed list.
  const managedScopes = row.default_scopes.some((s) => !options.includes(s));
  const [name, setName] = useState(row.client_name);
  const [scopes, setScopes] = useState<string[]>(row.default_scopes);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Modal
      title={`Edit ${row.client_id}`}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            onClick={async () => {
              try {
                await api.updateClient(row.client_id, { client_name: name, ...(managedScopes ? {} : { default_scopes: scopes }) });
                toast('Client updated. New tokens use the new scopes.');
                onSaved();
                onClose();
              } catch (e) {
                setErr(errorMessage(e));
              }
            }}
          >
            Save
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="en">Display name</label>
        <input id="en" className="in" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="f">
        <label>Default scopes</label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {(role === 'user' ? row.default_scopes : [...new Set([...options, ...row.default_scopes])]).map((s) => (
            <label key={s} className="tg" style={{ background: scopes.includes(s) ? '#e7f1fa' : '#fff' }}>
              <input type="checkbox" disabled={managedScopes} checked={scopes.includes(s)} onChange={() => setScopes(scopes.includes(s) ? scopes.filter((x) => x !== s) : [...scopes, s])} />
              <span className="mono" style={{ fontSize: 12 }}>
                {s}
              </span>
            </label>
          ))}
        </div>
      </div>
      {managedScopes && <p className="hint">Some of these scopes are outside what you may assign. You can change the display name.</p>}
      {role === 'user' && <p className="hint">You can remove scopes from your agent, never add them.</p>}
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

export default Clients;
