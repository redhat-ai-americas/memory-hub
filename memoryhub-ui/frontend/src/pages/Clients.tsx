import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { renderWelcomeEmail } from '@/components/welcomeEmail';
import { copyText, Empty, ErrorState, Icon, Modal, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CredentialRow, PublicConfig, SettingsResponse } from '@/types';
import { errorMessage, fmtRelative } from '@/utils/format';
import { ConfirmModal } from './common';

const SCOPE_OPTIONS = [
  'memory:read',
  'memory:read:user',
  'memory:read:project',
  'memory:read:organizational',
  'memory:write',
  'memory:write:user',
  'memory:write:project',
  'memory:write:organizational',
  'memory:write:role',
  'memory:approve:enterprise',
  'memory:admin',
];

const USER_SCOPE_OPTIONS = [
  'memory:read', 'memory:read:user', 'memory:read:project', 'memory:read:campaign',
  'memory:read:role', 'memory:read:organizational', 'memory:read:enterprise',
  'memory:write:user', 'memory:write:project', 'memory:write:campaign',
];

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

const STATUS: Record<CredentialRow['status'], { cls: string; label: string }> = {
  new: { cls: 'grn', label: 'New' },
  active: { cls: 'grn', label: 'Active' },
  stale: { cls: 'ylw', label: 'Stale' },
  revoked: { cls: 'red', label: 'Revoked' },
};

