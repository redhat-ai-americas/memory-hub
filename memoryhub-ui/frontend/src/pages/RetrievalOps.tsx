import React, { useState } from 'react';
import { api } from '@/api/client';
import { EmbedContext, PageHeader, Tabs } from '@/components/Shell';
import { Empty, ErrorState, Seg, SkLines } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { JobRow, OperationsResponse, SearchHealth } from '@/types';
import { fmtInt, fmtRelative } from '@/utils/format';
import Operations from './Operations';
import { Checks, Runs } from './Quality';
import Search from './Search';

type View = 'runs' | 'checks' | 'indexing' | 'playground' | 'jobs' | 'errors';
const VIEWS: View[] = ['runs', 'checks', 'indexing', 'playground', 'jobs', 'errors'];

const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined || Number.isNaN(v) ? '—' : `${(v * 100).toFixed(digits)}%`);
const ms = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v < 1 ? '<1 ms' : `${Math.round(v)} ms`);
const fmtDur = (v: number | null) => {
  if (v === null || v === undefined) return '—';
  if (v < 1000) return `${Math.round(v)} ms`;
  const s = Math.round(v / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
};
const timeOrDate = (iso: string) => {
  const d = new Date(iso);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
    : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
};

/** Why an expected memory was matched but not delivered, and what usually fixes it. */
const CUTS: Record<string, { reason: string; fix: (h: SearchHealth) => string }> = {
  limit: { reason: 'Rank beyond max_results', fix: () => 'Raise max_results for curator agents' },
  superseded: { reason: 'Superseded version', fix: () => 'Expected — newer version delivered' },
  weight: { reason: 'Below weight threshold', fix: () => 'Review fading suggestions' },
  index_lag: { reason: 'Index lag', fix: (h) => (h.index_backlog ? `Indexing backlog ${fmtInt(h.index_backlog)} items` : 'Check the indexing backlog') },
  budget: { reason: 'Token budget', fix: () => 'Raise max_response_tokens' },
  filters: { reason: 'Filtered out by the request', fix: () => 'Check the agent’s scope and project filters' },
  rbac: { reason: 'Outside the caller’s access', fix: () => 'Expected — access rules' },
};

const STAGE_LABEL: Record<string, string> = { rbac: 'RBAC filter', filter: 'RBAC filter', filters: 'RBAC filter', vector: 'Vector search', embed: 'Vector search', lexical: 'Lexical', fts: 'Lexical', rerank: 'Rerank', assemble: 'Assemble', format: 'Assemble' };
const stageLabel = (n: string) => STAGE_LABEL[n.toLowerCase()] ?? n.charAt(0).toUpperCase() + n.slice(1);

/** Admin menu item "Retrieval health & operations": how search works across the tenant, and the jobs behind it. */
const RetrievalOps: React.FC<{ route: HashRoute }> = ({ route }) => {
  const requested = route.params.get('view');
  const view: View = VIEWS.includes(requested as View) ? (requested as View) : requested === 'health' ? 'runs' : 'runs';
  const days = ['1', '7', '30'].includes(route.params.get('days') || '') ? route.params.get('days')! : '7';
  const go = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams();
    const v = patch.view ?? view;
    const d = patch.days ?? days;
    if (v !== 'runs') next.set('view', v);
    if (d !== '7') next.set('days', d);
    navigate('/quality', next, { replace: true });
  };
  const checks = useApi(() => api.checks(), []);
  const failed = useApi(() => api.operations({ days: Number(days), status: 'failed' }), [days]);
  const checkCount = checks.data ? checks.data.checks.length : null;
  const errorCount = failed.data ? failed.data.items.length : null;

  return (
    <>
      <PageHeader
        title="Retrieval health & operations"
        crumbs={[{ label: 'Retrieval health' }]}
        description="How well search works across the tenant: stage timings, where matches are cut, reranker behaviour and background jobs. Aggregates only — no query text from personal sessions."
        actions={
          <Seg
            label="Period"
            value={days}
            onChange={(d) => go({ days: d })}
            options={[
              { value: '1', label: '24 h' },
              { value: '7', label: '7 d' },
              { value: '30', label: '30 d' },
            ]}
          />
        }
        tabs={
          <Tabs
            label="Retrieval health"
            value={view}
            onChange={(v) => go({ view: v })}
            tabs={[
              { value: 'runs', label: 'Search runs' },
              { value: 'checks', label: 'Org checks', count: checkCount },
              { value: 'indexing', label: 'Indexing & reranker' },
              { value: 'playground', label: 'Search playground' },
              { value: 'jobs', label: 'Background jobs' },
              { value: 'errors', label: 'Errors', count: errorCount },
            ]}
          />
        }
      />
      {view === 'runs' && <SearchRuns days={days} recall={checks.data?.last?.summary} checkCount={checkCount} onView={(v) => go({ view: v })} />}
      {view === 'indexing' && <Indexing days={days} />}
      <EmbedContext.Provider value={{ showTitle: false }}>
        {view === 'checks' && (
          <div className="body">
            <OrgChecks />
          </div>
        )}
        {view === 'playground' && <Search route={route} />}
        {view === 'jobs' && <Operations key={`jobs${days}`} days={days} description="Every background job in the tenant — hygiene and dreaming, embedding retries, retention purges, compaction proposals, check runs — with status, duration, attempts and a correlation ID. Metadata only." />}
        {view === 'errors' && (
          <Operations key={`err${days}`} days={days} initialStatus="failed" description="Failed background jobs in this period. Retry the ones that can be retried; the correlation ID links every attempt of the same job." />
        )}
      </EmbedContext.Provider>
    </>
  );
};

