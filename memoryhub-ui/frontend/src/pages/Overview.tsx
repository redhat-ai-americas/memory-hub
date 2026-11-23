import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { ErrorState, Icon, ScopeLabel, Sk, SkLines, Standby } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import type { ContradictionStats, StatsResponse } from '@/types';
import { fmtInt, fmtRelative, scopeMeta, truncate } from '@/utils/format';
import { memoryHref, WriteMemoryModal } from './common';

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
        {href && (
          <span className="kpi-go">
            <Icon.Arrow size={15} />
          </span>
        )}
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

interface OverviewData {
  stats: StatsResponse;
  contradictions: ContradictionStats;
}

/**
 * Overview for both roles, from GET /api/stats (memory counts by scope, recent
 * writes, MCP health) and GET /api/contradictions/stats. Both are already
 * limited to what the viewer may see.
 */
const Overview: React.FC = () => {
  const { role, tenant, refreshCounts } = useApp();
  const [writing, setWriting] = useState(false);
  const { data, error, loading, reload } = useApi<OverviewData>(
    async () => {
      const [stats, contradictions] = await Promise.all([api.stats(), api.contradictionStats()]);
      return { stats, contradictions };
    },
    [],
    60000,
  );
  const first = loading && !data;
  const total = data?.stats.total_memories ?? 0;
  const empty = !!data && total === 0;
  const isAdmin = role === 'admin';
  const scopes = [...(data?.stats.scope_counts ?? [])].sort((a, b) => b.count - a.count);

  return (
    <>
      <PageHeader
        title={isAdmin ? 'Tenant overview' : 'Overview'}
        crumbs={[{ label: isAdmin ? 'Tenant overview' : 'Overview' }]}
        description={
          isAdmin ? (
            <>
              Governed agent memory for <b>{tenant || '…'}</b> in the scopes you moderate. Personal memories are counted, never shown.
            </>
          ) : (
            <>
              The memories you can read in tenant <b>{tenant || '…'}</b>: your own and what your projects and organization share with you.
            </>
          )
        }
        actions={
          <>
            <button
              type="button"
              className="btn bs"
              onClick={() => {
                reload();
                refreshCounts();
              }}
            >
              Refresh
            </button>
            {isAdmin ? (
              <a className="btn bp" href={buildHash('/review')}>
                Open contradictions
              </a>
            ) : (
              <button type="button" className="btn bp" onClick={() => setWriting(true)}>
                <Icon.Plus />
                Write memory
              </button>
            )}
          </>
        }
      />
      <div className="body">
        {error && !data ? (
          <div className="card">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : (
          <>
            {data && !data.stats.mcp_health && (
              <div className="alert warn-a" role="status">
                <Icon.Info style={{ flex: 'none', marginTop: 1 }} />
                <div>
                  <b>The MCP server did not answer its health check.</b> Agents may not be able to read or write memories right now.
                </div>
              </div>
            )}

            <div className="grid-kpi">
              <KpiCard
                label={isAdmin ? 'Current memories' : 'Memories you can read'}
                loading={first}
                href={buildHash('/memories')}
                value={empty ? <span className="standby-val">0</span> : fmtInt(total)}
                sub={
                  empty ? (
                    <span className="standby-pulse">
                      <i />
                      Waiting for the first write
                    </span>
                  ) : (
                    <span className="muted">Current versions, not deleted</span>
                  )
                }
              />
              <KpiCard
                label="Open contradictions"
                loading={first}
                href={isAdmin ? buildHash('/review') : buildHash('/memories', { flag: 'contradicted' })}
                value={fmtInt(data?.contradictions.unresolved)}
                sub={<span className="muted">{fmtInt(data?.contradictions.total)} reported in total</span>}
              />
              <KpiCard
                label="High-confidence reports"
                loading={first}
                value={fmtInt(data?.contradictions.high_confidence)}
                sub={
                  <span className="muted">
                    {fmtInt(data?.contradictions.medium_confidence)} medium · {fmtInt(data?.contradictions.low_confidence)} low
                  </span>
                }
              />
              <KpiCard
                label="MCP server"
                loading={first}
                value={data?.stats.mcp_health ? 'Healthy' : 'Unreachable'}
                sub={<span className="muted">Health check from the dashboard backend</span>}
              />
            </div>

            <div className="grid-2-1">
              <div className="card span-2">
                <div className="ch">
                  <h2 data-h="3">Recent activity</h2>
                  <a className="sm" href={buildHash('/memories', { sort: 'updated' })}>
                    Open Memory browser
                  </a>
                </div>
                {first ? (
                  <SkLines lines={6} gap={22} />
                ) : empty ? (
                  <Standby>Memories appear here as agents and people write them.</Standby>
                ) : !data?.stats.recent_activity.length ? (
                  <p className="sm muted">No activity recorded yet.</p>
                ) : (
                  <div className="scroll">
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>When</th>
                          <th>Memory</th>
                          {role === 'user' && <th>Owner</th>}
                          <th>Scope</th>
                          <th>Change</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.stats.recent_activity.map((r) => (
                          <tr key={`${r.id}-${r.updated_at}`}>
                            <td className="muted" style={{ whiteSpace: 'nowrap' }}>
                              {fmtRelative(r.updated_at)}
                            </td>
                            <td style={{ maxWidth: 420 }}>
                              <a href={memoryHref(r.id)}>{truncate(r.stub, 110)}</a>
                            </td>
                            {role === 'user' && <td>{r.owner_id}</td>}
                            <td>
                              <ScopeLabel scope={r.scope} />
                            </td>
                            <td className="muted">{r.action}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="card">
                <div className="ch">
                  <h2 data-h="3">{isAdmin ? 'Memories by scope' : 'My memories by scope'}</h2>
                </div>
                {first ? (
                  <SkLines lines={6} gap={22} />
                ) : empty || scopes.length === 0 ? (
                  <Standby>Counts for each scope appear here.</Standby>
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
                              <b>{fmtInt(s.count)}</b> <span className="muted">{`${pct}%`}</span>
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
          </>
        )}
      </div>
      {writing && <WriteMemoryModal onClose={() => setWriting(false)} onSaved={() => reload()} />}
    </>
  );
};

export default Overview;
