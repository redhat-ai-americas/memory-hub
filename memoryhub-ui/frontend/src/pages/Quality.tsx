import React, { useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { ConfirmModal, memoryHref } from './common';
import { Empty, ErrorState, Seg, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CheckResult, CheckRun, ChecksOverview, SavedQuery, SearchHealth } from '@/types';
import { errorMessage, fmtInt, fmtRelative, truncate } from '@/utils/format';

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
const STAGE: Record<string, string> = {
  filters: 'filtered out',
  rbac: 'outside access',
  weight: 'below weight threshold',
  limit: 'beyond max results',
  budget: 'token budget',
  matched: 'not a top match',
  missing: 'not found',
  deleted: 'deleted',
};

/**
 * Retrieval quality. Users: retrieval checks (saved queries with the memories
 * they should return), runs and their comparison. Platform admins: retrieval
 * health — counts and timings of every search run, never queries or content.
 */
const Quality: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { role } = useApp();
  const tab = route.params.get('tab') || (role === 'admin' ? 'health' : 'checks');
  const setTab = (t: string) => navigate('/quality', t === 'checks' ? undefined : { tab: t }, { replace: true });
  return (
    <>
      <PageHeader
        title={role === 'admin' ? 'Retrieval health' : 'Retrieval checks'}
        description={
          role === 'admin'
            ? 'How search behaves across the tenant: how many memories match, where they are cut, how long it takes. Built from counts and timings only — never queries or memory content.'
            : 'Saved queries with the memories they should return. Run them after you change memories, weights or settings, and see what broke — and why each missing memory did not come back.'
        }
        tabs={
          role === 'admin' ? undefined : (
            <Tabs
              label="Retrieval quality"
              value={tab}
              onChange={setTab}
              tabs={[
                { value: 'checks', label: 'Checks' },
                { value: 'runs', label: 'Runs' },
                { value: 'health', label: 'My search health' },
              ]}
            />
          )
        }
      />
      <div className="body">{tab === 'health' || role === 'admin' ? <Health /> : tab === 'runs' ? <Runs /> : <Checks />}</div>
    </>
  );
};

const Metric: React.FC<{ label: string; value: string; hint?: string }> = ({ label, value, hint }) => (
  <div>
    <div className="statv">{value}</div>
    <div className="hint">
      {label}
      {hint ? ` · ${hint}` : ''}
    </div>
  </div>
);

