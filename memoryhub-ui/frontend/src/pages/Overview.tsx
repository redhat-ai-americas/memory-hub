import React, { useState } from 'react';
import { api, ApiError } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { ErrorState, Icon, ScopeLabel, Sk, SkLines, Standby, Status, TOKEN_ESTIMATE_NOTE } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import type { AuditEvent, Onboarding, UsageSummary, Overview as OverviewData, OverviewRange } from '@/types';
import { fmtCompact, fmtInt, fmtTime, scopeMeta, shortId } from '@/utils/format';
import { ACTIVITY_RANGES, ActivityChart, PIE_COLORS, PieChart } from '@/components/charts';
import { actorKind, actorName, decisionOf, EventTarget, memoryHref, WriteMemoryModal } from './common';
import { RequestSentence, RequestStatus } from './requests';
import type { MyRequestsResponse } from '@/types';

/** A KPI tile. With an href the whole tile is a link to the records behind the number. */
const KpiCard: React.FC<{ label: string; href?: string; loading: boolean; value?: React.ReactNode; sub?: React.ReactNode }> = ({
  label,
  href,
  loading,
  value,
  sub,
}) => {
  const body = (
    <>
      <div className="sm muted kpi-label">
        {label}
        {href && <span className="kpi-go"><Icon.Arrow size={15} /></span>}
      </div>
      {loading ? (
        <>
          <Sk w="55%" h={34} style={{ margin: '8px 0 6px' }} />
          <Sk w="70%" h={12} />
        </>
      ) : (
        <>
          <div className="kpi">{value}</div>
          <div className="sm">{sub}</div>
        </>
      )}
    </>
  );
  return href ? (
    <a className="card kpi-card" href={href}>
      {body}
    </a>
  ) : (
    <div className="card">{body}</div>
  );
};

