import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs } from '@/components/Shell';
import { DocumentsSection } from './Documents';
import { PacksSection } from './Packs';
import { Empty, ErrorState, ScopeLabel, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { KnowledgeFact, KnowledgeIndexItem, KnowledgePage } from '@/types';
import { errorMessage, fmtInt, fmtRelative } from '@/utils/format';
import { memoryHref } from './common';

/**
 * Knowledge pages: what memory says about you or a project, as a page that
 * rebuilds itself when its source memories change. Every line cites them.
 */
const Knowledge: React.FC<{ route: HashRoute }> = ({ route }) => {
  const [, , kind, id] = route.path.split('/');
  if (kind === 'documents') return <DocumentsSection id={id} />;
  if (kind === 'packs') return <PacksSection id={id} />;
  if (kind === 'me' || (kind === 'project' && id)) return <Page kind={kind} id={kind === 'me' ? 'me' : decodeURIComponent(id)} />;
  return <Index />;
};

/** Knowledge: the living pages, the documents memories are written from, and context packs. */
export const KnowledgeTabs: React.FC<{ value: 'pages' | 'documents' | 'packs' }> = ({ value }) => (
  <Tabs
    label="Knowledge"
    value={value}
    onChange={(v) => navigate(v === 'pages' ? '/knowledge' : `/knowledge/${v}`)}
    tabs={[
      { value: 'pages', label: 'Pages' },
      { value: 'documents', label: 'Documents' },
      { value: 'packs', label: 'Context packs' },
    ]}
  />
);

const pageHref = (kind: string, id: string) => buildHash(kind === 'me' ? '/knowledge/me' : `/knowledge/project/${encodeURIComponent(id)}`);

const Index: React.FC = () => {
  const { data, error, loading, reload } = useApi<{ items: KnowledgeIndexItem[] }>(() => api.knowledge(), []);
  return (
    <>
      <PageHeader
        title="Knowledge"
        tabs={<KnowledgeTabs value="pages" />}
        description="A living page for you and for each of your projects: what memory knows, grouped by topic, with the people and things involved and the open questions. Every line links to the memories it came from, and each page rebuilds itself when they change."
      />
      <div className="body">
        {error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : loading && !data ? (
          <div className="card">
            <SkLines lines={6} />
          </div>
        ) : (
          <div className="kgrid">
            {(data?.items ?? []).map((k) => (
              <a key={`${k.kind}:${k.id}`} className="card kcard link-plain" href={pageHref(k.kind, k.id)}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <span className={`lbl ${k.kind === 'me' ? 's-user' : 's-project'}`}>{k.kind === 'me' ? 'You' : 'Project'}</span>
                  <span className={`lbl ${k.fresh ? 'grn' : 'g'}`}>{k.generated_at ? (k.fresh ? 'Up to date' : 'Updates on open') : 'Not built yet'}</span>
                </div>
                <h3 style={{ margin: '12px 0 4px' }}>{k.title}</h3>
                <p className="sm muted" style={{ margin: 0 }}>
                  {fmtInt(k.source_count)} source {k.source_count === 1 ? 'memory' : 'memories'}
                  {k.summary ? ` · ${k.summary.facts} facts · ${k.summary.entities} entities` : ''}
                  {k.summary?.open_questions ? ` · ${k.summary.open_questions} open questions` : ''}
                </p>
                {k.sections.length > 0 && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
                    {k.sections.map((s) => (
                      <span key={s} className="tag">
                        {s}
                      </span>
                    ))}
                  </div>
                )}
                {k.generated_at && <p className="hint" style={{ margin: '12px 0 0' }}>Built {fmtRelative(k.generated_at).toLowerCase()}</p>}
              </a>
            ))}
          </div>
        )}
      </div>
    </>
  );
};

const Cites: React.FC<{ ids: string[] }> = ({ ids }) => (
  <span className="cites">
    {ids.slice(0, 4).map((mid, i) => (
      <a key={mid} href={memoryHref(mid)} title="Open the source memory" className="cite">
        {i + 1}
      </a>
    ))}
    {ids.length > 4 && <span className="hint">+{ids.length - 4}</span>}
  </span>
);

