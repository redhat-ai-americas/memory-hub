import React from 'react';
import { api } from '@/api/client';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Seg, SkTable } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { MyReads } from '@/types';
import { avatarColor, fmtInt, fmtRelative, initials } from '@/utils/format';
import { memoryHref } from './common';

const OP: Record<string, string> = {
  'memory.read': 'read',
  'memory.search': 'found in search',
  'memory.write': 'wrote',
  'memory.update': 'updated',
  'memory.delete': 'deleted',
  'memory.relationship_created': 'linked',
};
const op = (t: string) => OP[t] ?? t.replace(/^memory\./, '').replace(/_/g, ' ');

/** Who read my memories: every agent or person that touched memories you own. */
const WhoRead: React.FC<{ route: HashRoute }> = ({ route }) => {
  const days = Number(route.params.get('days') || 30);
  const who = route.params.get('who') === 'all' ? 'all' : 'others';
  const { data, error, loading, reload } = useApi<MyReads>(() => api.myReads(days, who), [days, who]);
  const set = (k: string, v: string | undefined) => {
    const next = new URLSearchParams(route.params);
    if (v) next.set(k, v);
    else next.delete(k);
    navigate('/reads', next, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Who read my memories"
        description="Every agent or person that read, found or changed a memory that belongs to you or your agents. Taken from the append-only audit log."
        actions={
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Seg
              label="Who"
              value={who}
              onChange={(v) => set('who', v === 'others' ? undefined : v)}
              options={[
                { value: 'others', label: 'Others' },
                { value: 'all', label: 'Including my agents' },
              ]}
            />
            <Seg
              label="Period"
              value={String(days)}
              onChange={(v) => set('days', v === '30' ? undefined : v)}
              options={[
                { value: '1', label: '24 h' },
                { value: '7', label: '7 d' },
                { value: '30', label: '30 d' },
                { value: '90', label: '90 d' },
              ]}
            />
          </div>
        }
      />
      <div className="body">
        {error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : loading && !data ? (
          <div className="card">
            <SkTable rows={6} cols={4} />
          </div>
        ) : data && data.total === 0 ? (
          <div className="card">
            <Empty title={who === 'others' ? 'Nobody else touched your memories' : 'No activity on your memories'}>
              {who === 'others'
                ? `In the last ${days} days only you and your agents (${data.identities.join(', ')}) used your memories.`
                : `No audit events on your memories in the last ${days} days.`}
            </Empty>
          </div>
        ) : (
          data && (
            <div className="row-wrap">
              <div className="col-main">
                <section className="card" style={{ padding: 0 }}>
                  <div className="ch" style={{ padding: '18px 20px 0' }}>
                    <h3>Readers</h3>
                    <span className="sm muted">{fmtInt(data.total)} events</span>
                  </div>
                  <div className="scroll">
                    <table className="tbl mid">
                      <thead>
                        <tr>
                          <th>Who</th>
                          <th>What</th>
                          <th>Events</th>
                          <th>Last</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.readers.map((r) => (
                          <tr key={r.actor_id}>
                            <td>
                              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                                <span className="mav" style={{ background: avatarColor(r.actor_id) }}>
                                  {initials(r.actor_id)}
                                </span>
                                <div>
                                  <div className="b6">
                                    {r.actor_id}
                                    {r.yours && <span className="sm muted"> · your agent</span>}
                                  </div>
                                  <div className="sm muted">
                                    {r.driver_id && r.driver_id !== r.actor_id ? `for ${r.driver_id}` : 'acting for itself'}
                                    {r.via_dashboard ? ' · via dashboard' : ''}
                                  </div>
                                </div>
                              </div>
                            </td>
                            <td className="sm">{r.kinds.map(op).join(', ')}</td>
                            <td>
                              {fmtInt(r.count)}
                              {r.denied > 0 && <span className="lbl red" style={{ marginLeft: 6 }}>{r.denied} denied</span>}
                            </td>
                            <td className="sm muted">{fmtRelative(r.last)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
                <section className="card" style={{ padding: 0 }}>
                  <div className="ch" style={{ padding: '18px 20px 0' }}>
                    <h3>Recent events</h3>
                    <a className="sm" href={buildHash('/memories', { scope: 'user' })}>
                      My memories
                    </a>
                  </div>
                  <div style={{ padding: '4px 20px 14px' }}>
                    {data.events.map((e) => (
                      <div key={String(e.id)} className="hrow">
                        <span style={{ minWidth: 0 }}>
                          <b>{e.actor_id}</b> {op(e.event_type)}{' '}
                          <a href={memoryHref(e.memory_id)} className="ellipsis" style={{ display: 'inline-block', maxWidth: 360, verticalAlign: 'bottom' }}>
                            {e.memory_stub}
                          </a>
                          {e.break_glass && <span className="lbl red" style={{ marginLeft: 6 }}>break-glass</span>}
                          {e.decision === 'denied' && <span className="lbl red" style={{ marginLeft: 6 }}>denied</span>}
                        </span>
                        <span className="sm muted" style={{ whiteSpace: 'nowrap' }}>
                          {fmtRelative(e.timestamp)}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
              <aside className="col-side">
                <section className="card">
                  <h3>Most used memories</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
                    {data.top_memories.map((m) => (
                      <a key={m.id} className="hrow link-plain" href={memoryHref(m.id)} style={{ color: 'inherit' }}>
                        <span className="ellipsis" style={{ minWidth: 0 }}>
                          {m.stub}
                        </span>
                        <b className="sm">{m.count}</b>
                      </a>
                    ))}
                  </div>
                </section>
                <section className="card">
                  <h3>Whose activity counts as yours</h3>
                  <p className="sm muted" style={{ margin: '8px 0 10px' }}>
                    You and the agents linked to you. Others are shown by default.
                  </p>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {data.identities.map((i) => (
                      <span key={i} className="lbl g mono">
                        {i}
                      </span>
                    ))}
                  </div>
                  <a className="btn bl sm" href={buildHash('/identities')} style={{ marginTop: 10 }}>
                    Manage my agents
                  </a>
                </section>
              </aside>
            </div>
          )
        )}
      </div>
    </>
  );
};

export default WhoRead;