const Checks: React.FC = () => {
  const toast = useToast();
  const { refreshCounts } = useApp();
  const { data, error, loading, reload, setData } = useApi<ChecksOverview>(() => api.checks(), []);
  const [busy, setBusy] = useState(false);
  const [del, setDel] = useState<SavedQuery | null>(null);
  const run = async (ids?: string[]) => {
    setBusy(true);
    try {
      const r = await api.runChecks(ids);
      toast(`Checks ran: recall ${pct(r.summary.recall)}, ${r.summary.failing ?? 0} failing.`);
      reload();
      refreshCounts();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (loading && !data)
    return (
      <div className="card">
        <SkLines lines={8} />
      </div>
    );
  if (!data) return null;
  const last = data.last;
  const byQuery = Object.fromEntries((last?.results ?? []).map((r) => [r.query_id, r]));
  return (
    <>
      {data.checks.length === 0 ? (
        <div className="card">
          <Empty
            title="No retrieval checks yet"
            action={
              <a className="btn bp" href={buildHash('/search')}>
                Open Search playground
              </a>
            }
          >
            Save a query in the Search playground and mark the memories it should return with ☆. It becomes a check here.
          </Empty>
        </div>
      ) : (
        <>
          <section className="card">
            <div className="ch">
              <h3>Last run {last ? `· ${fmtRelative(last.started_at).toLowerCase()}` : ''}</h3>
              <button type="button" className="btn bp" disabled={busy} onClick={() => run()}>
                {busy ? 'Running…' : data.checks.length === 1 ? 'Run the check' : `Run all ${data.checks.length} checks`}
              </button>
            </div>
            {last ? (
              <div className="stats4" style={{ marginTop: 6 }}>
                <Metric label="hit rate" value={pct(last.summary.hit_rate)} hint="≥ 1 expected back" />
                <Metric label="recall" value={pct(last.summary.recall)} />
                <Metric label="precision" value={pct(last.summary.precision)} />
                <Metric label="MRR" value={last.summary.mrr?.toFixed(2) ?? '—'} />
                <Metric label="failing" value={String(last.summary.failing ?? 0)} />
                <Metric label="median time" value={`${Math.round(last.summary.p50_ms ?? 0)} ms`} />
              </div>
            ) : (
              <p className="sm muted">Not run yet. The scheduler also runs your checks once a day.</p>
            )}
          </section>
          <section className="card" style={{ padding: 0 }}>
            <div className="scroll">
              <table className="tbl mid">
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Expected</th>
                    <th>Recall</th>
                    <th>First hit</th>
                    <th>Why missing</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.checks.map((q) => {
                    const r: CheckResult | undefined = byQuery[q.id];
                    const m = r?.metrics ?? q.last_result;
                    return (
                      <tr key={q.id}>
                        <td style={{ maxWidth: 320 }}>
                          <div className="b6">{q.name}</div>
                          <div className="sm muted ellipsis">“{truncate(q.request.query, 80)}”</div>
                          {!q.mine && <div className="hint">shared by {q.owner}</div>}
                        </td>
                        <td>{q.expected.length}</td>
                        <td>
                          {m ? (
                            <span className={`lbl ${m.recall === 1 ? 'grn' : m.hit ? 'ylw' : 'red'}`}>
                              {pct(m.recall)} · {m.found}/{m.expected}
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="sm">{m?.first_rank ? `#${m.first_rank}` : '—'}</td>
                        <td className="sm" style={{ maxWidth: 360 }}>
                          {r && r.missing.length ? (
                            r.missing.map((x) => (
                              <div key={x.id}>
                                <a href={memoryHref(x.id)}>{truncate(x.stub ?? x.id, 40)}</a> — <span className="muted">{STAGE[x.stage] ?? x.stage}</span>
                              </div>
                            ))
                          ) : r ? (
                            <span className="ok">all came back</span>
                          ) : (
                            <span className="muted">run to see</span>
                          )}
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <button type="button" className="btn bl sm" disabled={busy} onClick={() => run([q.id])}>
                            Run
                          </button>
                          <a className="btn bl sm" href={buildHash('/search', { saved: q.id })}>
                            Open
                          </a>
                          {q.mine && (
                            <button type="button" className="btn bl sm danger" onClick={() => setDel(q)}>
                              Delete
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      {data.queries.length > 0 && (
        <section className="card">
          <h3>Saved queries without expectations</h3>
          <p className="sm muted" style={{ margin: '4px 0 10px' }}>
            Open one in the playground and mark the memories it should return to turn it into a check.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {data.queries.map((q) => (
              <a key={q.id} className="conn link-plain" href={buildHash('/search', { saved: q.id })}>
                <span className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
                  {q.name}
                </span>
                <span className="hint">{q.mine ? (q.visibility === 'project' ? `shared · ${q.project}` : 'only you') : `by ${q.owner}`}</span>
              </a>
            ))}
          </div>
        </section>
      )}
      {del && (
        <ConfirmModal
          title="Delete this saved query?"
          confirmLabel="Delete"
          danger
          onClose={() => setDel(null)}
          onConfirm={async () => {
            await api.deleteSavedQuery(del.id);
            setData({ ...data, checks: data.checks.filter((c) => c.id !== del.id), queries: data.queries.filter((c) => c.id !== del.id) });
            refreshCounts();
          }}
        >
          “{del.name}” and its expected memories are removed. Past runs stay.
        </ConfirmModal>
      )}
    </>
  );
};

const Runs: React.FC = () => {
  const { data, error, loading, reload } = useApi<ChecksOverview>(() => api.checks(), []);
  const [pick, setPick] = useState<string[]>([]);
  const [runs, setRuns] = useState<Record<string, CheckRun>>({});
  const load = async (id: string) => {
    if (!runs[id]) {
      const r = await api.checkRun(id);
      setRuns((x) => ({ ...x, [id]: r }));
    }
  };
  const toggle = (id: string) => {
    const next = pick.includes(id) ? pick.filter((x) => x !== id) : [...pick, id].slice(-2);
    setPick(next);
    next.forEach((x) => void load(x));
  };
  const [a, b] = pick.map((id) => runs[id]).sort((x, y) => (x && y ? x.started_at.localeCompare(y.started_at) : 0));
  const rows = useMemo(() => {
    if (!a?.results || !b?.results) return [];
    const ids = [...new Set([...a.results.map((r) => r.query_id), ...b.results.map((r) => r.query_id)])];
    return ids.map((id) => ({
      id,
      name: (b.results!.find((r) => r.query_id === id) ?? a.results!.find((r) => r.query_id === id))!.name,
      before: a.results!.find((r) => r.query_id === id)?.metrics.recall ?? null,
      after: b.results!.find((r) => r.query_id === id)?.metrics.recall ?? null,
    }));
  }, [a, b]);
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (loading && !data)
    return (
      <div className="card">
        <SkLines lines={6} />
      </div>
    );
  if (!data?.runs.length)
    return (
      <div className="card">
        <Empty title="No runs yet">Run your checks from the Checks tab; the scheduler also runs them daily.</Empty>
      </div>
    );
  return (
    <div className="row-wrap">
      <section className="card col-main" style={{ padding: 0 }}>
        <div className="ch" style={{ padding: '18px 20px 0' }}>
          <h3>Runs</h3>
          <span className="sm muted">Pick two to compare</span>
        </div>
        <table className="tbl mid">
          <thead>
            <tr>
              <th />
              <th>When</th>
              <th>Trigger</th>
              <th>Checks</th>
              <th>Recall</th>
              <th>Hit rate</th>
              <th>MRR</th>
              <th>Failing</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((r) => (
              <tr key={r.id} className={pick.includes(r.id) ? 'is-sel' : ''}>
                <td>
                  <input type="checkbox" aria-label="Compare this run" checked={pick.includes(r.id)} onChange={() => toggle(r.id)} />
                </td>
                <td className="sm">{fmtRelative(r.started_at)}</td>
                <td className="sm">{r.trigger}</td>
                <td>{r.summary.checks}</td>
                <td>{pct(r.summary.recall)}</td>
                <td>{pct(r.summary.hit_rate)}</td>
                <td>{r.summary.mrr?.toFixed(2) ?? '—'}</td>
                <td>{r.summary.failing ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <aside className="card col-side">
        <h3>Compare</h3>
        {rows.length === 0 ? (
          <p className="sm muted">Tick two runs to see which checks got better or worse.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
            <div className="sm muted">
              {fmtRelative(a!.started_at)} → {fmtRelative(b!.started_at)}
            </div>
            {rows.map((r) => {
              const d = r.before !== null && r.after !== null ? r.after - r.before : null;
              return (
                <div key={r.id} className="cmp-row">
                  <span className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
                    {r.name}
                  </span>
                  <span className="sm">
                    {pct(r.before)} → <b>{pct(r.after)}</b>
                  </span>
                  {d !== null && d !== 0 && <span className={`sm ${d > 0 ? 'ok' : 'err'}`}>{d > 0 ? '▲' : '▼'}</span>}
                </div>
              );
            })}
          </div>
        )}
      </aside>
    </div>
  );
};

const CUT_LABEL: Record<string, string> = {
  filters: 'Version / branch / status filters',
  rbac: 'Access (RBAC)',
  weight: 'Weight threshold',
  limit: 'Max results',
  budget: 'Token budget',
};

const Health: React.FC = () => {
  const { role } = useApp();
  const [days, setDays] = useState('7');
  const { data, error, loading, reload } = useApi<SearchHealth>(() => api.searchHealth(Number(days)), [days]);
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span className="sm muted">
          {data?.scope === 'tenant' ? 'All search runs in the tenant (playground, checks, context packs).' : 'Your search runs (playground, checks, context packs).'} Agent
          searches through MCP are not traced here.
        </span>
        <Seg
          label="Period"
          value={days}
          onChange={setDays}
          options={[
            { value: '1', label: '24 h' },
            { value: '7', label: '7 d' },
            { value: '30', label: '30 d' },
          ]}
        />
      </div>
      {loading && !data ? (
        <div className="card">
          <SkLines lines={6} />
        </div>
      ) : !data || data.runs === 0 ? (
        <div className="card">
          <Empty title="No search runs in this period">{role === 'admin' ? 'Runs appear as users use the Search playground, retrieval checks and context packs.' : 'Run a search in the playground.'}</Empty>
        </div>
      ) : (
        <div className="row-wrap">
          <div className="col-main">
            <section className="card">
              <div className="stats4">
                <Metric label="search runs" value={fmtInt(data.runs)} />
                <Metric label="median latency" value={`${Math.round(data.latency?.p50 ?? 0)} ms`} hint={`p95 ${Math.round(data.latency?.p95 ?? 0)} ms`} />
                <Metric label="matched on average" value={String(data.avg?.matched ?? 0)} />
                <Metric label="returned on average" value={String(data.avg?.returned ?? 0)} />
                <Metric label="came back empty" value={pct(data.empty_share)} />
                <Metric label="vector search" value={pct(data.vector_share)} hint="rest fell back to full text" />
              </div>
            </section>
            <section className="card">
              <h3>Where matches are cut</h3>
              <p className="sm muted" style={{ margin: '4px 0 12px' }}>
                Share of all matched memories that each stage dropped.
              </p>
              <div className="funnel">
                {Object.entries(data.cut ?? {}).map(([k, v]) => (
                  <div key={k} className="fstep static">
                    <span className="fl">{CUT_LABEL[k] ?? k}</span>
                    <span className="fbar">
                      <i style={{ width: `${Math.max(1, v * 100)}%`, background: '#ca6c0f' }} />
                    </span>
                    <span className="fn">
                      <b>{pct(v)}</b>
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </div>
          <aside className="col-side">
            <section className="card">
              <h3>Stage time (median)</h3>
              <dl className="dl" style={{ marginTop: 12 }}>
                {(data.stages ?? []).map((s) => (
                  <React.Fragment key={s.name}>
                    <dt>{s.name}</dt>
                    <dd>{s.p50 < 1 ? '<1' : Math.round(s.p50)} ms</dd>
                  </React.Fragment>
                ))}
              </dl>
            </section>
            <section className="card">
              <h3>Sources &amp; reranker</h3>
              <dl className="dl" style={{ marginTop: 12 }}>
                {Object.entries(data.sources ?? {}).map(([k, v]) => (
                  <React.Fragment key={k}>
                    <dt>{k}</dt>
                    <dd>{fmtInt(v)}</dd>
                  </React.Fragment>
                ))}
                {Object.entries(data.rerank ?? {}).map(([k, v]) => (
                  <React.Fragment key={`r${k}`}>
                    <dt>rerank {k.replace('_', ' ')}</dt>
                    <dd>{fmtInt(v)}</dd>
                  </React.Fragment>
                ))}
              </dl>
            </section>
          </aside>
        </div>
      )}
    </>
  );
};

export default Quality;
