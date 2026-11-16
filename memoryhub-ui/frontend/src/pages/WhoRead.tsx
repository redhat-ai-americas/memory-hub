import React, { useContext } from 'react';
import { api } from '@/api/client';
import { EmbedContext, PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Icon, SkTable } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { MyReads } from '@/types';
import { fmtInt, fmtMonthDay, fmtTime } from '@/utils/format';
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

const REASON_CLASS: Record<string, string> = { project: 's-project', review: 's-user', incident: 'red', own: 'g' };

const isToday = (iso: string) => new Date(iso).toDateString() === new Date().toDateString();

/** Who read my memories: every agent or person that touched memories you own. */
const WhoRead: React.FC<{ route: HashRoute }> = ({ route }) => {
  const embedded = Boolean(useContext(EmbedContext));
  const days = Number(route.params.get('days') || 30);
  const who = route.params.get('who') === 'all' ? 'all' : 'others';
  const { data, error, loading, reload } = useApi<MyReads>(() => api.myReads(days, who), [days, who]);
  const set = (k: string, v: string | undefined) => {
    const next = new URLSearchParams(route.params);
    if (v) next.set(k, v);
    else next.delete(k);
    navigate(route.path, next, { replace: true });
  };

  const others = (data?.readers ?? []).filter((r) => !r.yours);
  const summary = data?.summary;
  const readsByOthers = summary?.reads_by_others ?? others.reduce((a, r) => a + r.count, 0);
  const incidentGrants = summary?.incident_grants ?? (data?.events ?? []).filter((e) => e.break_glass).length;

  return (
    <>
      {!embedded && (
        <PageHeader
          title="Who read my memories"
          description="Every agent or person that read, found or changed a memory that belongs to you or your agents. Taken from the append-only audit log."
        />
      )}
      <div className="body">
        <div className="filters">
          <label htmlFor="wr-days" className="vh">
            Period
          </label>
          <select id="wr-days" className="in auto" value={String(days)} onChange={(e) => set('days', e.target.value === '30' ? undefined : e.target.value)}>
            <option value="1">Last 24 hours</option>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
          </select>
          <label className="check-pill">
            <input type="checkbox" checked={who === 'all'} onChange={(e) => set('who', e.target.checked ? 'all' : undefined)} />
            Include my agents
          </label>
        </div>

        {error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : loading && !data ? (
          <div className="card">
            <SkTable rows={6} cols={4} />
          </div>
        ) : (
          data && (
            <>
              <div className="grid-kpi">
                <Kpi label={`Reads by others · ${days === 1 ? '24 h' : `${days} d`}`} value={readsByOthers} sub="project members on project memories" />
                <Kpi label="Reads of personal memory by others" value={summary?.personal_by_others} sub="reviewers of your open requests" />
                <Kpi label="Admin reads without workflow" value={summary?.admin_without_workflow ?? 0} sub="never possible without incident" />
                <Kpi label="Incident grants on my data" value={incidentGrants} sub="you are notified if one starts" />
              </div>

              <div className="row-wrap">
                <div className="col-main">
                  <section className="card">
                    <div className="ch">
                      <h2 data-h="3">Readers</h2>
                      <span className="sm muted">{fmtInt(data.total)} events</span>
                    </div>
                    {(data.readers ?? []).length === 0 ? (
                      <Empty compact title={who === 'others' ? 'Nobody else touched your memories' : 'No activity on your memories'}>
                        {who === 'others'
                          ? `In this period only you and your agents (${data.identities.join(', ')}) used your memories.`
                          : 'No audit events on your memories in this period.'}
                      </Empty>
                    ) : (
                      <div className="scroll">
                        <table className="tbl mid" style={{ minWidth: 560 }}>
                          <thead>
                            <tr>
                              <th>Reader</th>
                              <th>On behalf of</th>
                              <th>Memories</th>
                              <th>Reads</th>
                              <th>Why allowed</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(data.readers ?? []).map((r) => (
                              <tr key={r.actor_id}>
                                <td>
                                  {r.actor_id}
                                  {r.yours && <span className="hint"> · your agent</span>}
                                  {r.denied > 0 && (
                                    <span className="lbl red" style={{ marginLeft: 6 }}>
                                      {r.denied} denied
                                    </span>
                                  )}
                                </td>
                                <td className="sm">{r.driver_id && r.driver_id !== r.actor_id ? r.driver_id : '—'}</td>
                                <td>{r.memories !== undefined ? fmtInt(r.memories) : '—'}</td>
                                <td>{fmtInt(r.count)}</td>
                                <td>
                                  {r.reason ? (
                                    <span className={`lbl ${REASON_CLASS[r.reason_kind ?? 'project'] ?? 'g'}`}>{r.reason}</span>
                                  ) : (
                                    <span className="sm muted">{r.kinds.map(op).join(', ')}</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                  <section className="card">
                    <h2 data-h="3" style={{ marginBottom: 6 }}>Recent events</h2>
                    {(data.events ?? []).length === 0 && <p className="sm muted">No events in this period.</p>}
                    {(data.events ?? []).map((e) => (
                      <div key={String(e.id)} className="evrow">
                        <span className="mono muted" style={{ width: 56, flex: 'none' }}>
                          {isToday(e.timestamp) ? fmtTime(e.timestamp) : fmtMonthDay(e.timestamp)}
                        </span>
                        <span style={{ minWidth: 0, flex: 1 }}>
                          {e.actor_id} {op(e.event_type)} <a href={memoryHref(e.memory_id)}>{e.memory_stub}</a>
                          {e.break_glass && (
                            <span className="lbl red" style={{ marginLeft: 6 }}>
                              break-glass
                            </span>
                          )}
                          {e.decision === 'denied' && (
                            <span className="lbl red" style={{ marginLeft: 6 }}>
                              denied
                            </span>
                          )}
                        </span>
                      </div>
                    ))}
                  </section>
                </div>
                <aside className="col-side">
                  <section className="card">
                    <h2 data-h="3">Most used memories</h2>
                    <div style={{ display: 'flex', flexDirection: 'column', marginTop: 8 }}>
                      {(data.top_memories ?? []).length === 0 && <p className="sm muted">Nothing read in this period.</p>}
                      {(data.top_memories ?? []).map((m) => (
                        <div key={m.id} className="evrow">
                          <span className="sm muted" style={{ width: 28, flex: 'none' }}>
                            {m.count}
                          </span>
                          <a className="sm ellipsis" href={memoryHref(m.id)} style={{ minWidth: 0 }}>
                            {m.stub}
                          </a>
                        </div>
                      ))}
                    </div>
                  </section>
                  <section className="card">
                    <h2 data-h="3">Whose activity counts as yours</h2>
                    <p className="sm" style={{ margin: '10px 0 0' }}>
                      You, and agents registered to you: {data.identities?.length ? data.identities.join(', ') : 'none yet'}. Toggle “Include my agents” to see their reads too.
                    </p>
                    <a className="btn bl sm" href={buildHash('/identities')} style={{ marginTop: 6, paddingLeft: 0 }}>
                      Manage my agents
                    </a>
                  </section>
                  <div className="alert ok-a">
                    <Icon.Shield stroke="#3d7317" style={{ flex: 'none', marginTop: 1 }} />
                    <div className="sm">Any incident read of your memory appears here with its incident number.</div>
                  </div>
                </aside>
              </div>
            </>
          )
        )}
      </div>
    </>
  );
};

const Kpi: React.FC<{ label: string; value: number | null | undefined; sub: string }> = ({ label, value, sub }) => (
  <div className="card">
    <div className="sm">{label}</div>
    <div className="kpi">{value === null || value === undefined ? '—' : fmtInt(value)}</div>
    <div className="sm muted">{sub}</div>
  </div>
);

export default WhoRead;