const Clients: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { role } = useApp();
  const tab = route.params.get('tab') || 'clients';
  const focusClient = route.params.get('client');
  const { data, error, loading, reload } = useApi(() => api.credentials(), []);
  const [revealed, setRevealed] = useState<Revealed | null>(null);
  const [modal, setModal] = useState<null | 'client' | 'key'>(null);
  const [editing, setEditing] = useState<CredentialRow | null>(null);
  const [confirm, setConfirm] = useState<null | { kind: 'secret' | 'key' | 'revoke' | 'restore'; row: CredentialRow }>(null);

  // Keeps the hub view (My agents & API keys › …) when embedded.
  const setTab = (t: string) => {
    const next = new URLSearchParams(route.params);
    if (t === 'clients') next.delete('tab');
    else next.set('tab', t);
    navigate(route.path, next, { replace: true });
  };
  // QA 2026-11-10 BR-PA2-04: show the confirmed revoke/re-activate at once,
  // without waiting for (or trusting a stale) list refresh.
  const [applied, setApplied] = useState<Record<string, boolean>>({});
  useEffect(() => setApplied({}), [data]);
  const withApplied = (list: CredentialRow[]) =>
    list.map((c) =>
      c.client_id in applied
        ? { ...c, active: applied[c.client_id], status: applied[c.client_id] ? ('active' as const) : ('revoked' as const) }
        : c,
    );
  const rows = withApplied(tab === 'keys' ? data?.api_keys ?? [] : data?.clients ?? []);
  const [q, setQ] = useState('');
  const [statusF, setStatusF] = useState('');
  const [ownerF, setOwnerF] = useState('');
  const shown = rows.filter((c) => {
    if (ownerF && c.identity_type !== ownerF) return false;
    if (statusF === 'suspended' && !c.suspended_incident) return false;
    if (statusF === 'active' && !(c.active && c.status !== 'stale' && !c.suspended_incident)) return false;
    if (statusF === 'stale' && c.status !== 'stale') return false;
    if (statusF === 'revoked' && c.active) return false;
    if (q && !`${c.client_name} ${c.client_id} ${c.owner ?? ''}`.toLowerCase().includes(q.toLowerCase())) return false;
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
            ? 'Credentials your agents use to reach the MCP server and SDK. A secret is shown once when it is issued; nobody can view it later.'
            : 'The tenant’s client registry: OAuth clients, API keys and trusted token issuers. A secret is shown once when it is issued; nobody can view it later, including you.'
        }
        actions={
          <>
            <button type="button" className="btn bs" disabled={data ? !data.auth_available : true} onClick={() => setModal('key')}>
              New API key
            </button>
            <button type="button" className="btn bp" disabled={data ? !data.auth_available : true} onClick={() => setModal('client')}>
              <Icon.Plus /> New OAuth client
            </button>
          </>
        }
        tabs={
          <Tabs
            label="Credential type"
            value={tab}
            onChange={setTab}
            tabs={[
              { value: 'clients', label: 'OAuth clients', count: data ? data.clients.length : null },
              { value: 'keys', label: 'API keys', count: data ? data.api_keys.length : null },
              { value: 'issuers', label: 'Trusted issuers', count: data ? data.issuers.length : null },
            ]}
          />
        }
      />
      <div className="body">
        {revealed && <RevealCard revealed={revealed} onDismiss={() => setRevealed(null)} />}
        {tab !== 'issuers' && data?.auth_available && (
          <div className="filters">
            <span className="in-icon">
              <Icon.Search size={15} />
              <label htmlFor="cl-q" className="vh">
                Search clients
              </label>
              <input id="cl-q" className="in" placeholder={tab === 'keys' ? 'Search keys' : 'Search clients'} value={q} onChange={(e) => setQ(e.target.value)} />
            </span>
            <label htmlFor="cl-s" className="vh">
              Status
            </label>
            <select id="cl-s" className="in auto" value={statusF} onChange={(e) => setStatusF(e.target.value)}>
              <option value="">Status: any</option>
              <option value="active">Status: Active</option>
              <option value="suspended">Status: Suspended</option>
              <option value="stale">Status: Stale &gt; 30 d</option>
              <option value="revoked">Status: Revoked</option>
            </select>
            {role !== 'user' && (
              <>
                <label htmlFor="cl-o" className="vh">
                  Owner type
                </label>
                <select id="cl-o" className="in auto" value={ownerF} onChange={(e) => setOwnerF(e.target.value)}>
                  <option value="">Owner type: any</option>
                  <option value="service">Owner type: service identity</option>
                  <option value="user">Owner type: person</option>
                </select>
              </>
            )}
          </div>
        )}
        <section className="card" style={{ padding: tab === 'issuers' ? undefined : '6px 12px' }}>
          {error && !data ? (
            <ErrorState error={error} onRetry={reload} />
          ) : loading && !data ? (
            <SkTable rows={7} cols={6} />
          ) : !data!.auth_available ? (
            <Empty title="Auth service unavailable" action={<button type="button" className="btn bs" onClick={reload}>Try again</button>}>
              The dashboard could not reach the MemoryHub auth service (MEMORYHUB_AUTH_SERVICE_URL), so clients and keys cannot be listed or issued.
            </Empty>
          ) : tab === 'issuers' ? (
            <IssuerList issuers={data!.issuers} issuer={data!.issuer} />
          ) : shown.length === 0 ? (
            <Empty
              compact
              title={rows.length ? 'Nothing matches' : tab === 'keys' ? 'No API keys yet' : 'No OAuth clients yet'}
              action={
                !rows.length && (
                  <button type="button" className="btn bp" onClick={() => setModal(tab === 'keys' ? 'key' : 'client')}>
                    {tab === 'keys' ? 'New API key' : 'New OAuth client'}
                  </button>
                )
              }
            >
              {rows.length ? 'Clear a filter to see more.' : 'Create a client for each agent or service that should read or write memory.'}
            </Empty>
          ) : (
            <div className="scroll">
              <table className="tbl mid" style={{ minWidth: 820 }}>
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Owner</th>
                    <th>Grant type</th>
                    <th>Scopes allowed</th>
                    <th>Last used</th>
                    <th>Status</th>
                    <th>
                      <span className="vh">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((c) => {
                    const st = statusOf(c);
                    return (
                      <tr key={c.client_id} className={c.status === 'new' ? 'new' : c.client_id === focusClient ? 'is-sel' : ''}>
                        <td>
                          <b>{c.client_name}</b>
                          <div className="mono sm muted">{c.client_id.length > 10 ? `${c.client_id.slice(0, 7)}…` : c.client_id}</div>
                        </td>
                        <td>{c.identity_type === 'service' ? 'service identity' : c.owner ?? 'person'}</td>
                        <td className="sm">{tab === 'keys' ? 'API key' : c.grant === 'authorization_code' ? 'authorization_code + PKCE' : c.grant}</td>
                        <td className="sm" style={{ maxWidth: 240 }}>
                          {c.identity_type === 'user' && c.default_scopes.length === 0
                            ? 'owner’s scopes ∩ agent permissions'
                            : c.default_scopes.map((x) => x.replace(/^memory:/, '').replace(/^project:/, 'project: ')).join(' · ') || '—'}
                        </td>
                        <td className="sm" style={{ whiteSpace: 'nowrap' }}>
                          {lastUsed(c.last_used)}
                        </td>
                        <td>
                          <span className={`lbl ${st.cls}`}>{st.label}</span>
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <span className="row-links stack-links">
                            {c.suspended_incident ? (
                              <a className="link-btn" href={buildHash('/audit', { tab: 'grants' })}>
                                Details
                              </a>
                            ) : !c.active ? (
                              role !== 'user' ? (
                                <button type="button" className="link-btn" onClick={() => setConfirm({ kind: 'restore', row: c })}>
                                  Re-issue
                                </button>
                              ) : (
                                <span className="sm muted">Ask an admin</span>
                              )
                            ) : (
                              <>
                                {!c.public && c.identity_type === 'service' && c.status !== 'stale' && (
                                  <button type="button" className="link-btn" onClick={() => setConfirm({ kind: tab === 'keys' ? 'key' : 'secret', row: c })}>
                                    {tab === 'keys' ? 'Rotate key' : 'Rotate secret'}
                                  </button>
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
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {data?.auth_available && tab !== 'issuers' && (
          <div className="acc-cards two">
            <section className="card">
              <div className="card-head">
                <h2 data-h="3">Trusted token issuers</h2>
                <button
                  type="button"
                  className="btn bs sm-btn"
                  onClick={() => setTab('issuers')}
                  title="Issuers are configured on the auth service (MEMORYHUB_TRUSTED_ISSUERS)"
                >
                  {role === 'user' ? 'View all' : 'Add issuer'}
                </button>
              </div>
              {data.issuers.length === 0 ? (
                <p className="sm muted" style={{ marginTop: 10 }}>
                  No trusted issuers. Token exchange is disabled in the auth service.
                </p>
              ) : (
                <ul className="issuer-list">
                  {data.issuers.map((i) => (
                    <li key={i.name}>
                      <span className="mono">{i.name}</span>
                      <span className={`lbl ${i.status === 'verified' || i.status === 'active' ? 'grn' : 'ylw'}`}>
                        {i.status === 'verified' || i.status === 'active' ? 'Verified · JWKS' : i.status ?? 'Draft'}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            {role !== 'user' && <ClientPolicy />}
          </div>
        )}
        {role !== 'user' && (
          <div className="alert" role="note">
            <Icon.Info size={16} />
            <span className="sm">
              Users manage their own agents’ keys in My agents. Here you can suspend or revoke any client in the tenant, but a client never grants more than its owner can read.
            </span>
          </div>
        )}
      </div>

      {(modal === 'client' || modal === 'key') && (
        <CreateClientModal
          apiKeyFirst={modal === 'key'}
          onClose={() => setModal(null)}
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
              <b>{confirm.row.client_id}</b> can no longer sign in or obtain tokens. {REVOCATION_TIMING} Its memories stay; it simply loses access. You
              can re-activate it later. Audited.
            </>
          )}
          {confirm.kind === 'restore' && <>The client can obtain tokens again with its existing secret.</>}
        </ConfirmModal>
      )}
    </>
  );
};

const statusOf = (c: CredentialRow) =>
  c.suspended_incident
    ? { cls: 'ylw', label: `Suspended · ${c.suspended_incident}` }
    : !c.active
      ? { cls: 'g', label: 'Revoked' }
      : c.status === 'stale'
        ? { cls: 'ylw', label: 'Stale > 30 d' }
        : STATUS[c.status];
const lastUsed = (iso: string | null) => {
  if (!iso) return 'Never';
  const d = new Date(iso);
  if (Date.now() - d.getTime() < 3600000) return fmtRelative(iso);
  if (d.toDateString() === new Date().toDateString()) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

/** Tenant client policy, within the limits set in Global policies. */
const ClientPolicy: React.FC = () => {
  const { data } = useApi<SettingsResponse>(() => api.settings(), []);
  const qv = data?.values.quotas;
  return (
    <section className="card">
      <div className="card-head">
        <h2 data-h="3">Client policy</h2>
        <span className="sm muted">within global limits</span>
      </div>
      {!data ? (
        <SkLines lines={3} />
      ) : (
        <dl className="detail-kv nums">
          <dt>Allowed connection methods</dt>
          <dd>{qv?.connection_methods === 'oauth' ? 'OAuth 2.1 only' : 'OAuth 2.1 · API key'}</dd>
          <dt>Key lifetime</dt>
          <dd>
            {qv?.key_lifetime_days ?? 90} days (max {qv?.key_lifetime_max_days ?? 365})
          </dd>
          <dt>Revoke stale after</dt>
          <dd>{qv?.revoke_stale_days ?? 60} days</dd>
        </dl>
      )}
      <a className="sm" href={buildHash('/settings')} style={{ display: 'inline-block', marginTop: 12 }}>
        Change in Tenant settings
      </a>
    </section>
  );
};

const IssuerCards: React.FC<{ issuers: { name: string; kind?: string; description?: string; status?: string }[] }> = ({ issuers }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14 }}>
    {issuers.length === 0 && <span className="sm muted">No trusted issuers. Token exchange is disabled in the auth service.</span>}
    {issuers.map((i) => (
      <div key={i.name} style={{ border: '1px solid #d2d2d2', borderRadius: 12, padding: '12px 14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <b>{i.name}</b>
          <span className={`lbl ${i.status === 'active' ? 'grn' : 'ylw'}`}>{i.status === 'active' ? 'Active' : i.status ? i.status[0].toUpperCase() + i.status.slice(1) : 'Draft'}</span>
        </div>
        <div className="sm muted" style={{ marginTop: 4 }}>
          {i.description ?? i.kind}
        </div>
      </div>
    ))}
  </div>
);

const IssuerList: React.FC<{ issuers: { name: string; kind?: string; description?: string; status?: string }[]; issuer: string | null }> = ({ issuers, issuer }) => (
  <div style={{ padding: '20px 24px' }}>
    <div className="ch">
      <h2 data-h="3">Trusted token issuers</h2>
      {issuer && <span className="mono muted">MemoryHub issuer: {issuer}</span>}
    </div>
    <IssuerCards issuers={issuers} />
  </div>
);

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

export const CreateClientModal: React.FC<{
  defaultType?: 'user' | 'service';
  apiKeyFirst?: boolean;
  onClose: () => void;
  onCreated: (r: Revealed) => void;
}> = ({ defaultType = 'user', apiKeyFirst, onClose, onCreated }) => {
  const toast = useToast();
  const { tenant, role } = useApp();
  const userOnly = role === 'user';
  const [clientId, setClientId] = useState('');
  const [name, setName] = useState('');
  const [type, setType] = useState<'user' | 'service'>(defaultType);
  const [scopes, setScopes] = useState<string[]>(['memory:read', 'memory:write:user']);
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
        title: `${apiKeyFirst ? 'API key issued' : 'Client created'} · ${res.client_id}`,
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
    <Modal title={apiKeyFirst ? 'Issue API key' : type === 'service' ? 'Add service agent' : 'Create OAuth client'} onClose={onClose}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {apiKeyFirst && (
          <p className="sm muted" style={{ margin: 0 }}>
            API keys belong to a client. This creates a client and shows its API key and secret once.
          </p>
        )}
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
          <label htmlFor="ctype">Identity type</label>
          <select id="ctype" className="in" value={type} onChange={(e) => setType(e.target.value as 'user' | 'service')}>
            <option value="user">user — acts for a person</option>
            {!userOnly && <option value="service">service — its own narrowly scoped identity</option>}
          </select>
        </div>
        <div className="f">
          <label>Default scopes</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {(userOnly ? USER_SCOPE_OPTIONS : SCOPE_OPTIONS).map((s) => (
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
          <button type="submit" className="btn bp" disabled={busy || !clientId.trim() || scopes.length === 0}>
            {busy ? 'Creating…' : apiKeyFirst ? 'Issue API key' : 'Create'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
};

const EditClientModal: React.FC<{ row: CredentialRow; onClose: () => void; onSaved: () => void }> = ({ row, onClose, onSaved }) => {
  const toast = useToast();
  const { role } = useApp();
  const managedScopes = role === 'user' && row.default_scopes.some((s) => !USER_SCOPE_OPTIONS.includes(s));
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
          {[...new Set([...(role === 'user' ? USER_SCOPE_OPTIONS : SCOPE_OPTIONS), ...row.default_scopes])].map((s) => (
            <label key={s} className="tg" style={{ background: scopes.includes(s) ? '#e7f1fa' : '#fff' }}>
              <input type="checkbox" disabled={managedScopes} checked={scopes.includes(s)} onChange={() => setScopes(scopes.includes(s) ? scopes.filter((x) => x !== s) : [...scopes, s])} />
              <span className="mono" style={{ fontSize: 12 }}>
                {s}
              </span>
            </label>
          ))}
        </div>
      </div>
      {managedScopes && <p className="hint">These scopes are managed by a platform admin. You can change the display name.</p>}
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

export default Clients;
