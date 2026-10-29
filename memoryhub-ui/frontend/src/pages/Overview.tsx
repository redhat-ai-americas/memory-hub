import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { ErrorState, Icon, ScopeLabel, Sk, SkLines, Standby, Status, TOKEN_ESTIMATE_NOTE } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import type { Onboarding, UsageSummary, Overview as OverviewData, OverviewRange } from '@/types';
import { fmtInt, fmtTime, scopeMeta } from '@/utils/format';
import { ACTIVITY_RANGES, ActivityChart, PIE_COLORS, PieChart } from '@/components/charts';
import { actorKind, actorName, decisionOf, EventTarget, WriteMemoryModal } from './common';

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
  const { tenant, role, standby, refreshCounts } = useApp();
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
        <Header tenant={tenant} onWrite={() => setWriteOpen(true)} />
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
      <Header tenant={data?.tenant_id || tenant} onWrite={() => setWriteOpen(true)} />
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
        {!empty && data && data.approvals.enterprise_pending > 0 && (
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
                <h3>Memory operations</h3>
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
              </>
            )}
          </div>
          <div className="card">
            <div className="ch">
              <h3>Memories by scope</h3>
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
        </div>

        <div className="card">
          <div className="ch">
            <div>
              <h3>Memory categories</h3>
              <p className="sm muted" style={{ margin: '4px 0 0' }}>
                Category mix across all memories, by domain tag. A memory can have more than one category.
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

        <div className="grid-2-1">
          <div className="card span-2">
            <div className="ch">
              <h3>Recent activity</h3>
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
                          <td className="mono">{e.operation}</td>
                          <td style={{ maxWidth: 360 }}>
                            <EventTarget e={e} />
                          </td>
                          <td>{e.scope && e.scope !== 'all' && e.scope !== 'session' ? <ScopeLabel scope={e.scope} /> : <span className="muted">—</span>}</td>
                          <td className={d.cls} style={{ fontWeight: 500 }}>
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="card">
              <div className="ch">
                <h3>Component health</h3>
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
              <h3 style={{ marginBottom: 12 }}>Context assembly</h3>
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
          </div>
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

const Header: React.FC<{ tenant: string; onWrite: () => void }> = ({ tenant, onWrite }) => (
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
          <h3>Getting started</h3>
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
const AgentUsage: React.FC = () => {
  const { data } = useApi<UsageSummary>(() => api.usageSummary(30), []);
  if (!data || !data.served || !data.skipped_most) return null;
  const pct = data.use_rate === null ? null : Math.round(data.use_rate * 100);
  return (
    <section className="card" aria-label="Agent usage">
      <div className="ch">
        <h3>Do agents use what they get?</h3>
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
