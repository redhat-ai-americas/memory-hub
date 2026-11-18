import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { Empty, ErrorState, ScopeLabel, SkLines, Standby } from '@/components/ui';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { MemoryRecord } from '@/types';
import { fmtRelative, truncate } from '@/utils/format';
import { memoryHref } from './common';

interface Hit {
  id: string;
  rank: number;
  score: number;
  memory: MemoryRecord | null;
}

/**
 * Search playground. GET /api/graph/search ranks up to 20 current memories
 * the viewer may read: by embedding similarity when the embedding service
 * answers, by plain text match otherwise (every score is then 1.00). Each hit is
 * opened with GET /api/memory/{id} to show what it says.
 */
const Search: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { standby } = useApp();
  const initial = route.params.get('q') || '';
  const [query, setQuery] = useState(initial);
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [ran, setRan] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const run = async (q = query) => {
    const text = q.trim();
    if (!text) return;
    setRunning(true);
    setError(null);
    navigate(route.path, { q: text }, { replace: true });
    try {
      const matches = await api.search(text);
      const records = await Promise.all(matches.map((m) => api.memory(m.id).catch(() => null)));
      setHits(matches.map((m, i) => ({ id: m.id, rank: i + 1, score: m.score, memory: records[i] })));
      setRan(text);
    } catch (e) {
      setError(e as Error);
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    if (initial) void run(initial);
    // Run once for a shared link with ?q=.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const textFallback = !!hits?.length && hits.every((h) => h.score === 1);

  return (
    <>
      <PageHeader
        title="Search playground"
        crumbs={[{ label: 'Search playground' }]}
        description="Search every current memory you can read, the way an agent's search_memory call ranks them. Only memories your access allows ever come back."
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
            <h2 data-h="3">Query</h2>
            <div className="f">
              <label htmlFor="q">Query</label>
              <textarea id="q" className="in" required value={query} onChange={(e) => setQuery(e.target.value)} placeholder="how should I run containers locally for this repo?" />
              <span className="hint">Returns the 20 closest current memories.</span>
            </div>
            <button type="submit" className="btn bp" style={{ justifyContent: 'center' }} disabled={running || standby || !query.trim()}>
              {running ? 'Running…' : 'Run search'}
            </button>
            {standby && <span className="hint">Searching starts once the tenant has its first memory.</span>}
          </form>

          <div className="col-main">
            {standby ? (
              <div className="card">
                <Standby compact={false}>Ranked results appear here once there is something to search.</Standby>
              </div>
            ) : error ? (
              <div className="card">
                <ErrorState error={error} onRetry={() => void run()} title="The search failed" />
              </div>
            ) : running && !hits ? (
              <div className="card">
                <SkLines lines={8} />
              </div>
            ) : !hits ? (
              <div className="card">
                <Empty title="Run a search">Enter a query to see which memories come back and how closely each one matches.</Empty>
              </div>
            ) : (
              <div className="card">
                <div className="ch">
                  <h2 data-h="3">Ranked results</h2>
                  <span className="sm muted">
                    {hits.length} for “{truncate(ran, 60)}” · {textFallback ? 'text match (embedding service unavailable)' : 'semantic similarity'}
                  </span>
                </div>
                {hits.length === 0 ? (
                  <Empty compact title="No results">
                    Nothing you can read matched this query. Try fewer words.
                  </Empty>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {hits.map((h) => (
                      <div className="res" key={h.id}>
                        <span className="rk">{h.rank}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          {h.memory ? (
                            <>
                              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
                                <ScopeLabel scope={h.memory.scope} />
                                <span className="sm muted">{h.memory.owner_id}</span>
                                {h.memory.branch_type && <span className="lbl g">{h.memory.branch_type}</span>}
                              </div>
                              <a href={memoryHref(h.id)} style={{ fontWeight: 500, textDecoration: 'none', color: '#151515' }}>
                                {truncate(h.memory.stub || h.memory.content, 160)}
                              </a>
                            </>
                          ) : (
                            <a href={memoryHref(h.id)} className="mono">
                              {h.id}
                            </a>
                          )}
                          <div className="sc">
                            {!textFallback && (
                              <span>
                                similarity <b>{h.score.toFixed(2)}</b>
                              </span>
                            )}
                            {h.memory && (
                              <>
                                <span>
                                  weight <b>{h.memory.weight.toFixed(2)}</b>
                                </span>
                                <span>
                                  v{h.memory.version} · updated {fmtRelative(h.memory.updated_at)}
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
};

export default Search;
