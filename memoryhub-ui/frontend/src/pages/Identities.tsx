import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, SkTable } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, type HashRoute } from '@/hooks/useHashRoute';
import type { ClientResponse, UserRow } from '@/types';
import { avatarColor, fmtInt, fmtRelative, initials } from '@/utils/format';
import { CreateClientModal } from './Clients';

const TYPE_LABEL: Record<string, { label: string; cls: string }> = {
  user: { label: 'user agent', cls: 'g' },
  service: { label: 'service', cls: 'blue' },
  unknown: { label: 'memory owner', cls: 'g' },
};

interface Row extends UserRow {
  client: ClientResponse | null;
}

/**
 * Agents & identities (GET /api/users): every OAuth client of the tenant merged
 * with the memory owners the database knows, with their memory counts. Users
 * see only their own agents. Credentials are managed under OAuth clients.
 */
const Identities: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { role } = useApp();
  const isUser = role === 'user';
  const { data, error, loading, reload } = useApi(async () => {
    const [users, clients] = await Promise.all([api.users(), api.clients().catch(() => [] as ClientResponse[])]);
    const byId = new Map(clients.map((c) => [c.client_id, c]));
    return users.map((u) => ({ ...u, client: byId.get(u.owner_id) ?? null }));
  }, []);
  const [kind, setKind] = useState<'' | 'user' | 'service' | 'unknown'>('');
  const [q, setQ] = useState('');
  const [creating, setCreating] = useState(false);
  const all: Row[] = data ?? [];
  const rows = all
    .filter((r) => !kind || r.identity_type === kind)
    .filter((r) => !q || `${r.name} ${r.owner_id}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b.last_active ?? '').localeCompare(a.last_active ?? ''));
  const focus = route.params.get('id');

  const table = (
    <section className="card" style={{ padding: '6px 12px' }}>
      {error && !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : loading && !data ? (
        <SkTable rows={7} cols={5} />
      ) : rows.length === 0 ? (
        <Empty
          title={q || kind ? 'No identities match' : isUser ? 'No agents yet' : 'No identities yet'}
          action={
            !(q || kind) && (
              <button type="button" className="btn bp" onClick={() => setCreating(true)}>
                {isUser ? 'Register an agent' : 'Create a service client'}
              </button>
            )
          }
        >
          {q || kind ? 'Clear a filter to see more.' : 'Identities appear when an OAuth client is created or an agent writes its first memory.'}
        </Empty>
      ) : (
        <div className="scroll">
          <table className="tbl" style={{ minWidth: 720 }}>
            <thead>
              <tr>
                <th>Identity</th>
                <th>Type</th>
                <th>Memories</th>
                <th>Last write</th>
                <th>Status</th>
                <th>
                  <span className="vh">Credentials</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.owner_id} className={focus === i.owner_id ? 'is-sel' : ''}>
                  <td>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                      <span className="idav" style={{ background: avatarColor(i.owner_id) }}>
                        {initials(i.name)}
                      </span>
                      <div>
                        <div style={{ fontWeight: 600 }}>{i.name}</div>
                        <div className="mono muted">{i.owner_id}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className={`lbl ${TYPE_LABEL[i.identity_type]?.cls ?? 'g'}`}>{TYPE_LABEL[i.identity_type]?.label ?? i.identity_type}</span>
                  </td>
                  <td>
                    <a href={buildHash('/memories', { actor: i.owner_id })}>{fmtInt(i.memory_count)}</a>
                  </td>
                  <td className="sm muted">{i.last_active ? fmtRelative(i.last_active) : '—'}</td>
                  <td className="sm">
                    {!i.client ? <span className="muted">no OAuth client</span> : i.client.active ? <span className="ok">● Active</span> : <span className="err">Revoked</span>}
                  </td>
                  <td>
                    {i.client && (
                      <a className="link-btn" href={isUser ? buildHash('/identities', { view: 'keys', client: i.owner_id }) : buildHash('/clients', { client: i.owner_id })}>
                        Credentials
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );

  const filters = (
    <div className="filters">
      <div className="seg" role="group" aria-label="Identity type">
        {(
          [
            ['', 'All'],
            ['user', 'User agents'],
            ['service', 'Service'],
            ['unknown', 'Memory owners'],
          ] as const
        )
          .filter(([v]) => !isUser || v !== 'service')
          .map(([v, label]) => (
            <button key={v || 'all'} type="button" className={kind === v ? 'on' : ''} aria-pressed={kind === v} onClick={() => setKind(v)}>
              {label}
            </button>
          ))}
      </div>
      <span className="in-icon">
        <Icon.Search size={15} />
        <label htmlFor="id-q" className="vh">
          Search identities
        </label>
        <input id="id-q" className="in" placeholder="Search name or ID" value={q} onChange={(e) => setQ(e.target.value)} />
      </span>
    </div>
  );

  const body = (
    <>
      {filters}
      {table}
      <div className="alert" role="note">
        <Icon.Info size={16} />
        <span className="sm">
          {isUser
            ? 'Your agents act with your permissions: they read what you can read and write where you can write.'
            : 'Seeing an agent here never opens its owner’s memory. Revoke and re-activate clients under OAuth clients & keys.'}
        </span>
      </div>
    </>
  );

  const modal = creating && <CreateClientModal onClose={() => setCreating(false)} onCreated={() => reload()} />;

  return (
    <>
      <PageHeader
        title={isUser ? 'My agents' : 'Agents & identities'}
        crumbs={[{ label: 'Agents & identities' }]}
        description={
          isUser
            ? 'You and the agents that act for you, with the memories each has written.'
            : 'Every identity that has an OAuth client or owns memories in this tenant: people, user agents and service identities, with what they have written.'
        }
        actions={
          <button type="button" className="btn bp" onClick={() => setCreating(true)}>
            <Icon.Plus /> {isUser ? 'Register an agent' : 'New service client'}
          </button>
        }
      />
      <div className="body">{body}</div>
      {modal}
    </>
  );
};

export default Identities;
