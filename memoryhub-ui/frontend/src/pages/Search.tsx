import React, { useEffect, useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { copyText, Dropdown, Empty, ErrorState, Icon, Modal, ScopeLabel, Seg, SkLines, Standby, Tokens, useToast } from '@/components/ui';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { DroppedMemory, ExplainResult, FunnelKey, SavedQuery, SearchRequest, SearchResponse } from '@/types';
import { errorMessage, shortId, truncate } from '@/utils/format';
import { MemoryPicker, memoryHref } from './common';

const ENTITY_ICON: Record<string, { color: string; d: string; label: string }> = {
  person: { label: 'Person', color: '#0066cc', d: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c1.5-4 4.5-6 8-6s6.5 2 8 6' },
  organization: { label: 'Organization', color: '#3d7317', d: 'M4 21V5l8-3v19M12 9h8v12M3 21h18' },
  location: { label: 'Location', color: '#009596', d: 'M12 21s-7-6.5-7-11a7 7 0 0114 0c0 4.5-7 11-7 11z' },
  object: { label: 'Object', color: '#ca6c0f', d: 'M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10' },
  event: { label: 'Event', color: '#5e40be', d: 'M5 5h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2zM3 10h18' },
};

const EntityGlyph: React.FC<{ type: string }> = ({ type }) => {
  const t = ENTITY_ICON[type] ?? ENTITY_ICON.object;
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={t.color} strokeWidth="2.2" aria-hidden="true" style={{ flex: 'none' }}>
      <path d={t.d} />
    </svg>
  );
};

/** Session focus picked from extracted entities instead of free text. */
const EntityFocusSelect: React.FC<{ value: string; onChange: (v: string) => void }> = ({ value, onChange }) => {
  const [q, setQ] = useState('');
  const [items, setItems] = useState<{ id: string; name: string; entity_type: string; memory_count: number }[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => {
      api
        .entities({ q: q.trim() || undefined, per_page: 30 })
        .then((r) => {
          setItems(r.items);
          setFailed(false);
        })
        .catch(() => setFailed(true));
    }, 200);
    return () => window.clearTimeout(t);
  }, [q]);
  const current = items?.find((i) => i.name === value);
  return (
    <Dropdown
      style={{ width: '100%' }}
      toggle={(p) => (
        <button type="button" className="sel" aria-labelledby="fo-l" aria-haspopup="listbox" style={{ width: '100%', justifyContent: 'space-between' }} {...p}>
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', minWidth: 0 }}>
            {value ? (
              <>
                <EntityGlyph type={current?.entity_type ?? 'object'} />
                <span className="ellipsis">{value}</span>
              </>
            ) : (
              <span className="muted">No session focus</span>
            )}
          </span>
          <Icon.Chevron />
        </button>
      )}
    >
      {(close) => (
        <div style={{ width: 340, maxWidth: '80vw' }} role="listbox" aria-label="Entities">
          <div style={{ padding: '6px 12px 8px' }}>
            <label className="vh" htmlFor="fo-q">
              Search entities
            </label>
            <input id="fo-q" className="in" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search entities" />
          </div>
          <button
            type="button"
            role="option"
            aria-selected={!value}
            onClick={() => {
              onChange('');
              close();
            }}
          >
            <span className="muted">No session focus</span>
          </button>
          <hr />
          <div style={{ maxHeight: 280, overflowY: 'auto' }}>
            {failed && <div className="mh">Entities are not available.</div>}
            {!failed && items === null && <div className="mh">Loading…</div>}
            {items?.length === 0 && <div className="mh">No entities match.</div>}
            {items?.map((e) => (
              <button
                key={e.id}
                type="button"
                role="option"
                aria-selected={e.name === value}
                style={e.name === value ? { fontWeight: 600, background: '#f5f9fc' } : undefined}
                onClick={() => {
                  onChange(e.name);
                  close();
                }}
              >
                <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <EntityGlyph type={e.entity_type} />
                  <span className="ellipsis" style={{ flex: 1 }}>
                    {e.name}
                  </span>
                  <span className="hint">
                    {ENTITY_ICON[e.entity_type]?.label ?? e.entity_type} · {e.memory_count}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </Dropdown>
  );
};

const STAGE_COLORS: Record<string, string> = {
  embed: '#004d99',
  pgvector: '#0066cc',
  'full-text': '#0066cc',
  rbac: '#383838',
  focus: '#009596',
  rrf: '#5e40be',
  rerank: '#8f4700',
  assemble: '#3d7317',
};
const SAVED_KEY = 'memoryhub.search.saved';

interface Form extends SearchRequest {}

const sdkCall = (f: Form) =>
  [
    'results = await client.search(',
    `    ${JSON.stringify(f.query)},`,
    f.focus ? `    focus=${JSON.stringify(f.focus)},` : null,
    f.focus ? `    session_focus_weight=${f.session_focus_weight},` : null,
    f.project ? `    project_id=${JSON.stringify(f.project)},` : null,
    `    max_results=${f.max_results},`,
    `    mode=${JSON.stringify(f.mode)},`,
    f.weight_threshold ? `    weight_threshold=${f.weight_threshold},` : null,
    `    max_response_tokens=${f.max_response_tokens},`,
    f.include_branches ? '    include_branches=True,' : null,
    ')',
  ]
    .filter(Boolean)
    .join('\n');

const readSaved = (): Form[] => {
  try {
    return JSON.parse(window.localStorage.getItem(SAVED_KEY) || '[]') as Form[];
  } catch {
    return [];
  }
};

const Search: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { standby, me, refreshCounts } = useApp();
  const [form, setForm] = useState<Form>({
    query: route.params.get('q') || '',
    focus: '',
    identity: '',
    project: '',
    mode: 'full',
    max_results: 10,
    session_focus_weight: 0.4,
    weight_threshold: 0,
    max_response_tokens: 4000,
    current_only: true,
    include_branches: false,
    rerank: true,
  });
  const [identities, setIdentities] = useState<{ id: string; label: string }[]>([]);
  const [projects, setProjects] = useState<string[]>([]);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState<'ranked' | 'dropped' | 'context' | 'json'>('ranked');
  const [legacy, setLegacy] = useState<Form[]>(readSaved);
  const [saved, setSaved] = useState<SavedQuery[]>([]);
  const [loaded, setLoaded] = useState<SavedQuery | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [why, setWhy] = useState<ExplainResult[]>([]);
  const [whyOpen, setWhyOpen] = useState(false);
  const [compareB, setCompareB] = useState<Form | null>(null);
  const [resultB, setResultB] = useState<SearchResponse | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [dropStage, setDropStage] = useState<FunnelKey | 'all'>('all');
  const loadSaved = () =>
    api
      .savedQueries()
      .then((r) => setSaved(r.items))
      .catch(() => undefined);
  useEffect(() => {
    void loadSaved().then(() => undefined);
  }, []);
  // ?saved=<id> opens a saved query (from Retrieval checks) and runs it.
  const savedParam = route.params.get('saved');
  useEffect(() => {
    if (!savedParam) return;
    api
      .savedQueries()
      .then(({ items }) => {
        const q = items.find((i) => i.id === savedParam);
        if (!q) return;
        const f = { ...form, ...q.request } as Form;
        setForm(f);
        setLoaded(q);
        void run(f, q.expected);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedParam]);

  useEffect(() => {
    api
      .settings()
      .then((s) =>
        setForm((f) => ({
          ...f,
          max_results: s.values.retrieval.max_results,
          max_response_tokens: s.values.retrieval.max_response_tokens,
          session_focus_weight: s.values.retrieval.session_focus_weight,
          rerank: s.values.retrieval.rerank,
        })),
      )
      .catch(() => undefined);
    api
      .identities()
      .then((r) =>
        setIdentities(
          r.items.map((i) => ({
            id: i.id,
            label: `${i.name}${i.bound_to ? ` · ${i.bound_to}` : ''} (${i.type})`,
          })),
        ),
      )
      .catch(() => undefined);
    api
      .projects(false)
      .then((r) => setProjects(r.items.map((p) => p.name)))
      .catch(() => undefined);
  }, []);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));

  const clean = (body: Form, explain: string[] = []): SearchRequest => ({
    ...body,
    focus: body.focus?.trim() || undefined,
    identity: body.identity?.trim() || undefined,
    project: body.project?.trim() || undefined,
    explain,
  });
  const run = async (override?: Form, explainIds?: string[]) => {
    const body = override ?? form;
    if (!body.query.trim()) return;
    setRunning(true);
    setError(null);
    setExpanded(false);
    try {
      const ids = explainIds ?? why.map((w) => w.id);
      const res = await api.search(clean(body, ids));
      setResult(res);
      setWhy(res.explain ?? []);
      if (compareB) setResultB(await api.search(clean({ ...compareB, query: compareB.query || body.query })));
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setRunning(false);
    }
  };

  const moveLegacy = async () => {
    try {
      for (const f of legacy) await api.createSavedQuery({ name: truncate(f.query, 60), request: clean(f) });
      window.localStorage.removeItem(SAVED_KEY);
      setLegacy([]);
      toast(`${legacy.length} saved ${legacy.length === 1 ? 'query' : 'queries'} moved to your account.`);
      void loadSaved();
      refreshCounts();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };

  const toggleExpected = async (id: string) => {
    if (!loaded || !loaded.mine) return;
    const next = loaded.expected.includes(id) ? loaded.expected.filter((x) => x !== id) : [...loaded.expected, id];
    try {
      await api.updateSavedQuery(loaded.id, { expected: next });
      setLoaded({ ...loaded, expected: next, is_check: next.length > 0 });
      void loadSaved();
      refreshCounts();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };

  const saveAsPack = async () => {
    try {
      const res = await api.createPack({
        name: truncate(form.query, 60),
        queries: [{ query: form.query, max_results: Math.min(form.max_results, 10), weight_threshold: form.weight_threshold, project: form.project || null }],
        token_budget: Math.min(form.max_response_tokens, 4000),
      });
      refreshCounts();
      navigate(`/knowledge/packs/${res.id}`);
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };

  const copySdk = async () => toast((await copyText(sdkCall(form))) ? 'SDK call copied.' : 'Copy failed — select the text instead.', 'ok');
  const results = result?.results ?? [];
  // Show every rank up to the last full result (at least five), then fold
  // the trailing stubs into the dashed "+N stub results" row.
  const lastFull = Math.max(5, ...results.filter((r) => r.delivery === 'full').map((r) => r.rank));
  const shownRanked = expanded ? results : results.filter((r) => r.rank <= lastFull);
  const hiddenStubs = results.length - shownRanked.length;
  const totalMs = result ? Math.max(1, result.stages.reduce((a, s) => a + s.ms, 0)) : 1;

  return (
    <>
      <PageHeader
        title="Search playground"
        description={
          <>
            Run <span className="mono">search_memory</span> exactly as an agent would — same RBAC, same two-vector retrieval — and see why each result ranked
            where it did.
          </>
        }
        actions={
          <>
            <Dropdown
              align="right"
              toggle={(p) => (
                <button type="button" className="btn bg" {...p}>
                  Saved queries
                </button>
              )}
            >
              {(close) => (
                <div style={{ minWidth: 300, maxWidth: 380 }}>
                  <button type="button" disabled={!form.query.trim()} onClick={() => { setSaveOpen(true); close(); }}>
                    Save current query…
                  </button>
                  {legacy.length > 0 && (
                    <button type="button" onClick={() => { void moveLegacy(); close(); }}>
                      Move {legacy.length} browser-saved {legacy.length === 1 ? 'query' : 'queries'} to your account
                    </button>
                  )}
                  {saved.length > 0 && <hr />}
                  {saved.map((q) => (
                    <button
                      key={q.id}
                      type="button"
                      onClick={() => {
                        const f = { ...form, ...q.request } as Form;
                        setForm(f);
                        setLoaded(q);
                        close();
                        void run(f, q.expected);
                      }}
                    >
                      <span style={{ display: 'flex', justifyContent: 'space-between', gap: 10, width: '100%' }}>
                        <span className="ellipsis">{q.name}</span>
                        <span className="hint" style={{ whiteSpace: 'nowrap' }}>
                          {q.is_check ? `check · ${q.expected.length}` : ''}
                          {!q.mine ? ` ${q.owner}` : ''}
                        </span>
                      </span>
                    </button>
                  ))}
                  {saved.length === 0 && <div className="mh">No saved queries yet</div>}
                </div>
              )}
            </Dropdown>
            <button type="button" className="btn bs" onClick={copySdk}>
              Copy as SDK call
            </button>
          </>
        }
      />
      <div className="body">
        <div className="row-wrap">
          <form
            className="card"
            style={{ flex: '1 1 320px', display: 'flex', flexDirection: 'column', gap: 18 }}
            onSubmit={(e) => {
              e.preventDefault();
              void run();
            }}
          >
            <h3>Query</h3>
            <div className="f">
              <label htmlFor="q">Query</label>
              <textarea id="q" className="in" required value={form.query} onChange={(e) => set('query', e.target.value)} placeholder="how should I run containers locally for this repo?" />
            </div>
            <div className="f">
              <span className="lbl-t" id="fo-l">
                Session focus
              </span>
              <EntityFocusSelect value={form.focus ?? ''} onChange={(v) => set('focus', v)} />
              <span className="hint">Pick an entity the session is about. Blended with the query via reciprocal-rank fusion.</span>
            </div>
            <div className="f">
              <label htmlFor="as">Run as identity</label>
              <input id="as" className="in" list="identity-list" value={form.identity} onChange={(e) => set('identity', e.target.value)} placeholder={`Dashboard (${me?.username ?? 'admin'}) — no RBAC filter`} />
              <datalist id="identity-list">
                {identities.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.label}
                  </option>
                ))}
              </datalist>
              <span className="hint">Results are filtered by this identity’s scopes and memberships.</span>
            </div>
            <div className="f">
              <label htmlFor="pj">Project context</label>
              <input id="pj" className="in" list="project-list" value={form.project} onChange={(e) => set('project', e.target.value)} />
              <datalist id="project-list">
                {projects.map((p) => (
                  <option key={p} value={p} />
                ))}
              </datalist>
            </div>
            <div className="f">
              <label>Response mode</label>
              <Seg
                label="Response mode"
                value={form.mode}
                onChange={(v) => set('mode', v)}
                options={[
                  { value: 'full', label: 'full' },
                  { value: 'index', label: 'index' },
                  { value: 'full_only', label: 'full_only' },
                ]}
              />
            </div>
            <div className="f">
              <label htmlFor="mr">Max results · {form.max_results}</label>
              <input id="mr" type="range" min={1} max={50} value={form.max_results} onChange={(e) => set('max_results', Number(e.target.value))} />
            </div>
            <div className="f">
              <label htmlFor="fw">Session focus weight · {form.session_focus_weight.toFixed(2)}</label>
              <input id="fw" type="range" min={0} max={100} value={Math.round(form.session_focus_weight * 100)} onChange={(e) => set('session_focus_weight', Number(e.target.value) / 100)} />
            </div>
            <div className="f">
              <label htmlFor="wt">Weight threshold · {form.weight_threshold.toFixed(2)}</label>
              <input id="wt" type="range" min={0} max={100} value={Math.round(form.weight_threshold * 100)} onChange={(e) => set('weight_threshold', Number(e.target.value) / 100)} />
            </div>
            <div className="f">
              <label htmlFor="tk">Max response tokens</label>
              <input id="tk" className="in" type="number" min={100} max={100000} value={form.max_response_tokens} onChange={(e) => set('max_response_tokens', Number(e.target.value) || 4000)} />
            </div>
            <label className="swrow">
              <span>Current versions only</span>
              <input type="checkbox" checked={form.current_only} onChange={(e) => set('current_only', e.target.checked)} />
            </label>
            <label className="swrow">
              <span>Include branches</span>
              <input type="checkbox" checked={form.include_branches} onChange={(e) => set('include_branches', e.target.checked)} />
            </label>
            <label className="swrow">
              <span>Cross-encoder rerank</span>
              <input type="checkbox" checked={form.rerank} onChange={(e) => set('rerank', e.target.checked)} />
            </label>
            <button type="submit" className="btn bp" style={{ justifyContent: 'center' }} disabled={running || standby || !form.query.trim()}>
              {running ? 'Running…' : 'Run search'}
            </button>
            {standby && <span className="hint">Searching starts once the tenant has its first memory.</span>}
          </form>

          <div className="col-main">
            {standby ? (
              <div className="card">
                <Standby compact={false}>
                  Pipeline timing, per-stage scores and the exact context an agent would receive appear here once there is something to search.
                </Standby>
              </div>
            ) : error ? (
              <div className="card">
                <ErrorState error={error} onRetry={() => void run()} title="The search failed" />
              </div>
            ) : !result && !running ? (
              <div className="card">
                <Empty title="Run a search">
                  Enter a query and choose who to run it as. You will see each pipeline stage’s timing and why every result ranked where it did.
                </Empty>
              </div>
            ) : running && !result ? (
              <>
                <div className="card">
                  <SkLines lines={2} />
                </div>
                <div className="card">
                  <SkLines lines={8} />
                </div>
              </>
            ) : (
              result && (
                <>
                  <div className="card">
                    <div className="ch">
                      <h3>Pipeline · {Math.round(result.total_ms)} ms</h3>
                      <span className="sm muted">
                        {result.returned} returned · {result.full_count} full · {result.stub_count} stubs · <Tokens n={result.tokens} /> ·{' '}
                        {result.omitted_count} filtered by RBAC
                      </span>
                    </div>
                    <div className="pipe" role="img" aria-label={result.stages.map((s) => `${s.name} ${s.ms} ms`).join(', ')}>
                      {result.stages.map((s) => (
                        <div key={s.name} style={{ flex: Math.max(s.ms, 0.5), background: STAGE_COLORS[s.name] ?? '#8a8d90' }} title={`${s.name} ${s.ms} ms`}>
                          {s.ms / totalMs > 0.12 ? `${s.name} · ${Math.round(s.ms)} ms` : s.ms / totalMs > 0.06 ? s.name : ''}
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, fontSize: 12, marginTop: 10 }} className="muted">
                      {result.stages.map((s) => (
                        <span key={s.name}>
                          {s.name}
                          {s.detail ? ` ${s.detail}` : ''} {s.ms < 1 ? '<1' : Math.round(s.ms)} ms
                        </span>
                      ))}
                      {result.rerank === 'not_configured' && <span>rerank not configured</span>}
                      {result.rerank === 'unavailable' && <span className="warn">reranker unavailable</span>}
                      <span>run as {result.run_as}</span>
                    </div>
                  </div>

                  {loaded && (
                    <div className="alert" role="status">
                      <div style={{ flex: 1 }}>
                        <b>{loaded.name}</b> · saved query{loaded.mine ? '' : ` by ${loaded.owner}`}
                        {loaded.is_check ? (
                          <>
                            {' '}
                            · retrieval check with {loaded.expected.length} expected{' '}
                            {loaded.expected.length === 1 ? 'memory' : 'memories'} ({results.filter((r) => loaded.expected.includes(r.id)).length} came back).
                          </>
                        ) : loaded.mine && me?.labs ? (
                          ' · mark the memories it should return (☆) to turn it into a retrieval check.'
                        ) : (
                          '.'
                        )}
                      </div>
                      <span style={{ display: 'flex', gap: 10 }}>
                        {loaded.is_check && (
                          <a href={buildHash('/quality')} className="sm" style={{ whiteSpace: 'nowrap' }}>
                            Retrieval checks
                          </a>
                        )}
                        <button type="button" className="link-btn sm" onClick={() => setLoaded(null)}>
                          Close
                        </button>
                      </span>
                    </div>
                  )}

                  {result.funnel && (
                    <Funnel
                      result={result}
                      onStage={(k) => {
                        setDropStage(k);
                        setTab('dropped');
                      }}
                    />
                  )}

                  <WhyNot
                    items={why}
                    open={whyOpen}
                    setOpen={setWhyOpen}
                    onAsk={(id) => void run(undefined, [...why.map((w) => w.id).filter((x) => x !== id), id])}
                    onClear={() => setWhy([])}
                  />

                  {compareB && (
                    <CompareCard
                      a={form}
                      b={compareB}
                      setB={setCompareB}
                      resA={result}
                      resB={resultB}
                      running={running}
                      onRun={() => void run()}
                      onClose={() => {
                        setCompareB(null);
                        setResultB(null);
                      }}
                    />
                  )}

                  <div className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 10, flexWrap: 'wrap' }}>
                      <Tabs
                        inCard
                        label="Result views"
                        value={tab}
                        onChange={setTab}
                        tabs={[
                          { value: 'ranked', label: 'Ranked results', count: results.length },
                          { value: 'dropped', label: 'Didn’t come back', count: (result.dropped?.length ?? 0) + Object.values(result.hidden_dropped ?? {}).reduce((x, y) => x + y, 0) },
                          { value: 'context', label: 'Assembled context' },
                          { value: 'json', label: 'Raw JSON' },
                        ]}
                      />
                      <span style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                        {!compareB && (
                          <button type="button" className="btn bl sm" onClick={() => setCompareB({ ...form })}>
                            Compare settings
                          </button>
                        )}
                        {me?.labs && (
                          <button type="button" className="btn bl sm" onClick={saveAsPack} disabled={!results.length}>
                            Save as context pack
                          </button>
                        )}
                      </span>
                    </div>
                    {tab === 'dropped' && <DroppedList result={result} stage={dropStage} setStage={setDropStage} />}
                    {tab === 'ranked' &&
                      (results.length === 0 ? (
                        <Empty compact title="No results">
                          {result.omitted_count > 0
                            ? `${result.omitted_count} candidate${result.omitted_count === 1 ? '' : 's'} matched but ${result.omitted_count === 1 ? 'is' : 'are'} outside this identity’s access.`
                            : 'Nothing matched this query. Try fewer words or a lower weight threshold.'}
                        </Empty>
                      ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                          {shownRanked.map((r) => (
                            <div className={`res ${loaded?.expected.includes(r.id) ? 'exp' : ''}`} key={r.id}>
                              <span className="rk">{r.rank}</span>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
                                  <ScopeLabel scope={r.scope} />
                                  <span className="lbl g">{expanded ? 'full' : r.delivery}</span>
                                  <span className="sm muted">{r.scope === 'campaign' ? `campaign:${r.scope_id ?? r.owner_id}` : r.scope_id ?? r.owner_id}</span>
                                  {r.downgraded && <span className="lbl ylw">stub · budget</span>}
                                  {loaded?.mine && me?.labs && (
                                    <button
                                      type="button"
                                      className={`star ${loaded.expected.includes(r.id) ? 'on' : ''}`}
                                      aria-pressed={loaded.expected.includes(r.id)}
                                      title={loaded.expected.includes(r.id) ? 'Expected — click to unmark' : 'Mark as a memory this query should return'}
                                      onClick={() => void toggleExpected(r.id)}
                                      style={{ marginLeft: 'auto' }}
                                    >
                                      {loaded.expected.includes(r.id) ? '★ expected' : '☆ expected'}
                                    </button>
                                  )}
                                </div>
                                <a href={memoryHref(r.id)} style={{ fontWeight: 500, textDecoration: 'none', color: '#151515' }}>
                                  {r.delivery === 'full' && r.content ? r.content : truncate(r.stub, 80)}
                                </a>
                                <div className="sc">
                                  {r.scores.vector !== null && (
                                    <span>
                                      vector <b>{r.scores.vector.toFixed(2)}</b>
                                    </span>
                                  )}
                                  {r.scores.text !== null && (
                                    <span>
                                      text <b>{r.scores.text.toFixed(2)}</b>
                                    </span>
                                  )}
                                  {r.scores.focus !== null && (
                                    <span>
                                      focus <b>{r.scores.focus.toFixed(2)}</b>
                                    </span>
                                  )}
                                  <span>
                                    RRF <b>{r.scores.rrf.toFixed(4)}</b>
                                  </span>
                                  {r.scores.rerank !== null && (
                                    <span>
                                      rerank <b>{r.scores.rerank.toFixed(2)}</b>
                                    </span>
                                  )}
                                  <span>
                                    weight <b>{r.scores.weight.toFixed(2)}</b>
                                  </span>
                                  <span>
                                    <b><Tokens n={r.tokens} /></b>
                                  </span>
                                </div>
                              </div>
                            </div>
                          ))}
                          {hiddenStubs > 0 && (
                            <div className="dashed muted">
                              + {hiddenStubs} stub result{hiddenStubs === 1 ? '' : 's'} (id, scope and first 80 characters) —{' '}
                              <button type="button" className="link-btn" onClick={() => setExpanded(true)}>
                                expand
                              </button>{' '}
                              to load full content with <span className="mono">read_memory</span>.
                            </div>
                          )}
                        </div>
                      ))}
                    {tab === 'context' && <pre>{result.assembled_context || '(empty)'}</pre>}
                    {tab === 'json' && <pre className="small">{JSON.stringify(result, null, 2)}</pre>}
                  </div>

                  <div className="card">
                    <div className="ch">
                      <h3>Equivalent SDK call</h3>
                      <button type="button" className="btn bl sm" onClick={copySdk}>
                        Copy
                      </button>
                    </div>
                    <pre className="dark">{sdkCall(form)}</pre>
                  </div>
                </>
              )
            )}
          </div>
        </div>
      </div>
      {saveOpen && (
        <SaveQueryModal
          form={clean(form)}
          projects={projects}
          onClose={() => setSaveOpen(false)}
          onSaved={(q) => {
            setSaveOpen(false);
            setLoaded(q);
            setTab('ranked');
            void loadSaved();
            refreshCounts();
            toast(me?.labs ? 'Saved. Mark the memories it should return (☆) to make it a retrieval check.' : 'Query saved.');
          }}
        />
      )}
    </>
  );
};

/* ------------------------------------------------------------------ */
/* Funnel: how many memories survived each stage                       */
/* ------------------------------------------------------------------ */

const FUNNEL_COLOR: Record<FunnelKey, string> = {
  matched: '#0066cc',
  filters: '#5e40be',
  rbac: '#383838',
  weight: '#ca6c0f',
  limit: '#009596',
  budget: '#3d7317',
};

const Funnel: React.FC<{ result: SearchResponse; onStage: (k: FunnelKey) => void }> = ({ result, onStage }) => {
  const f = result.funnel ?? [];
  const top = Math.max(1, f[0]?.count ?? 1);
  const hidden = result.hidden_dropped ?? {};
  return (
    <div className="card">
      <div className="ch">
        <h3>Why these results</h3>
        <span className="sm muted">
          {f[0]?.count ?? 0} matched → {result.returned} returned
        </span>
      </div>
      <div className="funnel">
        {f.map((st) => (
          <button key={st.key} type="button" className="fstep" disabled={!st.dropped} onClick={() => onStage(st.key)} title={st.dropped ? 'Show what this stage dropped' : undefined}>
            <span className="fl">{st.label}</span>
            <span className="fbar">
              <i style={{ width: `${Math.max(2, (st.count / top) * 100)}%`, background: FUNNEL_COLOR[st.key] }} />
            </span>
            <span className="fn">
              <b>{st.count}</b>
              {st.dropped ? <span className="fd">−{st.dropped}</span> : null}
              {st.downgraded ? <span className="hint"> · {st.downgraded} cut to stub</span> : null}
              {hidden[st.key] ? <span className="hint"> · {hidden[st.key]} you can’t read</span> : null}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
};

const STAGE_SHORT: Record<string, string> = {
  filters: 'Filters',
  rbac: 'Access',
  weight: 'Weight',
  limit: 'Max results',
  budget: 'Token budget',
  matched: 'Not a top match',
  returned: 'Returned',
  missing: 'Not found',
  deleted: 'Deleted',
};

const DroppedList: React.FC<{ result: SearchResponse; stage: FunnelKey | 'all'; setStage: (k: FunnelKey | 'all') => void }> = ({ result, stage, setStage }) => {
  const all = result.dropped ?? [];
  const hidden = Object.entries(result.hidden_dropped ?? {});
  const stages = useMemo(() => [...new Set(all.map((d) => d.stage))], [all]);
  const shown = stage === 'all' ? all : all.filter((d) => d.stage === stage);
  if (!all.length && !hidden.length) {
    return (
      <Empty compact title="Nothing was dropped">
        Every memory that matched came back.
      </Empty>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button type="button" className={`tag ${stage === 'all' ? 'on' : ''}`} onClick={() => setStage('all')}>
          All {all.length}
        </button>
        {stages.map((k) => (
          <button key={k} type="button" className={`tag ${stage === k ? 'on' : ''}`} onClick={() => setStage(k)}>
            {STAGE_SHORT[k]} {all.filter((d) => d.stage === k).length}
          </button>
        ))}
      </div>
      {shown.map((d: DroppedMemory) => (
        <div className="res" key={`${d.stage}-${d.id}`}>
          <span className="rkd" style={{ background: FUNNEL_COLOR[d.stage] }} title={d.rank ? `Ranked #${d.rank}` : STAGE_SHORT[d.stage]}>
            {d.rank ?? '–'}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 }}>
              <ScopeLabel scope={d.scope} />
              <span className="lbl g">{STAGE_SHORT[d.stage]}</span>
              <span className="mono muted sm">{shortId(d.id)}</span>
            </div>
            <a href={memoryHref(d.id)} style={{ fontWeight: 500, textDecoration: 'none', color: '#151515' }}>
              {truncate(d.stub, 120)}
            </a>
            <div className="sm muted" style={{ marginTop: 4 }}>
              {d.detail}
              {d.score !== undefined ? ` · score ${d.score.toFixed(2)}` : ''}
            </div>
          </div>
        </div>
      ))}
      {hidden.length > 0 && (
        <p className="hint" style={{ margin: 0 }}>
          Also dropped: {hidden.map(([k, n]) => `${n} at ${STAGE_SHORT[k] ?? k}`).join(', ')} — memories you cannot read are counted, never shown.
        </p>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* "Why didn't X come back?"                                           */
/* ------------------------------------------------------------------ */

const WhyNot: React.FC<{ items: ExplainResult[]; open: boolean; setOpen: (o: boolean) => void; onAsk: (id: string) => void; onClear: () => void }> = ({
  items,
  open,
  setOpen,
  onAsk,
  onClear,
}) => (
  <div className="card">
    <div className="ch">
      <h3>Why didn’t it come back?</h3>
      <span style={{ display: 'flex', gap: 8 }}>
        {items.length > 0 && (
          <button type="button" className="btn bl sm" onClick={onClear}>
            Clear
          </button>
        )}
        <button type="button" className="btn bs sm" onClick={() => setOpen(true)}>
          Pick a memory
        </button>
      </span>
    </div>
    {items.length === 0 ? (
      <p className="sm muted" style={{ margin: 0 }}>
        Pick a memory you expected. It is traced through every stage, even if it never made the top 50 matches.
      </p>
    ) : (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map((w) => (
          <div key={w.id} className={`why ${w.stage === 'returned' ? 'ok' : ''}`}>
            <span className={`lbl ${w.stage === 'returned' ? 'grn' : w.stage === 'missing' ? 'g' : 'org'}`}>{STAGE_SHORT[w.stage] ?? w.stage}</span>
            <div style={{ minWidth: 0 }}>
              <div className="sm b6 ellipsis">{w.stub ?? w.id}</div>
              <div className="sm muted">{w.detail}</div>
            </div>
          </div>
        ))}
      </div>
    )}
    {open && (
      <Modal title="Which memory did you expect?" onClose={() => setOpen(false)}>
        <MemoryPicker
          autoFocus
          onPick={(m) => {
            setOpen(false);
            onAsk(m.id);
          }}
        />
      </Modal>
    )}
  </div>
);

/* ------------------------------------------------------------------ */
/* Compare two settings                                                */
/* ------------------------------------------------------------------ */

const CompareCard: React.FC<{
  a: Form;
  b: Form;
  setB: (f: Form) => void;
  resA: SearchResponse;
  resB: SearchResponse | null;
  running: boolean;
  onRun: () => void;
  onClose: () => void;
}> = ({ a, b, setB, resA, resB, running, onRun, onClose }) => {
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setB({ ...b, [k]: v });
  const rankA = Object.fromEntries(resA.results.map((r) => [r.id, r.rank]));
  const rankB = resB ? Object.fromEntries(resB.results.map((r) => [r.id, r.rank])) : {};
  const diffs = (['query', 'max_results', 'weight_threshold', 'session_focus_weight', 'max_response_tokens', 'mode', 'rerank', 'current_only', 'include_branches'] as const).filter(
    (k) => a[k] !== b[k],
  );
  const Col: React.FC<{ res: SearchResponse; other: Record<string, number>; side: 'A' | 'B' }> = ({ res, other, side }) => (
    <div style={{ flex: '1 1 260px', minWidth: 0 }}>
      <div className="sm b6" style={{ marginBottom: 6 }}>
        {side} · {res.returned} returned · {Math.round(res.total_ms)} ms · <Tokens n={res.tokens} />
      </div>
      {res.results.map((r) => {
        const o = other[r.id];
        const delta = o ? o - r.rank : null;
        return (
          <div key={r.id} className="cmp-row">
            <span className="rk sm">{r.rank}</span>
            <span className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
              {truncate(r.stub, 70)}
            </span>
            {o === undefined ? (
              <span className="lbl blue">only {side}</span>
            ) : delta ? (
              <span className={`sm ${delta > 0 ? 'ok' : 'warn'}`}>{delta > 0 ? `↑${delta}` : `↓${-delta}`}</span>
            ) : (
              <span className="hint">=</span>
            )}
          </div>
        );
      })}
    </div>
  );
  return (
    <div className="card">
      <div className="ch">
        <h3>Compare settings</h3>
        <span style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn bp sm" disabled={running} onClick={onRun}>
            {running ? 'Running…' : 'Run A and B'}
          </button>
          <button type="button" className="btn bl sm" onClick={onClose}>
            Close
          </button>
        </span>
      </div>
      <p className="hint" style={{ margin: '0 0 10px' }}>
        A is the form on the left. Change B here, then run both.
      </p>
      <div className="cmp-form">
        <div className="f">
          <label htmlFor="bq">B · query</label>
          <input id="bq" className="in" value={b.query} onChange={(e) => set('query', e.target.value)} />
        </div>
        <div className="f">
          <label htmlFor="bmr">B · max results · {b.max_results}</label>
          <input id="bmr" type="range" min={1} max={50} value={b.max_results} onChange={(e) => set('max_results', Number(e.target.value))} />
        </div>
        <div className="f">
          <label htmlFor="bwt">B · weight threshold · {b.weight_threshold.toFixed(2)}</label>
          <input id="bwt" type="range" min={0} max={100} value={Math.round(b.weight_threshold * 100)} onChange={(e) => set('weight_threshold', Number(e.target.value) / 100)} />
        </div>
        <div className="f">
          <label htmlFor="btk">B · max tokens</label>
          <input id="btk" className="in" type="number" min={100} value={b.max_response_tokens} onChange={(e) => set('max_response_tokens', Number(e.target.value) || 4000)} />
        </div>
        <label className="swrow">
          <span>B · rerank</span>
          <input type="checkbox" checked={b.rerank} onChange={(e) => set('rerank', e.target.checked)} />
        </label>
        <label className="swrow">
          <span>B · current versions only</span>
          <input type="checkbox" checked={b.current_only} onChange={(e) => set('current_only', e.target.checked)} />
        </label>
      </div>
      {diffs.length > 0 && (
        <p className="sm" style={{ margin: '10px 0 0' }}>
          Differs in: <b>{diffs.map((d) => d.replace(/_/g, ' ')).join(', ')}</b>
        </p>
      )}
      {resB ? (
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginTop: 14 }}>
          <Col res={resA} other={rankB} side="A" />
          <Col res={resB} other={rankA} side="B" />
        </div>
      ) : (
        <p className="sm muted" style={{ marginTop: 12 }}>
          Run both to see which memories move up, drop out or appear.
        </p>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Save a query on the server                                          */
/* ------------------------------------------------------------------ */

const SaveQueryModal: React.FC<{ form: SearchRequest; projects: string[]; onClose: () => void; onSaved: (q: SavedQuery) => void }> = ({
  form,
  projects,
  onClose,
  onSaved,
}) => {
  const toast = useToast();
  const [name, setName] = useState(truncate(form.query, 60));
  const [share, setShare] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const { id } = await api.createSavedQuery({ name, request: form, visibility: share ? 'project' : 'private', project: share || null });
      const { items } = await api.savedQueries();
      const q = items.find((i) => i.id === id);
      if (q) onSaved(q);
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Save query"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={busy || !name.trim()} onClick={save}>
            Save
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="sqn">Name</label>
        <input id="sqn" className="in" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="f">
        <label htmlFor="sqs">Share with</label>
        <select id="sqs" className="in" value={share} onChange={(e) => setShare(e.target.value)}>
          <option value="">Only me</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              Project {p}
            </option>
          ))}
        </select>
        <span className="hint">Shared queries run with each person’s own access, so nobody sees more than they may read.</span>
      </div>
    </Modal>
  );
};

export default Search;

