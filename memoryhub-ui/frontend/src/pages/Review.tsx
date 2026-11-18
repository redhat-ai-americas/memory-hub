import React, { useMemo } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, ScopeLabel, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { ContradictionReport, MemoryRecord } from '@/types';
import { errorMessage, scopeMeta, shortId, truncate } from '@/utils/format';
import { memoryHref } from './common';

const ago = (iso: string) => {
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
};
const day = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

/** Scope pill: a lock for personal records. */
const ScopePill: React.FC<{ scope: string }> = ({ scope }) =>
  scope === 'user' ? (
    <ScopeLabel scope="user">
      <Icon.Lock size={11} /> Personal
    </ScopeLabel>
  ) : (
    <ScopeLabel scope={scope}>{scopeMeta(scope).label}</ScopeLabel>
  );

/** Reports grouped by the memory they contradict. */
interface Group {
  memoryId: string;
  reports: ContradictionReport[];
  latest: string;
}

const groupReports = (reports: ContradictionReport[]): Group[] => {
  const byMemory = new Map<string, ContradictionReport[]>();
  reports.forEach((r) => byMemory.set(r.memory_id, [...(byMemory.get(r.memory_id) ?? []), r]));
  return [...byMemory.entries()]
    .map(([memoryId, list]) => ({ memoryId, reports: list, latest: list.reduce((a, r) => (r.created_at > a ? r.created_at : a), list[0].created_at) }))
    .sort((a, b) => b.latest.localeCompare(a.latest));
};

/**
 * Contradictions (admins). GET /api/contradictions lists the reports agents
 * and people filed against memories in the scopes this admin moderates;
 * PATCH /api/contradictions/{id} marks one resolved or open again. The BFF
 * refuses to let anyone resolve a report on their own memory or their own report.
 */