const Overview: React.FC = () => {
  const { tenant, role, standby, refreshCounts, me } = useApp();
  // Personal records stay metadata-only for admins unless incident access is on.
  const grant = me?.access?.break_glass ?? null;
  // While the tenant has no memories the page polls every 5 s until the
  // first write_memory arrives, then switches to the live layout.
  const [activityRange, setActivityRange] = useState<OverviewRange>('7d');
  const { data, error, loading, reload } = useApi<OverviewData>(() => api.overview(activityRange), [activityRange], standby ? 5000 : 30000);
  const [writeOpen, setWriteOpen] = useState(false);
  const selectedActivityRange = ACTIVITY_RANGES.find((item) => item.value === activityRange) ?? ACTIVITY_RANGES[4];
  const empty = data ? data.memories.current === 0 : standby;
  const first = loading && !data;
  const activityReady = Boolean(data && data.activity_range === activityRange);

  if (error && !data) {
    return (
      <>
        <Header tenant={tenant} role={role} onWrite={() => setWriteOpen(true)} onRefresh={reload} />
        <div className="body">
          <div className="card">
            <ErrorState error={error} onRetry={reload} title="The overview could not be loaded" />
          </div>
        </div>
      </>
    );
  }

  const total = data?.memories.current ?? 0;
  const scopes = (data?.scopes ?? []).filter((s) => s.count > 0 || scopeMeta(s.scope).cls !== 'g');
  // Largest categories get their own slice; the long tail folds into "Other"
  // so the pie stays readable.
  const cats = data?.categories ?? [];
  const MAX_SLICES = PIE_COLORS.length - 1;
  const categorySlices = (cats.length > MAX_SLICES + 1 ? cats.slice(0, MAX_SLICES) : cats).map((c) => ({
    key: c.name,
    label: c.name,
    value: c.memory_count,
    href: buildHash('/memories', { domain: c.name }),
  }));
  if (cats.length > MAX_SLICES + 1) {
    const rest = cats.slice(MAX_SLICES);
    categorySlices.push({
      key: '__other',
      label: `Other (${rest.length} categories)`,
      value: rest.reduce((a, c) => a + c.memory_count, 0),
      href: buildHash('/memories'),
    });
  }
  const healthBad = data?.health.filter((h) => h.status === 'down' || h.status === 'degraded') ?? [];
  const searchesHref = buildHash('/audit', { tab: 'log', op: 'memory.search' });

  return (
    <>
      <Header tenant={data?.tenant_id || tenant} role={role} onWrite={() => setWriteOpen(true)} onRefresh={reload} />
      <div className="body">
        {empty && !first && (
          <div className="alert" role="status">
            <Icon.Info stroke="#0066cc" style={{ flex: 'none', marginTop: 1 }} />
            <div style={{ flex: 1 }}>
              <b>Waiting for the first memory.</b> This tenant has no memories yet. Metrics fill in as soon as an agent calls{' '}
              <span className="mono">write_memory</span>; this page checks again every 5 seconds.
            </div>
            <a href={buildHash('/clients')} style={{ whiteSpace: 'nowrap', fontWeight: 500 }}>
              Connect an agent
            </a>
          </div>
        )}
        {!empty && role !== 'user' && data && data.approvals.enterprise_pending > 0 && (
          <div className="alert">
            <Icon.Info stroke="#0066cc" style={{ flex: 'none', marginTop: 1 }} />
            <div style={{ flex: 1 }}>
              <b>
                {data.approvals.enterprise_pending === 1
                  ? '1 enterprise-scope memory is waiting for approval.'
                  : `${fmtInt(data.approvals.enterprise_pending)} enterprise-scope memories are waiting for approval.`}
              </b>{' '}
              Enterprise memories never reach agents until a designated approver signs off.
            </div>
            <a href={buildHash('/review')} style={{ whiteSpace: 'nowrap', fontWeight: 500 }}>
              Open review queue
            </a>
          </div>
        )}

        {role !== 'admin' && <GettingStarted />}
        {role !== 'admin' && !empty && <AgentUsage />}

        <div className="grid-kpi">
          <KpiCard
            label="Current memories"
            loading={first}
            href={buildHash('/memories')}
            value={empty ? <span className="standby-val">0</span> : fmtInt(total)}
            sub={
              empty ? (
                <span className="standby-pulse">
                  <i />
                  Waiting for the first write
                </span>
              ) : data?.memories.growth_pct !== null && data?.memories.growth_pct !== undefined ? (
                <>
                  <span className="ok">▲ {data.memories.growth_pct}%</span> <span className="muted">vs. previous 7 days</span>
                </>
              ) : (
                <span className="muted">{fmtInt(data?.memories.new_7d)} written in the last 7 days</span>
              )
            }
          />
          <KpiCard
            label="Agents connected"
            loading={first}
            href={buildHash('/identities')}
            value={fmtInt(data?.agents.total)}
            sub={<span className="muted">{fmtInt(data?.agents.active_now)} with an active session now</span>}
          />
          <KpiCard
            label="Searches · 24 h"
            loading={first}
            href={searchesHref}
            value={empty && !data?.searches.last_24h ? <span className="standby-val">—</span> : fmtInt(data?.searches.last_24h)}
            sub={
              <span className="muted">
                {empty && !data?.searches.last_24h
                  ? 'Starts with the first memory'
                  : data?.searches.p95_latency_ms
                    ? `p95 latency ${fmtInt(data.searches.p95_latency_ms)} ms`
                    : role === 'user'
                      ? 'Across your connected agents'
                      : 'Across all agents'}
              </span>
            }
          />
          <KpiCard
            label="Open contradictions"
            loading={first}
            href={buildHash('/review', { tab: 'contradictions' })}
            value={empty ? <span className="standby-val">—</span> : fmtInt(data?.contradictions.open)}
            sub={
              empty ? (
                <span className="muted">Starts with the first memory</span>
              ) : data && data.contradictions.over_threshold > 0 ? (
                <span className="err">{fmtInt(data.contradictions.over_threshold)} over revision threshold</span>
              ) : (
                <span className="muted">None over the threshold of {data?.contradictions.threshold}</span>
              )
            }
          />
        </div>

        <div className="grid-2-1">
          <div className="card span-2 ops">
            <div className="ops-head">
              <div>
                <h2 data-h="3">Memory operations</h2>
                <div className="ops-sub">{selectedActivityRange.title}</div>
              </div>
              <div className="ops-tools">
                <div className="ops-range" role="group" aria-label="Memory operation range">
                  {ACTIVITY_RANGES.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      className={activityRange === item.value ? 'on' : ''}
                      aria-pressed={activityRange === item.value}
                      onClick={() => setActivityRange(item.value)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                <button type="button" className="ops-refresh" onClick={reload} disabled={loading} aria-label="Refresh memory operations" title="Refresh">
                  <span className={loading && data ? 'spin' : undefined} style={{ display: 'inline-flex' }}>
                    <Icon.Refresh size={15} />
                  </span>
                </button>
              </div>
            </div>
            {first || (loading && !activityReady) ? (
              <Sk h={290} r={8} />
            ) : empty ? (
              <Standby>Searches and writes from the audit log will chart here.</Standby>
            ) : (
              <>
                <ActivityChart data={data!.activity} bucketSeconds={data!.activity_bucket_seconds} range={activityRange} />
                {data!.activity_source === 'memory' && <p className="ops-foot">No audit events yet — showing memory writes only.</p>}
                {role === 'admin' && <ActorActivity range={activityRange} />}
              </>
            )}
          </div>
          {role === 'user' ? (
            <div className="stack">
              <MyScopes data={data} loading={first} empty={empty} />
              <CategoryChips data={data} loading={first} empty={empty} />
            </div>
          ) : (
          <div className="card">
            <div className="ch">
              <h2 data-h="3">Memories by scope</h2>
            </div>
            {first ? (
              <SkLines lines={6} gap={22} />
            ) : empty ? (
              <Standby>Counts for each of the six scope tiers appear here.</Standby>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {scopes.map((s) => {
                  const pct = total ? Math.round((s.count / total) * 100) : 0;
                  return (
                    <a
                      key={s.scope}
                      href={buildHash('/memories', { scope: s.scope })}
                      className="link-plain"
                      style={{ display: 'flex', flexDirection: 'column', gap: 6, color: 'inherit' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <ScopeLabel scope={s.scope} />
                        <span className="sm">
                          <b>{fmtInt(s.count)}</b>{' '}
                          <span className="muted">{s.pending > 0 ? `${fmtInt(s.pending)} pending` : `${pct}%`}</span>
                        </span>
                      </div>
                      <div className="bar">
                        <span style={{ width: `${s.count ? Math.max(1, pct) : 0}%`, background: scopeMeta(s.scope).color }} />
                      </div>
                    </a>
                  );
                })}
              </div>
            )}
          </div>
          )}
        </div>

        {role !== 'user' && (
        <div className="card">
          <div className="ch">
            <div>
              <h2 data-h="3">Memory categories</h2>
              <p className="sm muted" style={{ margin: '4px 0 0' }}>
                Category mix across all memories, by domain tag. A memory can have more than one category, so shares are of all assignments.
              </p>
            </div>
          </div>
          {first ? (
            <div style={{ display: 'flex', gap: 32, alignItems: 'center' }}>
              <Sk w={200} h={200} r={100} />
              <div style={{ flex: 1 }}>
                <SkLines lines={5} gap={18} />
              </div>
            </div>
          ) : empty ? (
            <Standby>The mix of domain tags across memories appears here.</Standby>
          ) : role === 'admin' && data && data.categories.length ? (
            <CategoryTable data={data} />
          ) : categorySlices.length ? (
            <>
              <PieChart slices={categorySlices} label={`Memory categories: ${categorySlices.map((c) => `${c.label} ${c.value}`).join(', ')}`} />
              <p className="sm muted" style={{ margin: '14px 0 0' }}>
                {fmtInt(data!.memories.current)} current memories · counts are memory–category assignments and may overlap.
              </p>
            </>
          ) : (
            <p className="sm muted" style={{ margin: 0 }}>
              No categories have been assigned to your visible memories yet. Add domain tags in the Memory browser to build this mix.
            </p>
          )}
        </div>
        )}

        <div className="grid-2-1">
          <div className="span-2 stack">
          <div className="card">
            <div className="ch">
              <h2 data-h="3">Recent activity</h2>
              <a className="sm" href={buildHash('/audit', { tab: 'log' })}>
                Open audit log
              </a>
            </div>
            {first ? (
              <SkLines lines={6} gap={22} />
            ) : empty && !data?.recent.length ? (
              <Standby>Every write, search and governance decision will be listed here as it happens.</Standby>
            ) : !data?.recent.length ? (
              <p className="sm muted">No activity recorded yet.</p>
            ) : (
              <div className="scroll">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Actor</th>
                      <th>Operation</th>
                      <th>Memory</th>
                      <th>Scope</th>
                      <th>Decision</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent.map((e) => {
                      const d = decisionOf(e);
                      return (
                        <tr key={`${e.id}-${e.timestamp}`}>
                          <td className="mono muted">{fmtTime(e.timestamp)}</td>
                          <td>
                            <div style={{ fontWeight: 500 }}>{actorName(e)}</div>
                            <div className="sm muted">{actorKind(e)}</div>
                          </td>
                          <td className="mono">{role === 'admin' ? toolName(e) : e.operation}</td>
                          <td style={{ maxWidth: 360 }}>
                            {role === 'admin' && !grant && e.scope === 'user' && e.event_type !== 'memory.search' ? <HiddenPersonal id={e.memory_id} /> : <EventTarget e={e} />}
                          </td>
                          <td>{e.scope && e.scope !== 'all' && e.scope !== 'session' ? <ScopeLabel scope={e.scope} /> : <span className="muted">—</span>}</td>
                          <td className={d.cls} style={{ fontWeight: 600 }}>
                            {d.label}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {data.recent_source === 'memory' && <p className="sm muted">No audit events yet — showing the latest memory writes.</p>}
              </div>
            )}
          </div>
          {role === 'admin' && !empty && <AgentUsage tenantWide />}
          </div>
          {role === 'user' ? (
            <div className="stack">
              <MyContradictions data={data} loading={first} />
              <MyOpenRequests />
              <ContextAssembly data={data} loading={first} empty={empty} />
            </div>
          ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="card">
              <div className="ch">
                <h2 data-h="3">Component health</h2>
                {data &&
                  (healthBad.length === 0 ? (
                    <span className="lbl s-org">All systems normal</span>
                  ) : (
                    <span className={`lbl ${healthBad.some((h) => h.status === 'down') ? 'red' : 'ylw'}`}>
                      {healthBad.length} need{healthBad.length === 1 ? 's' : ''} attention
                    </span>
                  ))}
              </div>
              {first ? (
                <SkLines lines={8} gap={20} />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {data!.health.map((h) => (
                    <div key={h.key} className="hrow" title={h.detail ?? undefined}>
                      <span>{h.name}</span>
                      <Status status={h.status}>
                        {h.status === 'healthy'
                          ? 'Healthy'
                          : h.status === 'degraded'
                            ? `Degraded${h.latency_ms ? ` · ${h.latency_ms} ms` : ''}`
                            : h.status === 'down'
                              ? h.detail || 'Down'
                              : h.status === 'idle'
                                ? 'No recent activity'
                                : 'Not configured'}
                      </Status>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="card">
              <h2 data-h="3" style={{ marginBottom: 12 }}>Context assembly</h2>
              {first ? (
                <SkLines lines={3} />
              ) : empty ? (
                <Standby>Cache hits and tokens per injection appear once agents start searching.</Standby>
              ) : (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <div>
                      <div className="sm muted">KV-cache prefix hits</div>
                      <div className="kpi" style={{ fontSize: 26 }}>
                        {data!.context_assembly.prefix_hit_rate !== null ? `${Math.round(data!.context_assembly.prefix_hit_rate * 100)}%` : '—'}
                      </div>
                    </div>
                    <div>
                      <div className="sm muted" title={TOKEN_ESTIMATE_NOTE}>Avg tokens / injection (est.)</div>
                      <div className="kpi" style={{ fontSize: 26 }}>
                        {fmtInt(data!.context_assembly.avg_tokens)}
                      </div>
                    </div>
                  </div>
                  <p className="sm muted" style={{ margin: '8px 0 0' }}>
                    {data!.context_assembly.avg_tokens === null && data!.context_assembly.prefix_hit_rate === null
                      ? 'Shown when the MCP server reports response tokens and cache hits with its search events.'
                      : 'Epoch-locked ordering keeps shared memory prefixes cache-friendly across agents.'}
                  </p>
                </>
              )}
            </div>
            {role === 'admin' && <QuotasGovernance data={data} loading={first} />}
          </div>
          )}
        </div>
      </div>
      {writeOpen && (
        <WriteMemoryModal
          onClose={() => setWriteOpen(false)}
          onSaved={() => {
            reload();
            refreshCounts();
          }}
        />
      )}
    </>
  );
};

const Header: React.FC<{ tenant: string; role: string; onWrite: () => void; onRefresh: () => void }> = ({ tenant, role, onWrite, onRefresh }) =>
  role === 'admin' ? (
    <PageHeader
      title="Tenant overview"
      crumbs={[{ label: 'Tenant overview' }]}
      description={
        <>
          Health and activity of governed agent memory for <b>{tenant || '…'}</b>. Every number links to the records behind it; personal records open as metadata.
        </>
      }
      actions={
        <>
          <button type="button" className="btn bs" onClick={onRefresh}>
            Refresh
          </button>
          <a className="btn bs" href={buildHash('/accounts', { invite: '1' })}>
            Invite users
          </a>
          <a className="btn bp" href={buildHash('/review')}>
            Open review queue
          </a>
        </>
      }
    />
  ) : (
  <PageHeader
    title="Overview"
    description={
      <>
        Health and activity of governed agent memory for tenant <b>{tenant || '…'}</b>. Every number links to the records behind it.
      </>
    }
    actions={
      <>
        <a className="btn bs" href={buildHash('/clients')}>
          Connect an agent
        </a>
        <button type="button" className="btn bp" onClick={onWrite}>
          <Icon.Plus />
          Write memory
        </button>
      </>
    }
  />
);

export default Overview;

/* ------------------------------------------------------------------ */
/* Tenant overview (platform admin)                                    */
/* ------------------------------------------------------------------ */

const RANGE_HOURS: Record<OverviewRange, number | undefined> = { all: undefined, '1h': 1, '12h': 12, '1d': 24, '7d': 168, '30d': 720 };

/** MCP tool names, as agents call them. */
const TOOL_NAME: Record<string, string> = {
  'memory.write': 'write_memory',
  'memory.update': 'update_memory',
  'memory.read': 'read_memory',
  'memory.search': 'search_memory',
  'memory.delete': 'delete_memory',
  'memory.restore': 'restore_memory',
  'memory.promote': 'promote',
  'review.promotion_proposed': 'promote',
  'memory.set_weight': 'set_weight',
  'memory.weight': 'set_weight',
  'memory.relationship_created': 'create_relationship',
  'memory.contradiction_reported': 'report_contradiction',
};
export const toolName = (e: AuditEvent) => TOOL_NAME[e.event_type] ?? TOOL_NAME[e.operation] ?? e.operation.replace(/^memory\./, '');

const KIND_LABEL: Record<string, string> = { human: 'People (dashboard)', user_agent: 'User agents', service_agent: 'Service agents' };
const kindOf = (e: AuditEvent): 'human' | 'user_agent' | 'service_agent' => {
  const k = actorKind(e);
  if (k.startsWith('human') || k === 'user') return 'human';
  if (k === 'user agent') return 'user_agent';
  return 'service_agent';
};

/** Who did the work in the selected range: writes and updates, searches and reads, per actor and per kind of actor. */
const ActorActivity: React.FC<{ range: OverviewRange }> = ({ range }) => {
  const { data, loading } = useApi<AuditEvent[]>(async () => {
    const all: AuditEvent[] = [];
    for (let page = 1; page <= 5; page += 1) {
      const res = await api.audit({ hours: RANGE_HOURS[range], page, per_page: 200 });
      all.push(...res.items);
      if (all.length >= res.total || res.items.length === 0) break;
    }
    return all;
  }, [range]);
  if (loading && !data) return <SkLines lines={4} />;
  const events = (data ?? []).filter((e) => e.decision !== 'denied');
  type Row = { actor: string; kind: 'human' | 'user_agent' | 'service_agent'; writes: number; searches: number };
  const rows = new Map<string, Row>();
  const kinds: Record<Row['kind'], { writes: number; searches: number; actors: Set<string> }> = {
    human: { writes: 0, searches: 0, actors: new Set() },
    user_agent: { writes: 0, searches: 0, actors: new Set() },
    service_agent: { writes: 0, searches: 0, actors: new Set() },
  };
  events.forEach((e) => {
    const isWrite = ['memory.write', 'memory.update'].includes(e.operation);
    const isSearch = ['memory.search', 'memory.read'].includes(e.operation);
    if (!isWrite && !isSearch) return;
    const kind = kindOf(e);
    const r = rows.get(e.actor_id) ?? { actor: e.actor_id, kind, writes: 0, searches: 0 };
    if (isWrite) r.writes += 1;
    else r.searches += 1;
    rows.set(e.actor_id, r);
    kinds[kind].actors.add(e.actor_id);
    if (isWrite) kinds[kind].writes += 1;
    else kinds[kind].searches += 1;
  });
  const top = [...rows.values()].sort((a, b) => b.writes + b.searches - (a.writes + a.searches)).slice(0, 6);
  const max = Math.max(1, ...top.map((r) => r.writes + r.searches));
  if (top.length === 0) return <p className="sm muted" style={{ margin: '12px 0 0' }}>No writes or searches by users or agents in this range.</p>;
  return (
    <div className="actor-act">
      <div className="kind-tiles">
        {(Object.keys(kinds) as Row['kind'][]).map((k) => (
          <div key={k}>
            <div className="sm muted">{KIND_LABEL[k]}</div>
            <div className="b6">
              {fmtInt(kinds[k].writes)} <span className="sm muted">writes</span> · {fmtInt(kinds[k].searches)} <span className="sm muted">searches</span>
            </div>
            <div className="hint">{kinds[k].actors.size} active</div>
          </div>
        ))}
      </div>
      <table className="tbl actor-tbl">
        <thead>
          <tr>
            <th>Most active</th>
            <th>Kind</th>
            <th style={{ width: '40%' }}>
              <span className="legend-dot w" /> Writes &amp; updates <span className="legend-dot s" /> Searches
            </th>
            <th style={{ textAlign: 'right' }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {top.map((r) => (
            <tr key={r.actor}>
              <td>
                <a href={buildHash('/audit', { tab: 'log', actor: r.actor })}>{r.actor}</a>
              </td>
              <td className="sm muted">{KIND_LABEL[r.kind]}</td>
              <td>
                <div className="stackbar" title={`${r.writes} writes & updates, ${r.searches} searches`}>
                  <span className="w" style={{ width: `${(r.writes / max) * 100}%` }} />
                  <span className="s" style={{ width: `${(r.searches / max) * 100}%` }} />
                </div>
              </td>
              <td className="sm" style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                {fmtInt(r.writes)} · {fmtInt(r.searches)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {(data?.length ?? 0) >= 1000 && <p className="hint">Counted from the latest 1,000 audit events in this range.</p>}
    </div>
  );
};

/** Categories as a ranked list with each category's share of all assignments. */
const CategoryTable: React.FC<{ data: OverviewData }> = ({ data }) => {
  const cats = [...data.categories].sort((a, b) => b.memory_count - a.memory_count);
  const totalAssign = cats.reduce((a, c) => a + c.memory_count, 0) || 1;
  const top = cats.slice(0, 10);
  const rest = cats.slice(10);
  const max = Math.max(1, ...top.map((c) => c.memory_count));
  const rows = rest.length ? [...top, { name: `Other · ${rest.length} categories`, memory_count: rest.reduce((a, c) => a + c.memory_count, 0), other: true }] : top;
  return (
    <div className="cat-table">
      <div className="cat-head sm muted">
        <span>Category</span>
        <span />
        <span style={{ textAlign: 'right' }}>Memories</span>
        <span style={{ textAlign: 'right' }}>Share</span>
      </div>
      {rows.map((c, i) => {
        const share = Math.round((c.memory_count / totalAssign) * 1000) / 10;
        const other = 'other' in c;
        const body = (
          <>
            <span className="cat-name">
              <span className="cat-rank">{other ? '' : i + 1}</span>
              {c.name}
            </span>
            <span className="bar thin">
              <span style={{ width: `${Math.max(1, (c.memory_count / max) * 100)}%`, background: other ? '#8a8d90' : undefined }} />
            </span>
            <span className="mono" style={{ textAlign: 'right' }}>
              {fmtInt(c.memory_count)}
            </span>
            <span className="mono muted" style={{ textAlign: 'right' }}>
              {share}%
            </span>
          </>
        );
        return other ? (
          <div key="other" className="cat-row">
            {body}
          </div>
        ) : (
          <a key={c.name} className="cat-row link-plain" href={buildHash('/memories', { domain: c.name })}>
            {body}
          </a>
        );
      })}
    </div>
  );
};

/** The tenant's limits and the governance work waiting. Each number opens the records behind it. */
const QuotasGovernance: React.FC<{ data: OverviewData | null | undefined; loading: boolean }> = ({ data, loading }) => {
  const { superuser } = useApp();
  const counts = useApi(() => api.browse({ per_page: 1 }), []);
  const blocks = useApi(() => api.audit({ decision: 'denied', operation: ['memory.write'], hours: 168, per_page: 1 }), []);
  const g = data?.governance;
  const quarantined = g?.quarantined ?? counts.data?.tab_counts.quarantined;
  const policyBlocks = g?.policy_blocks_7d ?? blocks.data?.total;
  const review = data?.approvals.pending_total;
  const row = (label: string, value: React.ReactNode) => (
    <>
      <dt>{label}</dt>
      <dd>{value === undefined || value === null ? <span className="muted">—</span> : value}</dd>
    </>
  );
  return (
    <section className="card">
      <h2 data-h="3" style={{ marginBottom: 12 }}>Quotas &amp; governance</h2>
      {loading ? (
        <SkLines lines={6} />
      ) : (
        <dl className="kv gov">
          {row('Storage quota', g?.storage_quota_pct !== undefined && g?.storage_quota_pct !== null ? `${g.storage_quota_pct}%${g.storage_quota_limit ? ` of ${fmtCompact(g.storage_quota_limit)}` : ''}` : null)}
          {row('Indexing backlog', g?.indexing_backlog !== undefined && g?.indexing_backlog !== null ? `${fmtInt(g.indexing_backlog)}${g.indexing_failed ? ` · ${fmtInt(g.indexing_failed)} failed` : ''}` : null)}
          {row('Policy blocks · 7 d', policyBlocks !== undefined ? <a href={buildHash('/audit', { tab: 'log', decision: 'denied', op: 'memory.write' })}>{fmtInt(policyBlocks)}</a> : null)}
          {row('Review queue', review !== undefined ? <a href={buildHash('/review')}>{fmtInt(review)} open</a> : null)}
          {row('Quarantined', quarantined !== undefined ? <a href={buildHash('/memories', { tab: 'quarantined' })}>{fmtInt(quarantined)}</a> : null)}
          {row('Pending hard deletes', g?.pending_hard_deletes !== undefined && g?.pending_hard_deletes !== null ? `${fmtInt(g.pending_hard_deletes)}${g.pending_hard_deletes ? ' · 2nd approver' : ''}` : null)}
          {row(
            'Incident grants on tenant',
            g?.incident_grants !== undefined && g?.incident_grants !== null ? (
              superuser ? <a href={buildHash('/incident')}>{fmtInt(g.incident_grants)} active</a> : `${fmtInt(g.incident_grants)} active`
            ) : null,
          )}
        </dl>
      )}
    </section>
  );
};

/** Personal records open as metadata for admins: the content is never drawn. */
const HiddenPersonal: React.FC<{ id: string | null }> = ({ id }) => (
  <span className="hidden-box" title="Personal content hidden — metadata only">
    <Icon.EyeOff />
    <span className="mono">{id ? shortId(id) : 'personal memory'}</span>
  </span>
);

/** Tenant-wide: how often agents act on what search hands them, by kind of agent. */
const TenantUsage: React.FC<{ data: UsageSummary }> = ({ data }) => {
  const pct = data.use_rate === null ? null : Math.round(data.use_rate * 100);
  const kinds = data.by_kind ?? null;
  return (
    <section className="card" aria-label="Agent usage">
      <div className="ch">
        <h2 data-h="3">Do agents use what they get?</h2>
        <span className="sm muted">Last 30 days · tenant</span>
      </div>
      <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '0 1 300px' }}>
          <div className="statv">{pct === null ? '—' : `${pct}%`}</div>
          <div className="sm muted">
            of {fmtInt(data.used + data.skipped)} measured search hits were acted on within 30 minutes. {fmtInt(data.full)} more delivered in full.
          </div>
        </div>
        <div style={{ flex: '1 1 320px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {kinds ? (
            ([['User agents', kinds.user_agents], ['Service agents', kinds.service_agents]] as [string, number | null][]).map(([label, rate]) => (
              <div key={label}>
                <div className="sm" style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>{label}</span>
                  <span>{rate === null ? '—' : `${Math.round(rate * 100)}%`}</span>
                </div>
                <div className="bar thin">
                  <span style={{ width: `${rate === null ? 0 : Math.round(rate * 100)}%` }} />
                </div>
              </div>
            ))
          ) : (
            <>
              <div className="sm b6">Skipped most often</div>
              {data.skipped_most.length === 0 ? (
                <p className="sm muted" style={{ margin: 0 }}>
                  Nothing stands out — agents act on what they get.
                </p>
              ) : (
                data.skipped_most.slice(0, 4).map((m) => (
                  <a key={m.id} className="conn link-plain" href={buildHash(`/memory/${m.id}`)}>
                    <span className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
                      {m.redacted ? 'Personal memory (metadata only)' : m.stub}
                    </span>
                    <span className="hint" style={{ whiteSpace: 'nowrap' }}>
                      skipped {m.skipped} of {m.served}
                    </span>
                  </a>
                ))
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
};


/** Getting started: what a new user still has to do. Hidden once done or dismissed. */
const GettingStarted: React.FC = () => {
  const { data, setData } = useApi<Onboarding>(() => api.onboarding(), []);
  if (!data?.steps || data.dismissed || data.done === data.total) return null;
  const dismiss = () => {
    setData({ ...data, dismissed: true });
    api.saveMyPrefs({ onboarding_dismissed: true }).catch(() => undefined);
  };
  return (
    <section className="card" aria-label="Getting started">
      <div className="ch">
        <div>
          <h2 data-h="3">Getting started</h2>
          <p className="sm muted" style={{ margin: '4px 0 0' }}>
            {data.done} of {data.total} done. Each step takes a minute.
          </p>
        </div>
        <button type="button" className="btn bl sm" onClick={dismiss}>
          Hide
        </button>
      </div>
      <div className="bar thin" style={{ marginTop: 10 }}>
        <span style={{ width: `${Math.round((data.done / data.total) * 100)}%` }} />
      </div>
      <div className="onb">
        {data.steps.map((s) => (
          <a key={s.id} href={buildHash(s.href)} className={s.done ? 'done' : ''}>
            <span className="chk" aria-hidden="true">
              {s.done ? '✓' : ''}
            </span>
            <span>
              <span className="sm b6" style={{ display: 'block' }}>
                {s.title}
                {s.done && <span className="vh"> (done)</span>}
              </span>
              <span className="hint">{s.body}</span>
            </span>
          </a>
        ))}
      </div>
    </section>
  );
};

/** Do agents act on what search returns? The memories they keep skipping. */
const AgentUsage: React.FC<{ tenantWide?: boolean }> = ({ tenantWide }) => {
  const { data } = useApi<UsageSummary>(() => api.usageSummary(30), []);
  if (!data || !data.served || !data.skipped_most) return null;
  if (tenantWide) return <TenantUsage data={data} />;
  const pct = data.use_rate === null ? null : Math.round(data.use_rate * 100);
  return (
    <section className="card" aria-label="Agent usage">
      <div className="ch">
        <h2 data-h="3">Do agents use what they get?</h2>
        <span className="sm muted">Last 30 days</span>
      </div>
      <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '0 1 260px' }}>
          <div className="statv">{pct === null ? '—' : `${pct}%`}</div>
          <div className="hint">
            of {fmtInt(data.used + data.skipped)} measured search hits were acted on — read, updated, linked or reported by the same agent within 30 minutes. {fmtInt(data.full)} more were delivered in full (weight ≥ 0.80).
          </div>
        </div>
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <div className="sm b6" style={{ marginBottom: 6 }}>
            Skipped most often
          </div>
          {data.skipped_most.length === 0 ? (
            <p className="sm muted" style={{ margin: 0 }}>
              Nothing stands out — agents act on what they get.
            </p>
          ) : (
            data.skipped_most.slice(0, 5).map((m) => (
              <a key={m.id} className="conn link-plain" href={buildHash(`/memory/${m.id}`)}>
                <span className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
                  {m.stub}
                </span>
                <span className="hint" style={{ whiteSpace: 'nowrap' }}>
                  skipped {m.skipped} of {m.served}
                </span>
              </a>
            ))
          )}
          {data.skipped_most.length > 0 && (
            <p className="hint" style={{ margin: '6px 0 0' }}>
              Rewrite them more clearly, lower their weight, or let Dreaming fade them.
            </p>
          )}
        </div>
      </div>
    </section>
  );
};

/* ------------------------------------------------------------------ */
/* User overview: the right-hand column                                */
/* ------------------------------------------------------------------ */

type OverviewCardProps = { data: OverviewData | null | undefined; loading: boolean; empty?: boolean };

/** Personal, each project and the shared scopes the user reads, with their counts. */
const MyScopes: React.FC<OverviewCardProps> = ({ data, loading, empty }) => {
  const rows =
    data?.my_scopes ??
    (data?.scopes ?? [])
      .filter((s) => s.count > 0)
      .map((s) => ({ scope: s.scope, scope_id: null, label: scopeMeta(s.scope).label, count: s.count, access: s.scope === 'user' || s.scope === 'project' ? ('write' as const) : ('read' as const) }));
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <section className="card">
      <div className="ch">
        <h2 data-h="3">My memories by scope</h2>
        <a className="sm" href={buildHash('/memories')}>
          View all
        </a>
      </div>
      {loading ? (
        <SkLines lines={6} gap={22} />
      ) : empty || rows.length === 0 ? (
        <Standby>Your personal, project and shared memories are counted here.</Standby>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {rows.map((r) => (
            <a
              key={`${r.scope}:${r.scope_id ?? ''}`}
              className="link-plain"
              style={{ display: 'flex', flexDirection: 'column', gap: 6, color: 'inherit' }}
              href={buildHash('/memories', r.scope === 'project' && r.scope_id ? { project: r.scope_id } : { scope: r.scope })}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <ScopeLabel scope={r.scope}>{r.access === 'read' ? `${r.label} · read` : r.label}</ScopeLabel>
                <b>{fmtInt(r.count)}</b>
              </div>
              <div className="bar">
                <span style={{ width: `${Math.max(1, Math.round((r.count / max) * 100))}%`, background: scopeMeta(r.scope).color }} />
              </div>
            </a>
          ))}
        </div>
      )}
    </section>
  );
};

/** Categories as a compact list of tags with counts; each opens the browser filtered by it. */
const CategoryChips: React.FC<OverviewCardProps> = ({ data, loading, empty }) => (
  <section className="card">
    <h2 data-h="3" style={{ marginBottom: 12 }}>Memory categories</h2>
    {loading ? (
      <SkLines lines={2} />
    ) : empty || !data?.categories.length ? (
      <p className="sm muted" style={{ margin: 0 }}>
        No categories yet. Add domain tags in the Memory browser.
      </p>
    ) : (
      <div className="chips">
        {data.categories.map((c) => (
          <a key={c.name} className="tag link-plain" href={buildHash('/memories', { domain: c.name })}>
            {c.name} {fmtInt(c.memory_count)}
          </a>
        ))}
      </div>
    )}
  </section>
);

/** Open contradictions on records the user can read. */
const MyContradictions: React.FC<OverviewCardProps> = ({ data, loading }) => {
  const items = data?.contradictions.items;
  return (
    <section className="card">
      <div className="ch">
        <h2 data-h="3">Contradictions</h2>
        <span className="lbl blue">Readable records only</span>
      </div>
      {loading ? (
        <SkLines lines={4} />
      ) : items && items.length > 0 ? (
        <div className="dotlist">
          {items.slice(0, 4).map((c) => (
            <div key={c.id}>
              <span className="dot-amber" aria-hidden="true" />
              <div style={{ minWidth: 0 }}>
                <a href={memoryHref(c.memory_id)}>{c.title}</a>
                <div className="sm muted">
                  {c.scope === 'user' ? 'Personal' : c.scope_label ?? c.scope_id ?? scopeMeta(c.scope).label} · {c.memories} {c.memories === 1 ? 'memory' : 'memories'}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : data && data.contradictions.open > 0 ? (
        <p className="sm" style={{ margin: 0 }}>
          <b>{fmtInt(data.contradictions.open)}</b> open on memories you can read. <a href={buildHash('/memories', { flag: 'contradicted' })}>Show them</a>
        </p>
      ) : (
        <p className="sm muted" style={{ margin: 0 }}>
          No open contradictions on memories you can read.
        </p>
      )}
    </section>
  );
};

/** The user's requests that are still waiting. */
const MyOpenRequests: React.FC = () => {
  const { data, error, loading } = useApi<MyRequestsResponse>(() => api.myRequests(), [], 60000);
  const open = (data?.items ?? []).filter((r) => r.state === 'open');
  return (
    <section className="card">
      <div className="ch">
        <h2 data-h="3">My open requests</h2>
        <a className="sm" href={buildHash('/review')}>
          My requests
        </a>
      </div>
      {loading && !data ? (
        <SkLines lines={3} />
      ) : error && !data ? (
        <p className="sm muted" style={{ margin: 0 }}>
          {error instanceof ApiError && error.status === 404 ? 'Requests are not available on this server yet.' : 'Requests could not be loaded.'}
        </p>
      ) : open.length === 0 ? (
        <p className="sm muted" style={{ margin: 0 }}>
          Nothing waiting for a decision.
        </p>
      ) : (
        <div className="dotlist">
          {open.slice(0, 4).map((r) => (
            <div key={r.id} style={{ alignItems: 'center' }}>
              <RequestStatus r={r} short />
              <span className="sm" style={{ minWidth: 0 }}>
                <RequestSentence r={r} />
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

/** Cache hits and tokens per injection, for the agents the user connects. */
const ContextAssembly: React.FC<OverviewCardProps> = ({ data, loading, empty }) => (
  <section className="card">
    <h2 data-h="3" style={{ marginBottom: 12 }}>Context assembly</h2>
    {loading ? (
      <SkLines lines={3} />
    ) : empty || !data ? (
      <Standby>Cache hits and tokens per injection appear once agents start searching.</Standby>
    ) : (
      <>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <div className="sm muted">KV-cache prefix hits</div>
            <div className="kpi" style={{ fontSize: 26 }}>
              {data.context_assembly.prefix_hit_rate !== null ? `${Math.round(data.context_assembly.prefix_hit_rate * 100)}%` : '—'}
            </div>
          </div>
          <div>
            <div className="sm muted" title={TOKEN_ESTIMATE_NOTE}>
              Avg tokens / injection (est.)
            </div>
            <div className="kpi" style={{ fontSize: 26 }}>
              {fmtInt(data.context_assembly.avg_tokens)}
            </div>
          </div>
        </div>
        <p className="sm muted" style={{ margin: '8px 0 0' }}>
          {data.context_assembly.avg_tokens === null && data.context_assembly.prefix_hit_rate === null
            ? 'Shown when the MCP server reports response tokens and cache hits with its search events.'
            : 'Epoch-locked ordering keeps shared memory prefixes cache-friendly across agents.'}
        </p>
      </>
    )}
  </section>
);