const OrgChecks: React.FC = () => {
  const [tab, setTab] = useState<'checks' | 'runs'>('checks');
  return (
    <>
      <Seg
        label="Org checks"
        value={tab}
        onChange={setTab}
        options={[
          { value: 'checks', label: 'Checks' },
          { value: 'runs', label: 'Runs & compare' },
        ]}
      />
      {tab === 'checks' ? <Checks /> : <Runs />}
    </>
  );
};

const Tile: React.FC<{ label: string; value: React.ReactNode; sub: React.ReactNode; loading?: boolean }> = ({ label, value, sub, loading }) => (
  <section className="card">
    <div className="sm muted">{label}</div>
    {loading ? <SkLines lines={2} /> : (
      <>
        <div className="kpi">{value}</div>
        <div className="sm">{sub}</div>
      </>
    )}
  </section>
);

const SearchRuns: React.FC<{
  days: string;
  recall?: { checks: number; recall?: number; hit_rate?: number; failing?: number } | null;
  checkCount: number | null;
  onView: (v: View) => void;
}> = ({ days, recall, checkCount, onView }) => {
  const { data, error, loading, reload } = useApi<SearchHealth>(() => api.searchHealth(Number(days)), [days]);
  const h = data;
  const first = loading && !h;
  const zero = h?.zero_result_share ?? h?.empty_share;
  const success = h?.success_rate ?? (zero !== undefined ? 1 - zero : undefined);
  const stages = h?.stages ?? [];
  const p95 = new Map((h?.stages_p95 ?? []).map((s) => [s.name.toLowerCase(), s.p95]));
  const rerankStage = stages.find((s) => s.name.toLowerCase() === 'rerank');
  const rerankP95 = p95.get('rerank');
  const maxStage = Math.max(1, ...stages.map((s) => s.p50));
  const slowest = stages.reduce<string | null>((a, s) => (a === null || s.p50 > (stages.find((x) => x.name === a)?.p50 ?? 0) ? s.name : a), null);

  const sources = h?.sources ?? {};
  const totalSrc = Object.values(sources).reduce((a, b) => a + b, 0);
  const share = h?.share ?? {};
  const vector = share.vector ?? h?.vector_share;
  const lexical = share.lexical ?? (vector !== undefined ? 1 - vector : undefined);
  const rr = h?.rerank ?? {};
  const rrTotal = Object.values(rr).reduce((a, b) => a + b, 0);
  const fallback = share.fallback_no_rerank ?? (rrTotal ? (rr.off ?? rr.fallback ?? 0) / rrTotal : undefined);

  const cuts = Object.entries({ ...(h?.cut ?? {}), ...(h?.cut_extra ?? {}) })
    .filter(([, v]) => typeof v === 'number')
    .map(([k, v]) => ({ key: k, share: v as number }));
  const cutTotal = cuts.reduce((a, c) => a + c.share, 0);
  const cutRows = cuts
    .map((c) => ({ ...c, rel: cutTotal ? c.share / cutTotal : 0 }))
    .filter((c) => c.share > 0)
    .sort((a, b) => b.share - a.share);

  const recallValue = recall?.recall ?? recall?.hit_rate;
  const passing = recall ? recall.checks - (recall.failing ?? 0) : null;

  return (
    <div className="body">
      {error && !h ? (
        <section className="card">
          <ErrorState error={error} onRetry={reload} />
        </section>
      ) : (
        <div className="grid-kpi">
          <Tile loading={first} label="Search success" value={pct(success, 1)} sub={`zero-result ${pct(zero, 1)}`} />
          <Tile
            loading={first}
            label="p95 latency"
            value={ms(h?.latency?.p95)}
            sub={rerankP95 !== undefined ? `reranker p95 ${ms(rerankP95)}` : rerankStage ? `reranker median ${ms(rerankStage.p50)}` : `median ${ms(h?.latency?.p50)}`}
          />
          <Tile
            loading={first}
            label="Recall@5 · org checks"
            value={recallValue !== undefined ? recallValue.toFixed(2) : '—'}
            sub={
              recall && passing !== null ? (
                `${passing} of ${recall.checks} checks pass`
              ) : (
                <button type="button" className="link-btn" onClick={() => onView('checks')}>
                  {checkCount ? 'Run org checks' : 'Set up org checks'}
                </button>
              )
            }
          />
          <Tile loading={first} label="Stale-result attempts" value={h?.stale_filtered !== undefined ? fmtInt(h.stale_filtered) : '—'} sub="superseded filtered out" />
        </div>
      )}

      <div className="row-wrap">
        <div className="col-main">
          <section className="card">
            <h3>Stage time (median)</h3>
            {first ? (
              <SkLines lines={5} />
            ) : stages.length === 0 ? (
              <p className="sm muted" style={{ marginTop: 10 }}>No stage timings recorded in this period.</p>
            ) : (
              <div className="stage-bars">
                {stages.map((s) => (
                  <div key={s.name} className="stage-bar">
                    <div className="stage-head">
                      <span>{stageLabel(s.name)}</span>
                      <span className="muted">{ms(s.p50)}</span>
                    </div>
                    <div className="bar thin">
                      <span style={{ width: `${Math.max(2, (s.p50 / maxStage) * 100)}%`, background: s.name === slowest && stages.length > 1 ? '#f0ab00' : undefined }} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <h3>Where matches are cut</h3>
              <span className="sm muted">Expected memory present but not delivered</span>
            </div>
            {first ? (
              <SkLines lines={4} />
            ) : cutRows.length === 0 ? (
              <p className="sm muted" style={{ marginTop: 10 }}>Nothing was cut in this period — every matched memory was delivered.</p>
            ) : (
              <table className="tbl mid" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th>Reason</th>
                    <th style={{ width: 90 }}>Share</th>
                    <th>Typical fix</th>
                  </tr>
                </thead>
                <tbody>
                  {cutRows.map((c) => (
                    <tr key={c.key}>
                      <td>{CUTS[c.key]?.reason ?? c.key}</td>
                      <td>{pct(c.rel)}</td>
                      <td className="muted">{h ? CUTS[c.key]?.fix(h) ?? '—' : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <JobsCard days={days} onView={onView} />
        </div>

        <aside className="col-side">
          <section className="card">
            <h3>Sources &amp; reranker</h3>
            {first ? (
              <SkLines lines={4} />
            ) : (
              <dl className="kv" style={{ marginTop: 14 }}>
                <dt>Vector share of top-5</dt>
                <dd>{pct(vector)}</dd>
                <dt>Lexical share</dt>
                <dd>{pct(lexical)}</dd>
                <dt>Rerank changed top-1</dt>
                <dd>{pct(share.rerank_changed_top1)}</dd>
                <dt>Fallback (no rerank)</dt>
                <dd>{pct(fallback, 1)}</dd>
                {totalSrc > 0 && share.vector === undefined && (
                  <>
                    <dt className="muted">Search runs</dt>
                    <dd className="muted">{fmtInt(h?.runs ?? totalSrc)}</dd>
                  </>
                )}
              </dl>
            )}
          </section>
          <section className="card">
            <h3>Search playground</h3>
            <p className="sm" style={{ margin: '10px 0 14px' }}>
              Run any query as yourself or a service agent. Personal scope is removed before ranking, so admin results never include it.
            </p>
            <button type="button" className="btn bs" onClick={() => onView('playground')}>
              Open playground
            </button>
          </section>
          <section className="card">
            <h3>Compare</h3>
            <p className="sm" style={{ margin: '10px 0 14px' }}>
              A/B two retrieval settings on the {checkCount ?? ''} org checks before changing tenant defaults.
            </p>
            <button type="button" className="btn bs" onClick={() => onView('checks')}>
              Open org checks
            </button>
          </section>
        </aside>
      </div>
    </div>
  );
};

const STATUS: Record<JobRow['status'], { label: string; color: string }> = {
  ok: { label: 'Done', color: '#3e8635' },
  running: { label: 'Running', color: '#c58c00' },
  failed: { label: 'Failed', color: '#c9190b' },
};

const JobsCard: React.FC<{ days: string; onView: (v: View) => void }> = ({ days, onView }) => {
  const [filter, setFilter] = useState<'' | 'running' | 'ok' | 'failed'>('');
  const { data, error, loading, reload } = useApi<OperationsResponse>(() => api.operations({ days: Number(days), status: filter || undefined }), [days, filter], 15000);
  const items = (data?.items ?? []).slice(0, 6);
  return (
    <section className="card">
      <div className="card-head">
        <h3>Background jobs</h3>
        <span className="sm job-filter">
          {([
            ['', 'Any'],
            ['running', 'Running'],
            ['ok', 'Done'],
            ['failed', 'Failed'],
          ] as const).map(([v, l], i) => (
            <React.Fragment key={v}>
              {i > 0 && <span className="muted"> · </span>}
              <button type="button" className={`link-btn ${filter === v ? 'on' : ''}`} onClick={() => setFilter(v)}>
                {l}
              </button>
            </React.Fragment>
          ))}
        </span>
      </div>
      {error && !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : loading && !data ? (
        <SkLines lines={4} />
      ) : items.length === 0 ? (
        <Empty compact title="No jobs">Nothing ran in this period{filter ? ' with that status' : ''}.</Empty>
      ) : (
        <table className="tbl mid" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Job</th>
              <th>Started</th>
              <th>Duration</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((j) => {
              const st = STATUS[j.status] ?? STATUS.ok;
              const count = typeof j.detail?.count === 'number' ? (j.detail.count as number) : null;
              return (
                <tr key={j.id}>
                  <td>
                    <span className="mono sm">{j.kind}</span>
                    <span className="muted sm"> · {j.label}</span>
                  </td>
                  <td title={new Date(j.started_at).toLocaleString()}>{timeOrDate(j.started_at)}</td>
                  <td>{j.status === 'running' ? '—' : fmtDur(j.duration_ms)}</td>
                  <td>
                    <span style={{ color: st.color, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <span className="status-dot" />
                      {st.label}
                      {count !== null && j.status === 'ok' ? ` · ${fmtInt(count)}` : ''}
                    </span>
                    {j.status === 'failed' && (
                      <>
                        {' '}
                        <button type="button" className="link-btn" onClick={() => onView('errors')}>
                          show run
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div style={{ marginTop: 10 }}>
        <button type="button" className="link-btn" onClick={() => onView('jobs')}>
          All background jobs →
        </button>
      </div>
    </section>
  );
};

const Indexing: React.FC<{ days: string }> = ({ days }) => {
  const settings = useApi(() => api.settings(), []);
  const ov = useApi(() => api.overview('7d'), []);
  const health = useApi<SearchHealth>(() => api.searchHealth(Number(days)), [days]);
  const jobs = useApi<OperationsResponse>(() => api.operations({ days: Number(days) }), [days]);
  const g = ov.data?.governance;
  const models = settings.data?.models;
  const r = settings.data?.values.retrieval;
  const idxKinds = (jobs.data?.kinds ?? []).filter((k) => /embed|index|reindex|vector|rerank/i.test(`${k.kind} ${k.label}`));
  const statusColor = (s?: string) => (s === 'healthy' ? '#3e8635' : s === 'degraded' ? '#c58c00' : s === 'down' ? '#c9190b' : '#6a6e73');
  return (
    <div className="body">
      <div className="row-wrap">
        <div className="col-main">
          <section className="card">
            <h3>Models</h3>
            {settings.error && !settings.data ? (
              <ErrorState error={settings.error} onRetry={settings.reload} />
            ) : !models ? (
              <SkLines lines={4} />
            ) : (
              <table className="tbl mid" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Latency</th>
                    <th>Endpoint</th>
                  </tr>
                </thead>
                <tbody>
                  {([
                    ['Embedding', models.embedding],
                    ['Reranker', models.reranker],
                  ] as const).map(([label, m]) => (
                    <tr key={label}>
                      <td>
                        <b>{label}</b>
                        {m?.name && <div className="sm muted">{m.name}</div>}
                      </td>
                      <td>
                        <span style={{ color: statusColor(m?.status), display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <span className="status-dot" />
                          {(m?.status ?? 'unknown').replace('_', ' ')}
                        </span>
                        {m?.detail && <div className="sm muted">{m.detail}</div>}
                      </td>
                      <td>{ms(m?.latency_ms)}</td>
                      <td className="mono sm" style={{ wordBreak: 'break-all' }}>{m?.url ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section className="card">
            <h3>Indexing jobs · {days === '1' ? '24 h' : `${days} d`}</h3>
            {jobs.loading && !jobs.data ? (
              <SkLines lines={3} />
            ) : idxKinds.length === 0 ? (
              <p className="sm muted" style={{ marginTop: 10 }}>No embedding or re-indexing jobs ran in this period.</p>
            ) : (
              <table className="tbl mid" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Done</th>
                    <th>Running</th>
                    <th>Failed</th>
                    <th>p95</th>
                  </tr>
                </thead>
                <tbody>
                  {idxKinds.map((k) => (
                    <tr key={k.kind}>
                      <td>
                        <span className="mono sm">{k.kind}</span> <span className="muted sm">· {k.label}</span>
                      </td>
                      <td>{fmtInt(k.ok)}</td>
                      <td>{fmtInt(k.running)}</td>
                      <td className={k.failed ? 'err' : ''}>{fmtInt(k.failed)}</td>
                      <td>{fmtDur(k.p95_ms ?? null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
        <aside className="col-side">
          <section className="card">
            <h3>Index</h3>
            <dl className="kv" style={{ marginTop: 14 }}>
              <dt>Indexing backlog</dt>
              <dd>{g?.indexing_backlog !== undefined ? `${fmtInt(g.indexing_backlog)}${g.indexing_failed ? ` · ${fmtInt(g.indexing_failed)} failed` : ''}` : health.data?.index_backlog !== undefined ? fmtInt(health.data.index_backlog) : '—'}</dd>
              <dt>Vector share</dt>
              <dd>{pct(health.data?.share?.vector ?? health.data?.vector_share)}</dd>
              <dt>Stale-result attempts</dt>
              <dd>{health.data?.stale_filtered !== undefined ? fmtInt(health.data.stale_filtered) : '—'}</dd>
            </dl>
          </section>
          <section className="card">
            <h3>Reranker settings</h3>
            {!r ? (
              <SkLines lines={3} />
            ) : (
              <dl className="kv" style={{ marginTop: 14 }}>
                <dt>Rerank</dt>
                <dd>{r.rerank ? 'On' : 'Off'}</dd>
                <dt>Max results</dt>
                <dd>{r.max_results}</dd>
                <dt>Full-content threshold</dt>
                <dd>{r.full_content_threshold}</dd>
                <dt>Session focus weight</dt>
                <dd>{r.session_focus_weight}</dd>
                <dt>Cache-friendly ordering</dt>
                <dd>{r.cache_optimized_ordering ? 'On' : 'Off'}</dd>
              </dl>
            )}
            <a className="sm" href={buildHash('/settings')} style={{ display: 'inline-block', marginTop: 12 }}>
              Change in Tenant settings
            </a>
            {settings.data?.meta.updated_at && <div className="sm muted" style={{ marginTop: 4 }}>Last changed {fmtRelative(settings.data.meta.updated_at)}</div>}
          </section>
        </aside>
      </div>
    </div>
  );
};

export default RetrievalOps;
