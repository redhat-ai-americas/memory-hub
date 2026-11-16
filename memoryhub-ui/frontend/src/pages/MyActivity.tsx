import React, { useState } from 'react';
import { api } from '@/api/client';
import { Hub, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, Pager, ScopeLabel, Sk, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { AuditEvent, MyReads } from '@/types';
import { errorMessage, fmtInt, fmtMonthDay, fmtTime } from '@/utils/format';
import Operations from './Operations';
import Quality from './Quality';
import WhoRead from './WhoRead';
import { memoryHref } from './common';

type View = 'log' | 'reads' | 'jobs' | 'checks' | 'incidents';

/**
 * My activity (user): a personal projection of events about the viewer and
 * their data. Everything that used to have its own menu item for a user —
 * readers, background jobs, retrieval checks and incident notices — is a view here.
 */
const MyActivity: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { me } = useApp();
  const labs = Boolean(me?.labs);
  const reads = useApi<MyReads>(() => api.myReads(90, 'others'), []);
  // Old links (#/audit?tab=denied, ?view=denied) open the log filtered to denied operations.
  const legacyDenied = route.params.get('tab') === 'denied' || route.params.get('view') === 'denied';
  const hubRoute = legacyDenied ? { ...route, params: new URLSearchParams({ decision: 'denied' }) } : route;
  const incidents = reads.data ? reads.data.summary?.incident_grants ?? (reads.data.events ?? []).filter((e) => e.break_glass).length : null;

  const exportMine = async () => {
    try {
      const all: AuditEvent[] = [];
      for (let page = 1; page <= 25; page += 1) {
        const res = await api.audit({ page, per_page: 200 });
        all.push(...res.items);
        if (all.length >= res.total) break;
      }
      const blob = new Blob([all.map((e) => JSON.stringify(e)).join('\n')], { type: 'application/x-ndjson' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `memoryhub-my-activity-${new Date().toISOString().slice(0, 10)}.jsonl`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast(`Exported ${fmtInt(all.length)} events.`);
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };

  const views: { value: View; label: string; count?: number | null; render: () => React.ReactNode; showTitle?: boolean }[] = [
    { value: 'log', label: 'Activity log', render: () => <ActivityLog route={hubRoute} /> },
    { value: 'reads', label: 'Who read my memories', render: () => <WhoRead route={route} /> },
    { value: 'jobs', label: 'Background jobs', render: () => <Operations /> },
    ...(labs ? [{ value: 'checks' as const, label: 'Retrieval checks', render: () => <Quality route={route} /> }] : []),
    { value: 'incidents', label: 'Incident notices', count: incidents, render: () => <IncidentNotices data={reads.data} error={reads.error} reload={reads.reload} /> },
  ];

  return (
    <Hub
      title="My activity"
      description="A personal projection of events about you and your data: your and your agents’ changes, reads of your personal and project records, and background jobs. Not the tenant audit and not a raw log of other people."
      actions={
        <button type="button" className="btn bs" onClick={exportMine}>
          Export
        </button>
      }
      route={hubRoute}
      fallback="log"
      views={views}
    />
  );
};

/** Incident (break-glass) reads of your memories. Each carries its incident number. */
const IncidentNotices: React.FC<{ data: MyReads | null; error: Error | null; reload: () => void }> = ({ data, error, reload }) => {
  const events = (data?.events ?? []).filter((e) => e.break_glass);
  return (
    <div className="body">
      <section className="card">
        <div className="ch">
          <h2 data-h="3">Incident notices</h2>
          <span className="sm muted">Last 90 days</span>
        </div>
        {error && !data ? (
          <ErrorState error={error} onRetry={reload} compact />
        ) : !data ? (
          <SkLines lines={3} />
        ) : events.length === 0 ? (
          <Empty compact title="No incident access to your memories">
            A super-user can open personal memories only with an incident reference. If that ever happens to yours, each read is listed here with its incident number and you
            are notified.
          </Empty>
        ) : (
          events.map((e) => (
            <div key={String(e.id)} className="evrow">
              <span className="mono muted">{fmtMonthDay(e.timestamp)} {fmtTime(e.timestamp)}</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <b>{e.actor_id}</b> opened <a href={memoryHref(e.memory_id)}>{e.memory_stub}</a> under incident access
              </span>
              <span className="lbl red">break-glass</span>
            </div>
          ))
        )}
        <div className="alert ok-a" style={{ marginTop: 14 }}>
          <Icon.Shield stroke="#3d7317" style={{ flex: 'none', marginTop: 1 }} />
          <div>Any incident read of your memory appears here with its incident number.</div>
        </div>
      </section>
    </div>
  );
};


/* ------------------------------------------------------------------ */
/* Activity log: what you and your agents changed, and what was denied */
/* ------------------------------------------------------------------ */

const OP_NAME: Record<string, string> = {
  'memory.write': 'write_memory',
  'memory.update': 'update_memory',
  'memory.read': 'read_memory',
  'memory.search': 'search_memory',
  'memory.delete': 'delete_memory',
  'memory.restore': 'restore_memory',
  'memory.weight': 'set_weight',
  'memory.set_weight': 'set_weight',
  'memory.promote': 'promote_memory',
  'memory.relationship_created': 'create_relationship',
  'memory.branch_created': 'add_branch',
  'memory.contradiction_reported': 'report_contradiction',
};
const opName = (op: string) => OP_NAME[op] ?? op.replace(/^memory\./, '');
const READ_OPS = new Set(['memory.read', 'memory.search']);
const WRITE_OPS = new Set(['memory.write', 'memory.update']);

const PERIODS = [
  { value: '24', label: 'Last 24 hours', short: '24 h' },
  { value: '168', label: 'Last 7 days', short: '7 d' },
  { value: '720', label: 'Last 30 days', short: '30 d' },
  { value: '2160', label: 'Last 90 days', short: '90 d' },
];

const ruleOf = (e: AuditEvent) => {
  const m = e.metadata || {};
  return (m.rule as string) || (m.reason as string) || (m.detail as string) || '';
};

const ActivityLog: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { me } = useApp();
  const self = me?.username ?? '';
  const p = route.params;
  const hours = p.get('hours') ?? '168';
  const actorF = p.get('actor') ?? 'all';
  const opF = p.get('op') ?? '';
  const scopeF = p.get('scope') ?? 'all';
  const decisionF = p.get('decision') ?? '';
  const q = p.get('q') ?? '';
  const [text, setText] = useState(q);
  const [page, setPage] = useState(1);
  const period = PERIODS.find((x) => x.value === hours) ?? PERIODS[1];
  const set = (k: string, v: string | undefined) => {
    const next = new URLSearchParams(p);
    if (v) next.set(k, v);
    else next.delete(k);
    setPage(1);
    navigate(route.path, next, { replace: true });
  };

  // One fetch for the period; filters, counts and the side panels work on it.
  const { data, error, loading, reload } = useApi<AuditEvent[]>(async () => {
    const all: AuditEvent[] = [];
    for (let pg = 1; pg <= 5; pg += 1) {
      const res = await api.audit({ hours: Number(hours), page: pg, per_page: 200 });
      all.push(...res.items);
      if (all.length >= res.total || res.items.length === 0) break;
    }
    return all;
  }, [hours]);
  const deleted = useApi(() => api.browse({ tab: 'deleted', per_page: 1 }), []);

  const events = data ?? [];
  const isMe = (e: AuditEvent) => e.actor_id === self;
  const isMyAgent = (e: AuditEvent) => e.actor_id !== self && e.driver_id === self;
  const changes = events.filter((e) => !READ_OPS.has(e.operation));

  const rows = events.filter((e) => {
    if (actorF === 'me' && !isMe(e)) return false;
    if (actorF === 'agents' && !isMyAgent(e)) return false;
    if (opF && e.operation !== opF) return false;
    if (scopeF === 'personal' && e.scope !== 'user') return false;
    if (scopeF === 'projects' && e.scope !== 'project') return false;
    if (decisionF === 'permitted' && e.decision === 'denied') return false;
    if (decisionF === 'denied' && e.decision !== 'denied') return false;
    if (q) {
      const hay = `${e.memory_stub ?? ''} ${e.memory_id ?? ''} ${JSON.stringify(e.metadata ?? {})}`.toLowerCase();
      if (!hay.includes(q.toLowerCase())) return false;
    }
    return true;
  });
  const perPage = 25;
  const shown = rows.slice((page - 1) * perPage, page * perPage);

  const mine = changes.filter((e) => isMe(e) && e.decision !== 'denied');
  const agentWrites = changes.filter((e) => isMyAgent(e) && WRITE_OPS.has(e.operation) && e.decision !== 'denied');
  const agentNames = new Set(agentWrites.map((e) => e.actor_id));
  const blocked = changes.filter((e) => e.decision === 'denied' && WRITE_OPS.has(e.operation));

  const byActor = new Map<string, number>();
  changes.forEach((e) => {
    if (e.decision === 'denied') return;
    const k = isMe(e) ? 'Me (dashboard)' : e.actor_id;
    byActor.set(k, (byActor.get(k) ?? 0) + 1);
  });
  const actors = [...byActor.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  const maxActor = Math.max(1, ...actors.map((a) => a[1]));
  const opsSeen = [...new Set(events.map((e) => e.operation))].sort();

  return (
    <div className="body">
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          set('q', text.trim() || undefined);
        }}
      >
        <span className="in-icon">
          <Icon.Search size={15} />
          <label htmlFor="al-q" className="vh">
            Filter by memory, tag or ID
          </label>
          <input id="al-q" className="in" placeholder="Filter by memory, tag or ID" value={text} onChange={(e) => setText(e.target.value)} onBlur={() => set('q', text.trim() || undefined)} />
        </span>
        <FilterSelect id="al-period" label="Period" value={hours} onChange={(v) => set('hours', v === '168' ? undefined : v)} options={PERIODS.map((x) => [x.value, x.label])} />
        <FilterSelect
          id="al-actor"
          label="Actor"
          value={actorF}
          onChange={(v) => set('actor', v === 'all' ? undefined : v)}
          options={[
            ['all', 'Actor: me + my agents'],
            ['me', 'Actor: me'],
            ['agents', 'Actor: my agents'],
          ]}
        />
        <FilterSelect id="al-op" label="Operation" value={opF} onChange={(v) => set('op', v || undefined)} options={[['', 'Operation: all'], ...opsSeen.map((o) => [o, opName(o)] as [string, string])]} />
        <FilterSelect
          id="al-scope"
          label="Scope"
          value={scopeF}
          onChange={(v) => set('scope', v === 'all' ? undefined : v)}
          options={[
            ['all', 'Scope: personal + projects'],
            ['personal', 'Scope: personal'],
            ['projects', 'Scope: my projects'],
          ]}
        />
        <FilterSelect
          id="al-dec"
          label="Decision"
          value={decisionF}
          onChange={(v) => set('decision', v || undefined)}
          options={[
            ['', 'Decision: all'],
            ['permitted', 'Decision: permitted'],
            ['denied', 'Decision: denied'],
          ]}
        />
      </form>

      {error && !data ? (
        <div className="card">
          <ErrorState error={error} onRetry={reload} />
        </div>
      ) : (
        <>
          <div className="grid-kpi">
            <KpiTile label={`Changes by me · ${period.short}`} value={data ? mine.length : null} sub="dashboard edits, weights, relations" />
            <KpiTile
              label={`Writes by my agents · ${period.short}`}
              value={data ? agentWrites.length : null}
              sub={`${agentNames.size} agent${agentNames.size === 1 ? '' : 's'} · ${agentWrites.filter((e) => e.scope === 'user').length} personal, ${agentWrites.filter((e) => e.scope === 'project').length} project`}
            />
            <KpiTile label="Blocked by policy" value={data ? blocked.length : null} sub="nothing was stored" />
            <KpiTile label="Deleted · restorable" value={deleted.data ? deleted.data.tab_counts.deleted : null} sub="restore them from the Memory browser" href={buildHash('/memories', { tab: 'deleted' })} />
          </div>

          <div className="row-wrap">
            <section className="card" style={{ flex: '999 1 620px', minWidth: 0, padding: '8px 12px 4px' }}>
              {loading && !data ? (
                <SkTable rows={6} cols={7} />
              ) : rows.length === 0 ? (
                <Empty compact title="Nothing in this period">
                  {q || actorF !== 'all' || opF || scopeF !== 'all' || decisionF ? 'No events match these filters.' : 'Changes you and your agents make show up here.'}
                </Empty>
              ) : (
                <>
                  <div className="scroll">
                    <table className="tbl" style={{ minWidth: 720 }}>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Actor</th>
                          <th>Operation</th>
                          <th>Memory</th>
                          <th>Scope</th>
                          <th>Change</th>
                          <th>Decision</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shown.map((e) => (
                          <tr key={`${e.id}-${e.timestamp}`}>
                            <td className="mono" style={{ whiteSpace: 'nowrap' }}>
                              {new Date(e.timestamp).toDateString() === new Date().toDateString() ? fmtTime(e.timestamp).slice(0, 5) : (
                                <>
                                  {fmtMonthDay(e.timestamp)}
                                  <div className="hint mono">{fmtTime(e.timestamp).slice(0, 5)}</div>
                                </>
                              )}
                            </td>
                            <td style={{ maxWidth: 140 }}>
                              {isMe(e) ? me?.name || e.actor_id : e.actor_id}
                              <div className="hint">
                                {isMe(e) ? `me${(e.metadata?.origin as string) === 'dashboard' || (e.metadata?.via as string) === 'dashboard' ? ' · dashboard' : ''}` : isMyAgent(e) ? 'my agent · driver: me' : e.actor_type ?? ''}
                              </div>
                            </td>
                            <td className="mono sm">{opName(e.operation)}</td>
                            <td style={{ maxWidth: 200 }}>
                              {e.memory_id && e.decision !== 'denied' ? (
                                <a href={memoryHref(e.memory_id)}>{e.memory_stub ?? e.memory_id}</a>
                              ) : e.operation === 'memory.search' ? (
                                <span className="sm">“{String(e.metadata?.query ?? 'search')}”</span>
                              ) : (
                                <span className="sm">
                                  {e.memory_stub ?? '—'}
                                  {e.decision === 'denied' && <span className="muted"> (not stored)</span>}
                                </span>
                              )}
                            </td>
                            <td>{e.scope && e.scope !== 'session' && e.scope !== 'all' ? <ScopeLabel scope={e.scope}>{e.scope === 'user' ? 'Personal' : undefined}</ScopeLabel> : <span className="muted">—</span>}</td>
                            <td className="sm">
                              <ChangeCell e={e} />
                            </td>
                            <td className="sm" style={{ whiteSpace: 'nowrap' }}>
                              {e.decision === 'denied' ? (
                                <span className="err">
                                  ● Denied{ruleOf(e) ? ` · ${ruleOf(e)}` : ''}
                                </span>
                              ) : (
                                <span className="ok">● Permitted</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pager page={page} perPage={perPage} total={rows.length} onPage={setPage} noun="events" />
                </>
              )}
            </section>

            <aside className="col-side" style={{ flex: '1 1 320px' }}>
              <section className="card">
                <h2 data-h="3" style={{ marginBottom: 14 }}>By actor · {period.short}</h2>
                {actors.length === 0 && <p className="sm muted">No changes in this period.</p>}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {actors.map(([name, n]) => (
                    <div key={name}>
                      <div className="sm" style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>{name}</span>
                        <span>{n}</span>
                      </div>
                      <div className="bar thin">
                        <span style={{ width: `${Math.max(2, (n / maxActor) * 100)}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
                <a className="sm" href={buildHash('/identities')} style={{ display: 'inline-block', marginTop: 14 }}>
                  Manage my agents
                </a>
              </section>
              <section className="card">
                <div className="ch">
                  <h2 data-h="3">Blocked writes</h2>
                  <span className="lbl red">{blocked.length}</span>
                </div>
                <p className="sm" style={{ margin: '0 0 6px' }}>
                  Your agents tried to store something a rule forbids. Nothing was saved; the rule name tells you why.
                </p>
                {blocked.slice(0, 5).map((e) => (
                  <div key={`${e.id}-${e.timestamp}`} className="evrow" style={{ alignItems: 'center' }}>
                    <span className="lbl red">{ruleOf(e) || 'policy'}</span>
                    <span className="sm">
                      {e.actor_id} · {fmtMonthDay(e.timestamp)}
                    </span>
                  </div>
                ))}
                <a className="sm" href={buildHash('/curation')} style={{ display: 'inline-block', marginTop: 10 }}>
                  See rules that apply to me
                </a>
              </section>
            </aside>
          </div>
        </>
      )}
    </div>
  );
};

const FilterSelect: React.FC<{ id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][] }> = ({ id, label, value, onChange, options }) => (
  <>
    <label htmlFor={id} className="vh">
      {label}
    </label>
    <select id={id} className="in auto" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  </>
);

const KpiTile: React.FC<{ label: string; value: number | null; sub: string; href?: string }> = ({ label, value, sub, href }) => {
  const body = (
    <>
      <div className="sm">{label}</div>
      <div className="kpi">{value === null ? <Sk w={60} h={30} /> : fmtInt(value)}</div>
      <div className="sm muted">{sub}</div>
    </>
  );
  return href ? (
    <a className="card link-plain" href={href} style={{ color: 'inherit' }}>
      {body}
    </a>
  ) : (
    <div className="card">{body}</div>
  );
};

/** What the operation changed: a new version, a version bump with a diff link, or a weight change. */
const ChangeCell: React.FC<{ e: AuditEvent }> = ({ e }) => {
  if (e.decision === 'denied' || READ_OPS.has(e.operation)) return <span className="muted">—</span>;
  const c = e.change;
  if (c) {
    if (c.before.version !== c.after.version)
      return (
        <a href={buildHash(`/memory/${e.memory_id}`, { tab: 'versions' })}>
          v{c.before.version} → v{c.after.version} · view diff
        </a>
      );
    if (c.before.weight !== c.after.weight)
      return (
        <>
          {c.before.weight.toFixed(2)} → {c.after.weight.toFixed(2)}
        </>
      );
  }
  if (e.operation === 'memory.write') return <>new · v{e.memory_version ?? 1}</>;
  if (e.operation === 'memory.update' && e.memory_version && e.memory_version > 1)
    return (
      <a href={buildHash(`/memory/${e.memory_id}`, { tab: 'versions' })}>
        v{e.memory_version - 1} → v{e.memory_version} · view diff
      </a>
    );
  return <span className="muted">—</span>;
};

export default MyActivity;