const Review: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { tenant, refreshCounts } = useApp();
  const tab = route.params.get('tab') === 'resolved' ? 'resolved' : 'open';
  const { data, error, loading, reload } = useApi(() => api.contradictions({ resolved: tab === 'resolved' }), [tab], 30000);
  const groups = useMemo(() => groupReports(data ?? []), [data]);
  const selectedId = route.params.get('memory');
  const selected = groups.find((g) => g.memoryId === selectedId) ?? groups[0];
  const setParam = (next: Record<string, string | undefined>) => {
    const params = new URLSearchParams(route.params);
    Object.entries(next).forEach(([k, v]) => (v ? params.set(k, v) : params.delete(k)));
    navigate(route.path, params, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Contradictions"
        crumbs={[{ label: 'Contradictions' }]}
        description={`Reports that a memory no longer matches what agents observe, for ${tenant}. Mark a report resolved once the memory has been corrected or the report rejected.`}
        tabs={
          <Tabs
            label="Report state"
            value={tab}
            onChange={(t) => setParam({ tab: t === 'open' ? undefined : t, memory: undefined })}
            tabs={[
              { value: 'open', label: 'Open', count: data && tab === 'open' ? data.length : null },
              { value: 'resolved', label: 'Resolved', count: data && tab === 'resolved' ? data.length : null },
            ]}
          />
        }
      />
      <div className="body">
        {error && !data ? (
          <div className="card">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : (
          <div className="row-wrap rq-layout">
            <aside className="rq-list card">
              {loading && !data ? (
                <SkLines lines={6} />
              ) : groups.length === 0 ? (
                <Empty compact title={tab === 'open' ? 'No open contradictions' : 'Nothing resolved yet'}>
                  {tab === 'open' ? 'Reports filed with report_contradiction appear here.' : 'Reports you or other admins resolve are kept here.'}
                </Empty>
              ) : (
                groups.map((g) => (
                  <button key={g.memoryId} type="button" className={`rq-item ${selected?.memoryId === g.memoryId ? 'on' : ''}`} onClick={() => setParam({ memory: g.memoryId })}>
                    <div className="rq-item-head">
                      <b>{truncate(g.reports[0].observed_behavior, 70)}</b>
                      <span className="sm muted">{ago(g.latest)}</span>
                    </div>
                    <div className="sm rq-item-sub">
                      <span className="mono">{shortId(g.memoryId)}</span> · {g.reports.length} report{g.reports.length === 1 ? '' : 's'} · reported by{' '}
                      {[...new Set(g.reports.map((r) => r.reporter))].join(', ')}
                    </div>
                  </button>
                ))
              )}
            </aside>

            <div className="rq-main">
              <section className="card rq-detail">
                {selected ? (
                  <Detail
                    key={`${selected.memoryId}-${tab}`}
                    group={selected}
                    resolvedTab={tab === 'resolved'}
                    onChanged={() => {
                      reload();
                      refreshCounts();
                    }}
                  />
                ) : loading && !data ? (
                  <SkLines lines={10} />
                ) : (
                  <Empty compact title="Nothing to review">
                    Pick a memory on the left when a report arrives.
                  </Empty>
                )}
              </section>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

const Detail: React.FC<{ group: Group; resolvedTab: boolean; onChanged: () => void }> = ({ group, resolvedTab, onChanged }) => {
  const toast = useToast();
  const memory = useApi<MemoryRecord>(() => api.memory(group.memoryId), [group.memoryId]);
  const [busy, setBusy] = React.useState<string | null>(null);

  const setResolved = async (ids: string[], resolved: boolean) => {
    setBusy(ids.length === 1 ? ids[0] : 'all');
    try {
      for (const id of ids) await api.setContradictionResolved(id, resolved);
      toast(resolved ? (ids.length === 1 ? 'Report marked resolved.' : `${ids.length} reports marked resolved.`) : 'Report opened again.');
      onChanged();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(null);
    }
  };

  const m = memory.data;
  return (
    <>
      <div className="rq-head">
        <div>
          <div className="sm muted">
            <span className="mono">{shortId(group.memoryId)}</span> · {group.reports.length} report{group.reports.length === 1 ? '' : 's'}
          </div>
          <h2 className="rq-title">{m ? truncate(m.stub || m.content, 90) : 'Contradicted memory'}</h2>
        </div>
      </div>

      <div className="rq-compare">
        <div className="rq-mem">
          {memory.error && !m ? (
            <p className="sm muted">{errorMessage(memory.error)}</p>
          ) : !m ? (
            <SkLines lines={3} />
          ) : (
            <>
              <div className="sm muted mono">
                v{m.version} · weight {m.weight.toFixed(2)} · <ScopePill scope={m.scope} />
              </div>
              <p>{m.content}</p>
              <div className="sm muted">
                {m.owner_id} · updated {day(m.updated_at)}
              </div>
            </>
          )}
        </div>
        {group.reports.map((r) => (
          <div className="rq-mem" key={r.id}>
            <div className="sm muted mono">
              {shortId(r.id, 'rpt')} · confidence {r.confidence.toFixed(2)}
            </div>
            <p>{r.observed_behavior}</p>
            <div className="sm muted" style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
              <span>
                {r.reporter} · {day(r.created_at)}
                {r.resolved_at ? ` · resolved ${day(r.resolved_at)}` : ''}
              </span>
              <button type="button" className="link-btn" disabled={!!busy} onClick={() => setResolved([r.id], !r.resolved)}>
                {r.resolved ? 'Open again' : 'Mark resolved'}
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="rq-decide">
        <div className="rq-actions">
          {!resolvedTab && (
            <button type="button" className="btn bp" disabled={!!busy} onClick={() => setResolved(group.reports.map((r) => r.id), true)}>
              {group.reports.length === 1 ? 'Mark resolved' : `Mark all ${group.reports.length} resolved`}
            </button>
          )}
          <a className="btn bs" href={memoryHref(group.memoryId)}>
            Open memory
          </a>
        </div>
        <p className="sm muted" style={{ margin: 0 }}>
          Correct the memory first if the report is right: open it and save a new version. You can never resolve a report on your own memory.
        </p>
      </div>
    </>
  );
};

export default Review;
