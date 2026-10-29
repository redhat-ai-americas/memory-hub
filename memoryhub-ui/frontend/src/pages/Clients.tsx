import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { renderWelcomeEmail } from '@/components/welcomeEmail';
import { copyText, Dropdown, Empty, ErrorState, Modal, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CredentialRow, PublicConfig } from '@/types';
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

/** Freshly issued credentials, shown once. */
export interface Revealed {
  title: string;
  clientId: string;
  clientName: string;
  secret: string | null;
  apiKey: string | null;
  scopes: string[];
}

const STATUS: Record<CredentialRow['status'], { cls: string; label: string }> = {
  new: { cls: 'grn', label: 'New' },
  active: { cls: 'grn', label: 'Active' },
  stale: { cls: 'ylw', label: 'Stale' },
  revoked: { cls: 'red', label: 'Revoked' },
};

const Clients: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const tab = route.params.get('tab') || 'clients';
  const focusClient = route.params.get('client');
  const { data, error, loading, reload } = useApi(() => api.credentials(), []);
  const [revealed, setRevealed] = useState<Revealed | null>(null);
  const [modal, setModal] = useState<null | 'client' | 'key'>(null);
  const [editing, setEditing] = useState<CredentialRow | null>(null);
  const [confirm, setConfirm] = useState<null | { kind: 'secret' | 'key' | 'revoke' | 'restore'; row: CredentialRow }>(null);

  const setTab = (t: string) => navigate('/clients', t === 'clients' ? undefined : { tab: t }, { replace: true });
  const rows = tab === 'keys' ? data?.api_keys ?? [] : data?.clients ?? [];

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
      toast(kind === 'restore' ? 'Client re-activated.' : 'Client revoked. Existing tokens stop working at expiry.');
    }
    reload();
  };

  return (
    <>
      <PageHeader
        title="OAuth clients & API keys"
        crumbs={[{ label: 'OAuth clients & keys' }]}
        description="Credentials agents use to reach the MCP server and SDK. Start with an API key; move to OAuth 2.1 client credentials or platform token exchange for production fleets."
        actions={
          <>
            <button type="button" className="btn bs" disabled={data ? !data.auth_available : true} onClick={() => setModal('key')}>
              Issue API key
            </button>
            <button type="button" className="btn bp" disabled={data ? !data.auth_available : true} onClick={() => setModal('client')}>
              Create OAuth client
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
        <div className="row-wrap">
          <section className="card" style={{ flex: '999 1 560px', padding: 0, minWidth: 0 }}>
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
            ) : rows.length === 0 ? (
              <Empty
                title={tab === 'keys' ? 'No API keys yet' : 'No OAuth clients yet'}
                action={
                  <button type="button" className="btn bp" onClick={() => setModal(tab === 'keys' ? 'key' : 'client')}>
                    {tab === 'keys' ? 'Issue API key' : 'Create OAuth client'}
                  </button>
                }
              >
                Create a client for each agent or service that should read or write memory.
              </Empty>
            ) : (
              <div className="scroll">
                <table className="tbl" style={{ minWidth: 820 }}>
                  <thead>
                    <tr>
                      <th>Client</th>
                      <th>Bound identity</th>
                      <th>Grant</th>
                      <th>Scopes</th>
                      <th>Last used</th>
                      <th>Status</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <tr key={c.client_id} className={c.status === 'new' ? 'new' : c.client_id === focusClient ? 'is-sel' : ''}>
                        <td>
                          <div style={{ fontWeight: 600 }}>{c.client_name}</div>
                          <div className="mono muted">{c.client_id}</div>
                        </td>
                        <td className="sm">
                          {c.identity_type}
                          {c.status === 'new' ? ' · new' : ''}
                        </td>
                        <td>
                          <span className={`lbl ${tab === 'keys' ? 'g' : c.grant === 'client_credentials' ? 'blue' : 'g'}`}>{tab === 'keys' ? 'API key' : c.grant}</span>
                        </td>
                        <td style={{ maxWidth: 240 }}>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                            {c.default_scopes.map((s) => (
                              <span className="code" key={s}>
                                {s}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="sm muted" style={{ whiteSpace: 'nowrap' }}>
                          {fmtRelative(c.last_used)}
                        </td>
                        <td>
                          <span className={`lbl ${STATUS[c.status].cls}`}>{STATUS[c.status].label}</span>
                        </td>
                        <td>
                          <Dropdown
                            align="right"
                            toggle={(p) => (
                              <button type="button" className="btn bl" aria-label="Client actions" style={{ padding: '4px 8px' }} {...p}>
                                ⋮
                              </button>
                            )}
                          >
                            {(close) => (
                              <>
                                <button type="button" onClick={() => { close(); setEditing(c); }}>
                                  Edit name and scopes
                                </button>
                                {!c.public && (
                                  <button type="button" onClick={() => { close(); setConfirm({ kind: 'secret', row: c }); }}>
                                    Rotate client secret
                                  </button>
                                )}
                                {!c.public && (
                                  <button type="button" onClick={() => { close(); setConfirm({ kind: 'key', row: c }); }}>
                                    Rotate API key
                                  </button>
                                )}
                                <hr />
                                {c.active ? (
                                  <button type="button" className="danger" onClick={() => { close(); setConfirm({ kind: 'revoke', row: c }); }}>
                                    Revoke
                                  </button>
                                ) : (
                                  <button type="button" onClick={() => { close(); setConfirm({ kind: 'restore', row: c }); }}>
                                    Re-activate
                                  </button>
                                )}
                              </>
                            )}
                          </Dropdown>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <aside className="col-side" style={{ flex: '1 1 380px' }}>
            {revealed && <RevealCard revealed={revealed} onDismiss={() => setRevealed(null)} />}
            {tab !== 'issuers' && data && (
              <div className="card">
                <div className="ch">
                  <h3>Trusted token issuers</h3>
                  <button type="button" className="btn bl sm" onClick={() => setTab('issuers')}>
                    View all
                  </button>
                </div>
                <p className="sm muted" style={{ margin: '0 0 12px' }}>
                  Workloads exchange their platform token (RFC 8693) for a scoped MemoryHub JWT — no API keys to manage.
                </p>
                <IssuerCards issuers={data.issuers} />
              </div>
            )}
            {!revealed && tab === 'issuers' && (
              <div className="card">
                <h3 style={{ marginBottom: 8 }}>Adding an issuer</h3>
                <p className="sm muted" style={{ margin: 0, lineHeight: 1.5 }}>
                  The local cluster issuer is enabled in the auth service with token exchange. Additional OIDC issuers are configured on the auth service; list them for
                  operators by setting <span className="mono">MEMORYHUB_TRUSTED_ISSUERS</span> on the dashboard.
                </p>
              </div>
            )}
          </aside>
        </div>
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
              <b>{confirm.row.client_id}</b> can no longer obtain tokens. Its memories stay; it simply loses access. You can re-activate it later. Audited.
            </>
          )}
          {confirm.kind === 'restore' && <>The client can obtain tokens again with its existing secret.</>}
        </ConfirmModal>
      )}
    </>
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
      <h3>Trusted token issuers</h3>
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
          <h3>{revealed.title}</h3>
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
            {SCOPE_OPTIONS.map((s) => (
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
                await api.updateClient(row.client_id, { client_name: name, default_scopes: scopes });
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
          {[...new Set([...SCOPE_OPTIONS, ...row.default_scopes])].map((s) => (
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
    </Modal>
  );
};

export default Clients;