const Fact: React.FC<{ f: KnowledgeFact; compact?: boolean }> = ({ f, compact }) => (
  <li className="kfact">
    <div style={{ minWidth: 0 }}>
      <span>{f.text}</span> <Cites ids={f.memory_ids} />
      {!compact && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4, alignItems: 'center' }}>
          <ScopeLabel scope={f.scope} />
          {f.similar > 0 && <span className="lbl g">+{f.similar} similar folded</span>}
          {f.contradicted > 0 && <span className="lbl s-role">⚠ contradicted ×{f.contradicted}</span>}
          {f.stale && <span className="lbl ylw">stale</span>}
          <span className="hint">
            weight {f.weight.toFixed(2)} · {fmtRelative(f.updated_at).toLowerCase()}
          </span>
        </div>
      )}
    </div>
  </li>
);

const Page: React.FC<{ kind: 'me' | 'project'; id: string }> = ({ kind, id }) => {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const { data, error, loading, reload, setData } = useApi<KnowledgePage>(() => api.knowledgePage(kind, id), [kind, id]);
  const sources = kind === 'me' ? buildHash('/memories', { scope: 'user' }) : buildHash('/memories', { project: id });

  const refresh = async () => {
    setBusy(true);
    try {
      setData(await api.knowledgePage(kind, id, true));
      toast('Page rebuilt from the current memories.');
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };

  if (error && !data) {
    return (
      <>
        <PageHeader title="Knowledge" crumbs={[{ label: 'Knowledge', href: buildHash('/knowledge') }, { label: id }]} />
        <div className="body">
          <ErrorState error={error} onRetry={reload} />
        </div>
      </>
    );
  }

  const k = data;
  const changes = k?.changes;
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Knowledge', href: buildHash('/knowledge') }, { label: kind === 'me' ? 'You' : id }]}
        title={k?.subject.title ?? 'Knowledge'}
        description={
          k
            ? `Built from ${fmtInt(k.source_count)} memories you can read${k.truncated ? ' (the 400 strongest)' : ''} · last source change ${k.last_source_change ? fmtRelative(k.last_source_change).toLowerCase() : '—'} · rebuilds itself when they change.`
            : undefined
        }
        actions={
          <>
            <a className="btn bg" href={sources}>
              Source memories
            </a>
            <button type="button" className="btn bs" disabled={busy} onClick={refresh}>
              {busy ? 'Rebuilding…' : 'Rebuild now'}
            </button>
          </>
        }
      />
      <div className="body">
        {loading && !k ? (
          <div className="card">
            <SkLines lines={10} />
          </div>
        ) : k && k.source_count === 0 ? (
          <div className="card">
            <Empty title="Nothing to summarise yet" action={<a className="btn bs" href={buildHash('/overview')}>Getting started</a>}>
              {kind === 'me' ? 'Once you or your agents write user memories, this page fills in on its own.' : 'Project memories you can read will appear here.'}
            </Empty>
          </div>
        ) : (
          k && (
            <>
              {k.rebuilt && changes && (changes.added.length > 0 || changes.removed.length > 0) && (
                <div className="alert" role="status">
                  <div>
                    <b>Updated just now.</b> Since the previous version: {changes.added.length} new {changes.added.length === 1 ? 'fact' : 'facts'}
                    {changes.removed.length ? `, ${changes.removed.length} gone` : ''}.
                  </div>
                </div>
              )}
              <div className="row-wrap">
                <div className="col-main">
                  {k.highlights.length > 0 && (
                    <section className="card khigh">
                      <h3>In short</h3>
                      <ul className="kfacts">
                        {k.highlights.map((f) => (
                          <Fact key={f.memory_id} f={f} compact />
                        ))}
                      </ul>
                    </section>
                  )}
                  {k.sections.map((s) => (
                    <section className="card" key={s.title}>
                      <div className="ch">
                        <h3>{s.title.charAt(0).toUpperCase() + s.title.slice(1)}</h3>
                        <span className="sm muted">{s.facts.length} facts</span>
                      </div>
                      <ul className="kfacts">
                        {s.facts.map((f) => (
                          <Fact key={f.memory_id} f={f} />
                        ))}
                      </ul>
                    </section>
                  ))}
                </div>
                <aside className="col-side">
                  <section className="card">
                    <h3>At a glance</h3>
                    <div className="stats4" style={{ marginTop: 12 }}>
                      <div>
                        <div className="statv">{k.summary.facts}</div>
                        <div className="hint">facts</div>
                      </div>
                      <div>
                        <div className="statv">{k.summary.folded}</div>
                        <div className="hint">duplicates folded</div>
                      </div>
                      <div>
                        <div className="statv">{k.summary.open_questions}</div>
                        <div className="hint">open questions</div>
                      </div>
                      <div>
                        <div className="statv">{k.summary.stale}</div>
                        <div className="hint">going stale</div>
                      </div>
                    </div>
                    <p className="hint" style={{ margin: '12px 0 0' }}>
                      Built {fmtRelative(k.generated_at).toLowerCase()}. No model writes this page: facts are your memories, grouped by domain tag, with near-duplicates folded together.
                    </p>
                  </section>
                  {k.entities.length > 0 && (
                    <section className="card">
                      <h3>People &amp; things</h3>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
                        {k.entities.map((e) => (
                          <a key={e.id} className="ent link-plain" href={buildHash(`/entity/${e.id}`)} title={`${e.count} memories`}>
                            {e.name} <span className="hint">{e.count}</span>
                          </a>
                        ))}
                      </div>
                    </section>
                  )}
                  {k.questions.length > 0 && (
                    <section className="card">
                      <h3>Open questions</h3>
                      <ul className="kfacts">
                        {k.questions.map((q) => (
                          <li key={q.memory_id} className="kfact">
                            <div>
                              <span className="lbl s-role">⚠ {q.count}</span> <a href={memoryHref(q.memory_id)}>{q.text}</a>
                              <div className="hint">An agent saw behaviour that contradicts it. Confirm, revise or let it go.</div>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                  {k.recent.length > 0 && (
                    <section className="card">
                      <h3>Recently changed</h3>
                      <ul className="kfacts">
                        {k.recent.map((r) => (
                          <li key={r.memory_id} className="kfact">
                            <div>
                              <span className={`lbl ${r.change === 'new' ? 'grn' : 'blue'}`}>{r.change === 'new' ? 'new' : `v${r.version}`}</span>{' '}
                              <a href={memoryHref(r.memory_id)}>{r.text}</a>
                              <div className="hint">{fmtRelative(r.updated_at)}</div>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                  {changes && (changes.added.length > 0 || changes.removed.length > 0) && (
                    <section className="card">
                      <h3>Since the previous version</h3>
                      <ul className="kfacts">
                        {changes.added.map((c) => (
                          <li key={`a${c.memory_id}`} className="kfact">
                            <div>
                              <b className="grn-t">+</b> <a href={memoryHref(c.memory_id)}>{c.text}</a>
                            </div>
                          </li>
                        ))}
                        {changes.removed.map((c) => (
                          <li key={`r${c.memory_id}`} className="kfact">
                            <div className="muted">
                              <b>−</b> <s>{c.text}</s>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                  {k.stale.length > 0 && (
                    <section className="card">
                      <h3>Going stale</h3>
                      <p className="hint" style={{ margin: '4px 0 8px' }}>
                        Not changed for a while. Memory hygiene can suggest fading them.
                      </p>
                      <ul className="kfacts">
                        {k.stale.slice(0, 5).map((f) => (
                          <Fact key={f.memory_id} f={f} compact />
                        ))}
                      </ul>
                      <a className="sm" href={buildHash('/hygiene')}>
                        Open Dreaming
                      </a>
                    </section>
                  )}
                </aside>
              </div>
            </>
          )
        )}
      </div>
    </>
  );
};

export default Knowledge;
