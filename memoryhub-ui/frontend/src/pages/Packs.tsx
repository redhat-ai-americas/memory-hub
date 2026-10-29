import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { copyText, Empty, ErrorState, Modal, ScopeLabel, SkLines, Switch, Tokens, TOKEN_ESTIMATE_NOTE, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate } from '@/hooks/useHashRoute';
import type { ContextPack, ContextPackDetail, PackQuery } from '@/types';
import { errorMessage, fmtInt, fmtRelative, truncate } from '@/utils/format';
import { ConfirmModal, MemoryPicker, memoryHref } from './common';
import { KnowledgeTabs } from './Knowledge';

/**
 * Context packs: named, reusable context for an agent or a project — pinned
 * memories plus searches, within a token budget, rendered under the viewer's
 * own access every time.
 */
const CRUMBS = [
  { label: 'Knowledge', href: buildHash('/knowledge') },
  { label: 'Context packs', href: buildHash('/knowledge/packs') },
];

/** Lives inside Knowledge: /knowledge/packs[/<id>]. */
export const PacksSection: React.FC<{ id?: string }> = ({ id }) => (id ? <PackPage id={id} /> : <PackList />);

const PackList: React.FC = () => {
  const toast = useToast();
  const { refreshCounts } = useApp();
  const { data, error, loading, reload } = useApi<{ items: ContextPack[] }>(() => api.packs(), []);
  const create = async () => {
    try {
      const { id } = await api.createPack({ name: 'New context pack' });
      refreshCounts();
      navigate(`/knowledge/packs/${id}`);
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };
  return (
    <>
      <PageHeader
        title="Knowledge"
        crumbs={[{ label: 'Knowledge', href: buildHash('/knowledge') }, { label: 'Context packs' }]}
        tabs={<KnowledgeTabs value="packs" />}
        description="Named context for an agent or a project: memories you pin plus searches that fill the rest, within a token budget. Each person gets the pack rendered with their own access."
        actions={
          <button type="button" className="btn bp" onClick={create}>
            New pack
          </button>
        }
      />
      <div className="body">
        {error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : loading && !data ? (
          <div className="card">
            <SkLines lines={5} />
          </div>
        ) : !data?.items.length ? (
          <div className="card">
            <Empty title="No context packs">Run a search in the playground and choose Save as context pack, or start an empty one.</Empty>
          </div>
        ) : (
          <div className="kgrid">
            {data.items.map((p) => (
              <a key={p.id} className="card kcard link-plain" href={buildHash(`/knowledge/packs/${p.id}`)}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span className={`lbl ${p.visibility === 'project' ? 's-project' : 's-user'}`}>{p.visibility === 'project' ? `Project ${p.project}` : 'Only you'}</span>
                  {p.read_only && !p.mine && <span className="lbl g">read-only</span>}
                </div>
                <h3 style={{ margin: '12px 0 4px' }}>{p.name}</h3>
                <p className="sm muted" style={{ margin: 0 }}>
                  {p.pinned.length} pinned · {p.queries.length} {p.queries.length === 1 ? 'search' : 'searches'} · budget {fmtInt(p.token_budget)} tokens
                </p>
                {p.agents.length > 0 && <p className="hint" style={{ margin: '8px 0 0' }}>For {p.agents.join(', ')}</p>}
                {p.last_render && (
                  <p className="hint" style={{ margin: '8px 0 0' }}>
                    {p.last_render.items} memories, <Tokens n={p.last_render.tokens} /> · {fmtRelative(p.last_render.at).toLowerCase()}
                  </p>
                )}
                {!p.mine && <p className="hint">by {p.owner}</p>}
              </a>
            ))}
          </div>
        )}
      </div>
    </>
  );
};

const PackPage: React.FC<{ id: string }> = ({ id }) => {
  const toast = useToast();
  const { refreshCounts } = useApp();
  const { data, error, reload } = useApi<ContextPackDetail>(() => api.pack(id), [id]);
  const [draft, setDraft] = useState<ContextPackDetail | null>(null);
  const [picker, setPicker] = useState(false);
  const [del, setDel] = useState(false);
  const [busy, setBusy] = useState(false);
  const [projects, setProjects] = useState<string[]>([]);
  useEffect(() => {
    if (data) setDraft(structuredClone(data));
  }, [data]);
  useEffect(() => {
    api
      .projects(true)
      .then((r) => setProjects(r.items.map((p) => p.name)))
      .catch(() => undefined);
  }, []);

  if (error && !data)
    return (
      <>
        <PageHeader title="Context pack" crumbs={[...CRUMBS, { label: 'Not found' }]} />
        <div className="body">
          <ErrorState error={error} onRetry={reload} />
        </div>
      </>
    );
  if (!data || !draft)
    return (
      <div className="body">
        <div className="card">
          <SkLines lines={8} />
        </div>
      </div>
    );

  const edit = data.can_edit;
  const owner = data.mine;
  const dirty = JSON.stringify(pick(draft)) !== JSON.stringify(pick(data));
  const save = async () => {
    setBusy(true);
    try {
      const body = pick(draft);
      const allowed = owner ? body : { name: body.name, description: body.description, pinned: body.pinned, queries: body.queries, token_budget: body.token_budget };
      await api.updatePack(id, allowed);
      toast('Pack saved.');
      reload();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  const set = <K extends keyof ContextPackDetail>(k: K, v: ContextPackDetail[K]) => setDraft({ ...draft, [k]: v });
  const setQuery = (i: number, q: Partial<PackQuery>) => set('queries', draft.queries.map((x, j) => (j === i ? { ...x, ...q } : x)));
  const r = data.render;
  const pinnedById = Object.fromEntries(r.items.filter((it) => it.source === 'pinned').map((it) => [it.id, it]));

  return (
    <>
      <PageHeader
        crumbs={[...CRUMBS, { label: data.name }]}
        title={data.name}
        description={data.description || 'Pinned memories first, then the searches below, until the token budget is used.'}
        actions={
          <>
            <button type="button" className="btn bg" onClick={async () => toast((await copyText(r.markdown)) ? 'Pack copied as Markdown.' : 'Copy failed.')}>
              Copy
            </button>
            <a className="btn bg" href={api.packMarkdownUrl(id)} download>
              Download .md
            </a>
            {edit && (
              <button type="button" className="btn bp" disabled={!dirty || busy} onClick={save}>
                {busy ? 'Saving…' : 'Save changes'}
              </button>
            )}
          </>
        }
      />
      <div className="body">
        {!edit && <div className="alert">This pack is read-only. Only {data.owner} can change it; you see it rendered with your own access.</div>}
        <div className="row-wrap">
          <div className="col-main">
            <section className="card">
              <h3>Basics</h3>
              <div className="fg">
                <div className="f">
                  <label htmlFor="pn">Name</label>
                  <input id="pn" className="in" disabled={!edit} value={draft.name} onChange={(e) => set('name', e.target.value)} />
                </div>
                <div className="f">
                  <label htmlFor="pb">Token budget</label>
                  <input id="pb" className="in" type="number" min={200} max={50000} disabled={!edit} value={draft.token_budget} onChange={(e) => set('token_budget', Number(e.target.value) || 2000)} />
                </div>
              </div>
              <div className="f" style={{ marginTop: 12 }}>
                <label htmlFor="pd">What it is for</label>
                <textarea id="pd" className="in" disabled={!edit} value={draft.description ?? ''} onChange={(e) => set('description', e.target.value)} />
              </div>
            </section>

            <section className="card">
              <div className="ch">
                <h3>Pinned memories</h3>
                {edit && (
                  <button type="button" className="btn bl sm" onClick={() => setPicker(true)}>
                    Pin a memory
                  </button>
                )}
              </div>
              {draft.pinned.length === 0 ? (
                <p className="sm muted">Pinned memories are always included, in this order, before any search results.</p>
              ) : (
                <ol className="pins">
                  {draft.pinned.map((mid, i) => (
                    <li key={mid}>
                      <a href={memoryHref(mid)} className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
                        {pinnedById[mid]?.stub ?? mid}
                      </a>
                      {pinnedById[mid] && <span className="hint"><Tokens n={pinnedById[mid].tokens} short /></span>}
                      {edit && (
                        <span style={{ display: 'flex', gap: 2 }}>
                          <button type="button" className="btn bl sm" aria-label="Move up" disabled={i === 0} onClick={() => set('pinned', move(draft.pinned, i, -1))}>
                            ↑
                          </button>
                          <button type="button" className="btn bl sm" aria-label="Move down" disabled={i === draft.pinned.length - 1} onClick={() => set('pinned', move(draft.pinned, i, 1))}>
                            ↓
                          </button>
                          <button type="button" className="btn bl sm" aria-label="Unpin" onClick={() => set('pinned', draft.pinned.filter((x) => x !== mid))}>
                            ✕
                          </button>
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section className="card">
              <div className="ch">
                <h3>Searches</h3>
                {edit && draft.queries.length < 10 && (
                  <button type="button" className="btn bl sm" onClick={() => set('queries', [...draft.queries, { query: '', max_results: 5, weight_threshold: 0 }])}>
                    Add search
                  </button>
                )}
              </div>
              {draft.queries.length === 0 && <p className="sm muted">Searches fill the rest of the budget with whatever currently matches.</p>}
              {draft.queries.map((q, i) => (
                <div key={i} className="pq">
                  <input className="in" aria-label={`Search ${i + 1}`} disabled={!edit} value={q.query} placeholder="What should this pack know about?" onChange={(e) => setQuery(i, { query: e.target.value })} />
                  <label className="sm">
                    top{' '}
                    <input className="in auto" type="number" min={1} max={20} disabled={!edit} value={q.max_results} onChange={(e) => setQuery(i, { max_results: Number(e.target.value) || 5 })} style={{ width: 64 }} />
                  </label>
                  {edit && (
                    <button type="button" className="btn bl sm" aria-label="Remove search" onClick={() => set('queries', draft.queries.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  )}
                </div>
              ))}
            </section>

            {owner && (
              <section className="card">
                <h3>Sharing &amp; agents</h3>
                <div className="fg" style={{ marginTop: 10 }}>
                  <div className="f">
                    <label htmlFor="ps">Share with</label>
                    <select
                      id="ps"
                      className="in"
                      value={draft.visibility === 'project' ? draft.project ?? '' : ''}
                      onChange={(e) => setDraft({ ...draft, visibility: e.target.value ? 'project' : 'private', project: e.target.value || null })}
                    >
                      <option value="">Only me</option>
                      {projects.map((p) => (
                        <option key={p} value={p}>
                          Project {p}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="swrow" style={{ alignSelf: 'end' }}>
                    <span>Read-only for others</span>
                    <Switch on={draft.read_only} onChange={(v) => set('read_only', v)} label="Read-only for others" />
                  </div>
                </div>
                <p className="fh" style={{ marginTop: 14 }}>
                  Attach to my agents
                </p>
                {data.my_agents.length === 0 ? (
                  <p className="sm muted">
                    No agents linked to you yet. <a href={buildHash('/identities')}>Link an agent</a>.
                  </p>
                ) : (
                  <div className="fx">
                    {data.my_agents.map((a) => (
                      <label key={a}>
                        <span>
                          <input
                            type="checkbox"
                            checked={draft.agents.includes(a)}
                            onChange={() => set('agents', draft.agents.includes(a) ? draft.agents.filter((x) => x !== a) : [...draft.agents, a])}
                          />{' '}
                          <span className="mono">{a}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
                <p className="hint" style={{ margin: '10px 0 0' }}>
                  MemoryHub’s MCP server cannot hand packs to agents yet (there is no get_context_pack tool). Attaching records which agents the pack is for; until the
                  tool exists, copy or download the pack into the agent’s instructions.
                </p>
                <hr className="sep" style={{ margin: '16px 0' }} />
                <button type="button" className="btn bl danger" onClick={() => setDel(true)}>
                  Delete pack
                </button>
              </section>
            )}
          </div>

          <aside className="col-side" style={{ flex: '1 1 360px' }}>
            <section className="card">
              <div className="ch">
                <h3>Preview</h3>
                <span className="sm muted">as {r.as}</span>
              </div>
              <div className="bar" style={{ margin: '6px 0 4px' }} aria-label={`${r.tokens} of ${r.budget} tokens`}>
                <span style={{ width: `${Math.min(100, (r.tokens / r.budget) * 100)}%` }} />
              </div>
              <div className="hint">
                <abbr className="est" title={TOKEN_ESTIMATE_NOTE}>≈{fmtInt(r.tokens)} of {fmtInt(r.budget)} tokens</abbr> · {r.items.length} memories
                {r.over_budget.length ? ` · ${r.over_budget.length} did not fit` : ''}
                {r.hidden ? ` · ${r.hidden} pinned you cannot read` : ''}
                {r.missing ? ` · ${r.missing} pinned deleted` : ''}
              </div>
              {dirty && <p className="hint warn">Save to refresh the preview.</p>}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
                {r.items.map((it) => (
                  <div key={it.id} className="pitem">
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                      <ScopeLabel scope={it.scope} />
                      <span className="lbl g">{it.source === 'pinned' ? 'pinned' : `search ${Number(it.source.split(':')[1]) + 1}`}</span>
                      <span className="hint"><Tokens n={it.tokens} short /></span>
                    </div>
                    <a href={memoryHref(it.id)} className="sm" style={{ color: 'inherit', textDecoration: 'none' }}>
                      {truncate(it.text, 220)}
                    </a>
                  </div>
                ))}
                {r.items.length === 0 && <span className="sm muted">Empty — pin memories or add a search.</span>}
              </div>
            </section>
          </aside>
        </div>
      </div>
      {picker && (
        <Modal title="Pin a memory" onClose={() => setPicker(false)}>
          <MemoryPicker
            autoFocus
            exclude={draft.pinned}
            onPick={(m) => {
              setPicker(false);
              set('pinned', [...draft.pinned, m.id]);
            }}
          />
        </Modal>
      )}
      {del && (
        <ConfirmModal
          title="Delete this context pack?"
          confirmLabel="Delete"
          danger
          onClose={() => setDel(false)}
          onConfirm={async () => {
            await api.deletePack(id);
            refreshCounts();
            navigate('/knowledge/packs');
          }}
        >
          The pack is removed for everyone it is shared with. Memories are not touched.
        </ConfirmModal>
      )}
    </>
  );
};

const pick = (p: ContextPack) => ({
  name: p.name,
  description: p.description,
  pinned: p.pinned,
  queries: p.queries,
  token_budget: p.token_budget,
  visibility: p.visibility,
  project: p.project,
  read_only: p.read_only,
  agents: p.agents,
});

const move = <T,>(arr: T[], i: number, d: number) => {
  const next = [...arr];
  const [x] = next.splice(i, 1);
  next.splice(i + d, 0, x);
  return next;
};

