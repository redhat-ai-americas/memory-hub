import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Pager, ScopeLabel, SelectMenu, SkLines, SkTable, Standby, Tokens, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { AuditEvent, AuditResponse, ForensicsResponse } from '@/types';
import { errorMessage, fmtInt, fmtTime, fmtUtc } from '@/utils/format';
import { decisionOf, EventTarget, memoryHref } from './common';

const RANGES = [
  { value: '1', label: 'Last hour' },
  { value: '24', label: 'Last 24 hours' },
  { value: '168', label: 'Last 7 days' },
  { value: '720', label: 'Last 30 days' },
  { value: '0', label: 'All time' },
];

const localInput = (d: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const Audit: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { role } = useApp();
  const personal = role === 'user';
  const requestedTab = route.params.get('tab') || 'forensics';
  const tab = personal && !['log', 'denied'].includes(requestedTab) ? 'log' : requestedTab;
  const setParam = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(route.params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!('page' in changes)) next.delete('page');
    navigate('/audit', next, { replace: true });
  };
  const { data: denied } = useApi(() => api.audit({ decision: 'denied', hours: undefined, per_page: 1 }), []);

  const exportLog = async () => {
    try {
      const all: AuditEvent[] = [];
      for (let page = 1; page <= 25; page += 1) {
        const res = await api.audit({ hours: undefined, page, per_page: 200 });
        all.push(...res.items);
        if (all.length >= res.total) break;
      }
      const blob = new Blob([all.map((e) => JSON.stringify(e)).join('\n')], { type: 'application/x-ndjson' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `memoryhub-audit-${new Date().toISOString().slice(0, 10)}.jsonl`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast(`Exported ${fmtInt(all.length)} audit events.`);
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };

  return (
    <>
      <PageHeader
        title={personal ? 'My activity' : 'Audit & forensics'}
        description={
          personal
            ? 'Searches, reads and writes made by your connected agents. Other users and their agents are not included.'
            : 'An append-only record of every memory operation, and the ability to reconstruct exactly what an agent knew at any moment.'
        }
        actions={
          !personal && (
            <button type="button" className="btn bg" onClick={exportLog}>
              Export for compliance
            </button>
          )
        }
        tabs={
          <Tabs
            label="Audit views"
            value={tab}
            onChange={(t) => setParam({ tab: t === 'forensics' ? undefined : t, decision: undefined })}
            tabs={
              personal
                ? [
                    { value: 'log', label: 'Activity log' },
                    { value: 'denied', label: 'Denied only', count: denied ? denied.denied_total : null },
                  ]
                : [
                    { value: 'forensics', label: 'Forensics' },
                    { value: 'log', label: 'Audit log' },
                    { value: 'denied', label: 'Denied only', count: denied ? denied.denied_total : null },
                    { value: 'retention', label: 'Retention' },
                  ]
            }
          />
        }
      />
      <div className="body">
        {tab === 'forensics' && !personal && <Forensics route={route} />}
        {tab !== 'retention' && tab !== 'forensics' && <AuditLog route={route} deniedOnly={tab === 'denied'} setParam={setParam} personal={personal} />}
        {tab === 'retention' && !personal && <Retention />}
      </div>
    </>
  );
};

const Forensics: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { standby } = useApp();
  const { data: ids } = useApi(() => api.identities(), []);
  const [agent, setAgent] = useState(route.params.get('actor') || '');
  const [session, setSession] = useState('');
  const [at, setAt] = useState(localInput(new Date()));
  const [windowMin, setWindowMin] = useState('60');
  const [result, setResult] = useState<ForensicsResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!agent.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api.forensics({ actor: agent.trim(), at: new Date(at).toISOString(), session_id: session.trim() || undefined, window_minutes: Number(windowMin) }),
      );
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(false);
    }
  };

  const changed = result?.findings ?? [];
  return (
    <section className="card">
      <div className="ch">
        <h3>What did the agent know?</h3>
        <span className="sm muted">Correlates read entries with version history</span>
      </div>
      <form style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }} onSubmit={run}>
        <div className="f grow">
          <label htmlFor="ag">Agent</label>
          <input id="ag" className="in" list="fx-agents" value={agent} onChange={(e) => setAgent(e.target.value)} placeholder="langgraph-intake" disabled={standby} />
          <datalist id="fx-agents">
            {(ids?.items ?? []).map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
                {i.bound_to ? ` · ${i.bound_to}` : ''}
              </option>
            ))}
          </datalist>
        </div>
        <div className="f grow">
          <label htmlFor="ss">Session</label>
          <input id="ss" className="in mono" value={session} onChange={(e) => setSession(e.target.value)} placeholder="any session" disabled={standby} />
        </div>
        <div className="f grow">
          <label htmlFor="tm">Point in time</label>
          <input id="tm" className="in" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} disabled={standby} />
        </div>
        <div className="f" style={{ flex: '0 1 140px' }}>
          <label htmlFor="wn">Look back</label>
          <select id="wn" className="in" value={windowMin} onChange={(e) => setWindowMin(e.target.value)} disabled={standby}>
            <option value="15">15 min</option>
            <option value="60">1 hour</option>
            <option value="240">4 hours</option>
            <option value="1440">24 hours</option>
          </select>
        </div>
        <button type="submit" className="btn bp" disabled={busy || standby || !agent.trim()}>
          {busy ? 'Reconstructing…' : 'Reconstruct context'}
        </button>
      </form>
      <div style={{ marginTop: 20 }}>
        {standby ? (
          <Standby>Once agents read and search memories, you can rebuild exactly which versions they were served at any moment.</Standby>
        ) : error ? (
          <ErrorState error={error} compact onRetry={() => void run()} />
        ) : busy && !result ? (
          <SkLines lines={5} />
        ) : !result ? (
          <p className="sm muted" style={{ margin: 0 }}>
            Pick an agent and a moment. The dashboard replays that agent’s read and search events from the audit log and shows which version of each memory it
            was given, and whether it has changed since.
          </p>
        ) : result.context.length === 0 ? (
          <Empty compact title="No memories served in that window">
            {result.events
              ? `${result.events} audit events found, but none referenced a memory. Search events record result IDs only when the MCP server includes them.`
              : `No audit events for ${result.actor} in the ${result.window_minutes} minutes before that time.`}
          </Empty>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20 }}>
            <div style={{ flex: '2 1 420px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="sm muted">
                {result.context.length} memories in context · <Tokens n={result.tokens} />
                {result.last_search_at ? ` · served by search at ${fmtTime(result.last_search_at)}` : ''}
              </div>
              {result.context.map((c, i) => (
                <div className="ctxi" key={c.id}>
                  <span className="n">{i + 1}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div>
                      <a href={memoryHref(c.id)} style={{ color: 'inherit', textDecoration: 'none' }}>
                        {c.content}
                      </a>
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                      <ScopeLabel scope={c.scope} />
                      <span className="mono muted">v{c.version_then} at that time</span>
                      {c.changed_after ? (
                        <span className="sm err">now v{c.version_now} — changed after this session</span>
                      ) : c.deleted ? (
                        <span className="sm err">deleted since</span>
                      ) : (
                        <span className="sm muted">{c.delivery === 'stub' ? 'stub only' : 'unchanged'}</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ flex: '1 1 260px', display: 'flex', flexDirection: 'column', gap: 12 }}>
              {changed.length > 0 ? (
                changed.map((f) => (
                  <React.Fragment key={f.id}>
                    <div className="finding">
                      <b>Finding</b>
                      <p className="muted" style={{ margin: '6px 0 0', lineHeight: 1.5 }}>
                        Memory #{result.context.findIndex((c) => c.id === f.id) + 1} was at <b>v{f.version_then}</b> when served; it was changed to v{f.version_now}
                        {f.changed_by ? ` by ${f.changed_by}` : ''}
                        {f.changed_at ? ` at ${fmtUtc(f.changed_at)} UTC` : ''}. The agent acted on the earlier version.
                      </p>
                    </div>
                    <div style={{ border: '1px solid #d2d2d2', borderRadius: 12, padding: 14, fontSize: 14 }}>
                      <b>Other agents exposed</b>
                      <p className="muted" style={{ margin: '6px 0 8px' }}>
                        v{f.version_then} was served to {f.other_actors_exposed} other agent{f.other_actors_exposed === 1 ? '' : 's'} before the change.
                      </p>
                      <a href={buildHash(`/memory/${f.id}`, { tab: 'access' })}>List sessions</a>
                    </div>
                  </React.Fragment>
                ))
              ) : (
                <div className="br" style={{ background: '#f3faf0', borderColor: '#afdc8f' }}>
                  <b>No later changes</b>
                  <p className="muted" style={{ margin: '6px 0 0', lineHeight: 1.5 }}>
                    Every memory the agent was served is still at the same version.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
};

const AuditLog: React.FC<{
  route: HashRoute;
  deniedOnly: boolean;
  personal?: boolean;
  setParam: (c: Record<string, string | undefined>) => void;
}> = ({ route, deniedOnly, setParam, personal }) => {
  const p = route.params;
  const op = p.get('op') || '';
  const decision = deniedOnly ? 'denied' : p.get('decision') || '';
  const hours = p.get('hours') ?? '24';
  const actor = p.get('actor') || '';
  const page = Number(p.get('page') || 1);
  const [expanded, setExpanded] = useState<Set<string | number>>(new Set());
  const params = { operation: op ? [op] : undefined, decision: decision || undefined, hours: hours === '0' ? undefined : Number(hours), actor: actor || undefined, page, per_page: 25 };
  const { data, error, loading, reload } = useApi<AuditResponse>(() => api.audit(params), [JSON.stringify(params)]);

  return (
    <section className="card" style={{ padding: 0 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', padding: '16px 20px' }}>
        <h3 style={{ marginRight: 'auto' }}>{deniedOnly ? 'Denied operations' : personal ? 'Your activity' : 'Audit log'}</h3>
        {actor && (
          <span className="chip">
            Actor: {actor}
            <button type="button" aria-label="Remove actor filter" onClick={() => setParam({ actor: undefined })}>
              ✕
            </button>
          </span>
        )}
        <SelectMenu
          label="Operation"
          value={op}
          onChange={(v) => setParam({ op: v || undefined })}
          options={[{ value: '', label: 'Operation: all' }, ...(data?.event_types ?? []).map((t) => ({ value: t, label: `Operation: ${data?.operations[t] ?? t}` }))]}
        />
        {!deniedOnly && (
          <SelectMenu
            label="Decision"
            value={decision}
            onChange={(v) => setParam({ decision: v || undefined })}
            options={[
              { value: '', label: 'Decision: all' },
              { value: 'allowed', label: 'Decision: permitted' },
              { value: 'denied', label: 'Decision: denied' },
            ]}
          />
        )}
        <SelectMenu label="Time range" value={hours} onChange={(v) => setParam({ hours: v === '24' ? undefined : v })} options={RANGES} />
      </div>
      {error && !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : loading && !data ? (
        <SkTable rows={8} cols={6} />
      ) : data!.items.length === 0 ? (
        <Empty title={deniedOnly ? 'No denied operations' : 'No audit events in this range'}>
          {deniedOnly
            ? 'Operations refused by RBAC or a curation rule appear here.'
            : 'Every MCP tool call that reads, writes or is refused is recorded here. Widen the time range or wait for agents to connect.'}
        </Empty>
      ) : (
        <>
          <div className="scroll">
            <table className="tbl" style={{ minWidth: 880 }}>
              <thead>
                <tr>
                  <th>Timestamp (UTC)</th>
                  <th>Operation</th>
                  <th>Actor</th>
                  <th>Target</th>
                  <th>Scope</th>
                  <th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {data!.items.map((e) => {
                  const d = decisionOf(e);
                  const open = expanded.has(e.id);
                  const actorSub =
                    (e.metadata as { via?: string }).via === 'dashboard'
                      ? 'dashboard'
                      : e.driver_id && e.driver_id !== e.actor_id
                        ? `for ${e.driver_id}`
                        : 'service';
                  return (
                    <React.Fragment key={e.id}>
                      <tr>
                        <td className="mono muted" style={{ whiteSpace: 'nowrap' }}>
                          {fmtUtc(e.timestamp)}
                        </td>
                        <td className="mono">{e.operation}</td>
                        <td className="sm">
                          <b>{e.actor_id}</b>
                          <div className="muted">{actorSub}</div>
                        </td>
                        <td style={{ maxWidth: 320 }}>
                          <EventTarget e={e} max={40} />
                        </td>
                        <td>{e.scope && !['all', 'session'].includes(e.scope) ? <ScopeLabel scope={e.scope} /> : <span className="muted">—</span>}</td>
                        <td className="sm">
                          <span className={d.cls} style={{ fontWeight: 600 }}>
                            {e.decision === 'denied' ? 'Denied' : d.label === 'Logged' ? 'Logged' : 'Permitted'}
                          </span>
                          <div className="muted">
                            {e.change ? (
                              <button
                                type="button"
                                className="link-btn sm"
                                onClick={() => {
                                  const n = new Set(expanded);
                                  if (open) n.delete(e.id);
                                  else n.add(e.id);
                                  setExpanded(n);
                                }}
                              >
                                v{e.change.before.version} → v{e.change.after.version} · {open ? 'collapse' : 'expand'}
                              </button>
                            ) : (
                              d.note ?? ''
                            )}
                          </div>
                        </td>
                      </tr>
                      {open && e.change && (
                        <tr style={{ background: '#fafafa' }}>
                          <td colSpan={6} style={{ padding: '14px 20px' }}>
                            <div className="sm" style={{ fontWeight: 600, marginBottom: 8 }}>
                              {e.operation} · {e.memory_id ? <a href={memoryHref(e.memory_id)}>{`mem_${e.memory_id.replace(/-/g, '').slice(0, 4)}…${e.memory_id.slice(-3)}`}</a> : ''} · state before / after
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
                              <pre>{JSON.stringify(e.change.before, null, 2)}</pre>
                              <pre>{JSON.stringify(e.change.after, null, 2)}</pre>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pager page={page} perPage={25} total={data!.total} onPage={(pg) => setParam({ page: String(pg) })} noun="events" />
        </>
      )}
      {!!data?.hidden_user_operations && (
        <div className="sm muted" style={{ padding: '12px 20px 0' }} role="note">
          {data.hidden_user_operations.toLocaleString('en-US')} operations on personal memories in this period are left out: only super-users audit user-scope activity.
        </div>
      )}
      <div className="sm muted" style={{ padding: '12px 20px' }}>
        Entries are immutable · full detail kept {data?.retention_days ?? 90} days, summaries 1 year, then archived to object storage.
      </div>
    </section>
  );
};

const Retention: React.FC = () => {
  const { data, error, loading, reload } = useApi(() => api.settings(), []);
  if (error && !data) return <div className="card"><ErrorState error={error} onRetry={reload} /></div>;
  if (loading || !data) return <div className="card"><SkLines lines={4} /></div>;
  const a = data.values.audit;
  return (
    <section className="card">
      <h3>Retention</h3>
      <div className="row">
        <div>
          <b style={{ fontSize: 14 }}>Full-detail retention</b>
          <div className="hint">Older partitions are summarised, then archived to MinIO.</div>
        </div>
        <span>{a.full_retention_days} days</span>
      </div>
      <div className="row">
        <div>
          <b style={{ fontSize: 14 }}>Read operation detail</b>
          <div className="hint">Writes and governance decisions are always logged in full.</div>
        </div>
        <span>{a.read_detail}</span>
      </div>
      <div className="row">
        <div>
          <b style={{ fontSize: 14 }}>Immutability</b>
          <div className="hint">PostgreSQL row-level security allows inserts only; updates and deletes are refused.</div>
        </div>
        <span className="ok">Enforced</span>
      </div>
      <a className="btn bs" href={buildHash('/settings', { section: 'audit' })} style={{ marginTop: 12 }}>
        Change in Settings
      </a>
    </section>
  );
};

export default Audit;
