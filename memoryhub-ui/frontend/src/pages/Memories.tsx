import React, { useEffect, useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Dropdown, Empty, ErrorState, Icon, Modal, Pager, ScopeLabel, SelectMenu, SkTable, SkLines, Standby, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { BrowseParams, BrowseResponse, MemoryRow, MyPrefsResponse } from '@/types';
import { errorMessage, fmtCompact, fmtInt, fmtRelative, fmtWeight, SCOPE_ORDER, scopeMeta, shortId } from '@/utils/format';
import { ConfirmModal, memoryHref, RelationshipModal, WriteMemoryModal } from './common';
import MemoryGraph, { LockIcon } from './MemoryGraph';
import MemoryTimeline from './MemoryTimeline';
import { UploadDocumentModal } from './Documents';

const list = (v: string | null) => (v ? v.split(',').filter(Boolean) : []);
const COLUMNS = ['scope', 'entities', 'owner', 'weight', 'version', 'branches', 'updated'] as const;
type Column = (typeof COLUMNS)[number];
const COLUMN_LABEL: Record<Column, string> = { scope: 'Scope', entities: 'Entities', owner: 'Owner', weight: 'Weight', version: 'Ver.', branches: 'Branches', updated: 'Updated' };
const COLS_KEY = 'memoryhub.browser.columns.v2';

const readCols = (): Column[] => {
  try {
    const raw = window.localStorage.getItem(COLS_KEY);
    const parsed = raw ? (JSON.parse(raw) as Column[]) : null;
    return parsed?.length ? parsed : [...COLUMNS];
  } catch {
    return [...COLUMNS];
  }
};

const Memories: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { standby, refreshCounts, role, me, superuser } = useApp();
  const isAdmin = role === 'admin';
  const grant = me?.access?.break_glass ?? null;
  const p = route.params;
  const view: 'table' | 'graph' | 'timeline' = p.get('view') === 'graph' ? 'graph' : p.get('view') === 'timeline' ? 'timeline' : 'table';
  // Old links drew time inside the graph; it is its own view now.
  useEffect(() => {
    if (p.get('layout') === 'timeline') navigate('/memories', { ...Object.fromEntries(p), layout: '', view: 'timeline' }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const state = {
    entity: p.get('entity') || '',
    entityName: p.get('entityName') || '',
    tab: p.get('tab') || 'current',
    q: p.get('q') || '',
    mode: p.get('mode') || 'semantic',
    scope: list(p.get('scope')),
    actor: list(p.get('actor')),
    project: p.get('project') || '',
    domain: list(p.get('domain')),
    minWeight: p.get('minw') ? Number(p.get('minw')) : 0,
    flag: list(p.get('flag')),
    sort: p.get('sort') || '',
    page: Number(p.get('page') || 1),
    per: Number(p.get('per') || 20),
  };
  const sort = state.sort || (state.q ? 'relevance' : 'updated');

  const setParams = (changes: Record<string, string | number | string[] | undefined>, resetPage = true) => {
    const next = new URLSearchParams(p);
    Object.entries(changes).forEach(([k, v]) => {
      const value = Array.isArray(v) ? v.join(',') : v === undefined ? '' : String(v);
      if (value === '' || value === '0' && k === 'minw') next.delete(k);
      else next.set(k, value);
    });
    if (resetPage && !('page' in changes)) next.delete('page');
    navigate('/memories', next, { replace: true });
  };

  const params: BrowseParams = {
    tab: state.tab,
    q: state.q || undefined,
    mode: state.mode,
    scope: state.scope,
    actor: state.actor,
    project: state.project || undefined,
    domain: state.domain,
    min_weight: state.minWeight || undefined,
    flag: state.flag,
    sort,
    order: 'desc',
    page: state.page,
    per_page: state.per,
    entity: state.entity || undefined,
  };
  const key = JSON.stringify(params);
  const { data, error, loading, reload } = useApi<BrowseResponse>(
    () => (view === 'table' ? api.browse(params) : Promise.resolve(null as unknown as BrowseResponse)),
    [key, view],
    standby && view === 'table' ? 5000 : null,
  );

  const [query, setQuery] = useState(state.q);
  useEffect(() => setQuery(state.q), [state.q]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => setSelected(new Set()), [key]);
  const [columns, setColumns] = useState<Column[]>(readCols);
  const [moreWriters, setMoreWriters] = useState(false);
  const [moreDomains, setMoreDomains] = useState(false);
  const [modal, setModal] = useState<null | 'write' | 'weight' | 'relate' | 'promote' | 'delete' | 'quarantine'>(null);
  const [qReason, setQReason] = useState('');
  const [rowDelete, setRowDelete] = useState<MemoryRow | null>(null);
  const [docOpen, setDocOpen] = useState(false);
  const [weightValue, setWeightValue] = useState(0.7);
  const [promoteScope, setPromoteScope] = useState('organizational');
  const [promoteScopeId, setPromoteScopeId] = useState('');

  const toggleColumn = (c: Column) => {
    const next = columns.includes(c) ? columns.filter((x) => x !== c) : COLUMNS.filter((x) => columns.includes(x) || x === c);
    setColumns(next);
    try {
      window.localStorage.setItem(COLS_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };

  const facets = data?.facets;
  const tabCounts = data?.tab_counts;
  const items = data?.items ?? [];
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.id));
  const ids = [...selected];

  const chips = useMemo(() => {
    const out: { label: string; clear: () => void }[] = [];
    if (state.scope.length) out.push({ label: `Scope: ${state.scope.map((s) => scopeMeta(s).label).join(', ')}`, clear: () => setParams({ scope: [] }) });
    if (state.actor.length) out.push({ label: `Written by: ${state.actor.join(', ')}`, clear: () => setParams({ actor: [] }) });
    if (state.project) out.push({ label: `Project: ${state.project}`, clear: () => setParams({ project: '' }) });
    if (state.domain.length) out.push({ label: `Domain: ${state.domain.join(', ')}`, clear: () => setParams({ domain: [] }) });
    if (state.entity) out.push({ label: `Entity: ${state.entityName || state.entity.slice(0, 8)}`, clear: () => setParams({ entity: '', entityName: '' }) });
    if (state.minWeight) out.push({ label: `Weight ≥ ${state.minWeight.toFixed(2)}`, clear: () => setParams({ minw: '' }) });
    state.flag.forEach((f) =>
      out.push({ label: FLAG_LABEL[f] ?? f, clear: () => setParams({ flag: state.flag.filter((x) => x !== f) }) }),
    );
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const toggleIn = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const runBulk = async (body: Parameters<typeof api.bulk>[0], done: string) => {
    const res = await api.bulk(body);
    if (res.errors.length) toast(`${res.errors.length} failed: ${res.errors[0].detail}`, 'err');
    if (res.forgotten?.length) toast(forgetReport(res.forgotten));
    else if (res.done.length) toast(done);
    setSelected(new Set());
    reload();
    refreshCounts();
  };

  const writers = facets?.writers ?? [];
  const domains = facets?.domains ?? [];
  const filtersDisabled = standby;

  return (
    <>
      <PageHeader
        title={
          isAdmin ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              Content moderation
              {grant ? (
                <span className="lbl red" style={{ fontFamily: 'var(--mh-font-text)' }}>
                  Incident {grant.incident_ref} · user memories open
                </span>
              ) : (
                <span className="lbl g" style={{ fontFamily: 'var(--mh-font-text)' }}>
                  <LockIcon size={12} />
                  Personal memories: metadata only
                </span>
              )}
            </span>
          ) : (
            'Memory browser'
          )
        }
        crumbs={[{ label: isAdmin ? 'Content moderation' : 'Memory browser' }]}
        description={
          isAdmin
            ? grant
              ? 'Search, quarantine, restore and delete memories across owners, including personal (user-scope) memories while incident access is on.'
              : 'Search, quarantine, restore and delete memories across owners. Project, campaign, role, organizational and enterprise memories are readable; what a personal (user-scope) memory says stays private.'
            : role === 'user'
              ? 'Every memory you are allowed to read — your own, and what your projects, campaigns, roles and organization share with you — as a table, a graph of how they connect, or a timeline.'
              : 'Every memory you are allowed to read, across all six scopes — as a table, a graph of how they connect, or a timeline. Nodes you cannot read are counted, never shown.'
        }
        actions={
          <>
            {view === 'table' && (
              <a className="btn bg" href={api.exportUrl(state.scope)} download aria-disabled={standby}>
                {isAdmin ? 'Export metadata' : 'Export JSONL'}
              </a>
            )}
            {!isAdmin && me?.labs && (
              <button type="button" className="btn bg" onClick={() => setDocOpen(true)}>
                Add document
              </button>
            )}
            {!isAdmin && (
              <button type="button" className="btn bp" onClick={() => setModal('write')}>
                <Icon.Plus />
                Write memory
              </button>
            )}
          </>
        }
        tabs={
          <div className="ph-tabrow">
            {view === 'table' && (
              <Tabs
                label="Memory state"
                value={state.tab}
                onChange={(t) => setParams({ tab: t === 'current' ? '' : t })}
                tabs={[
                  { value: 'current', label: 'Current', count: tabCounts?.current ?? null },
                  { value: 'all', label: 'All versions', count: tabCounts?.all ?? null },
                  { value: 'quarantined', label: 'Quarantined', count: tabCounts?.quarantined ?? null },
                  { value: 'deleted', label: 'Deleted', count: tabCounts?.deleted ?? null },
                ]}
              />
            )}
            <div className="viewtoggle">
              <span className="sm muted">View</span>
              <div className="seg lg" role="group" aria-label="View as">
                <button type="button" className={view === 'table' ? 'on' : ''} aria-pressed={view === 'table'} onClick={() => setParams({ view: '' }, false)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                    <rect x="3" y="4" width="18" height="16" rx="2" />
                    <path d="M3 10h18M3 15h18M9 10v10" />
                  </svg>
                  Table
                </button>
                <button type="button" className={view === 'graph' ? 'on' : ''} aria-pressed={view === 'graph'} onClick={() => setParams({ view: 'graph' }, false)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                    <circle cx="6" cy="6" r="2.5" />
                    <circle cx="18" cy="8" r="2.5" />
                    <circle cx="10" cy="18" r="2.5" />
                    <path d="M8.3 7.1l7.4.6M7 8.3l2.2 7.3M16.5 10l-4.8 6.3" />
                  </svg>
                  Graph
                </button>
                <button type="button" className={view === 'timeline' ? 'on' : ''} aria-pressed={view === 'timeline'} onClick={() => setParams({ view: 'timeline' }, false)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                    <path d="M3 18h18M6 18V9M11 18V5M16 18v-7M21 18v-4" />
                  </svg>
                  Timeline
                </button>
              </div>
            </div>
          </div>
        }
      />
      <div className="body">
        {isAdmin && (
          <div className={`alert ${grant ? 'err-a' : ''}`} role="note">
            <LockIcon size={18} />
            <div style={{ flex: '1 1 400px', minWidth: 0 }}>
              {grant ? (
                <>
                  <b>Incident access {grant.incident_ref} is on.</b> User memories are readable until {new Date(grant.expires_at).toLocaleString()}. Every one you open is
                  logged with HIGH severity and its owner is told. <a href={buildHash('/incident')}>End it</a> as soon as you are done.
                </>
              ) : (
                <>
                  <b>Personal memories are private.</b> You read and moderate project, campaign, role, organizational and enterprise memories. User-scope memories show
                  metadata only and are left out of search{data?.hidden_scopes?.includes('user') && (facets?.scopes.find((f) => f.value === 'user')?.count ?? 0) > 0
                    ? ` (${fmtCompact(facets!.scopes.find((f) => f.value === 'user')!.count)} here)`
                    : ''}
                  .{' '}
                  {superuser ? (
                    <>
                      For an incident, start <a href={buildHash('/incident')}>incident access</a>.
                    </>
                  ) : (
                    'Opening them needs a super-user with an incident reference.'
                  )}
                </>
              )}
            </div>
          </div>
        )}
        {role === 'user' && <ScopeBar project={state.project} onProject={(v) => setParams({ project: v })} tenant={me?.tenant_id ?? ''} />}
        {view !== 'table' && (chips.length > 0 || state.q) && (
          <div className="carried" role="note">
            <span className="sm muted">Filters from the table:</span>
            {chips.map((c) => (
              <span className="chip" key={c.label}>
                {c.label}
                <button type="button" aria-label={`Remove ${c.label}`} onClick={c.clear}>
                  ✕
                </button>
              </span>
            ))}
            {state.q && <span className="sm muted">Search text and the Current / Deleted tabs apply to the table only.</span>}
            <button type="button" className="btn bl sm" onClick={() => setParams({ view: '' }, false)}>
              Edit filters
            </button>
          </div>
        )}
        {view === 'graph' ? (
          <MemoryGraph route={route} setParams={setParams} />
        ) : view === 'timeline' ? (
          <MemoryTimeline route={route} setParams={setParams} />
        ) : (
        <div className="row-wrap">
          <aside className="card" style={{ flex: '1 1 230px', maxWidth: '100%', padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 20 }} aria-label="Filters">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3>Filters</h3>
              <button
                type="button"
                className="btn bl sm"
                disabled={!chips.length}
                onClick={() => setParams({ scope: [], actor: [], project: '', domain: [], minw: '', flag: [], entity: '', entityName: '' })}
              >
                Clear all
              </button>
            </div>
            {!facets ? (
              <SkLines lines={10} />
            ) : (
              <>
                <div>
                  <p className="fh">Scope</p>
                  <div className="fx">
                    {facets.scopes
                      .filter((s) => s.count > 0 || SCOPE_ORDER.includes(s.value as never))
                      .map((s) => (
                        <label key={s.value}>
                          <span>
                            <input
                              type="checkbox"
                              disabled={filtersDisabled}
                              checked={state.scope.includes(s.value)}
                              onChange={() => setParams({ scope: toggleIn(state.scope, s.value) })}
                            />{' '}
                            <ScopeLabel scope={s.value} />
                          </span>
                          <span className="muted sm">{fmtCompact(s.count)}</span>
                        </label>
                      ))}
                  </div>
                </div>
                <div>
                  <p className="fh">Written by</p>
                  <div className="fx">
                    {writers.length === 0 && <span className="sm muted">No writers yet</span>}
                    {(moreWriters ? writers : writers.slice(0, 4)).map((w) => (
                      <label key={w.value}>
                        <span>
                          <input type="checkbox" checked={state.actor.includes(w.value)} onChange={() => setParams({ actor: toggleIn(state.actor, w.value) })} />{' '}
                          <span className="ellipsis">{w.value}</span>
                        </span>
                        <span className="muted sm">{fmtCompact(w.count)}</span>
                      </label>
                    ))}
                    {writers.length > 4 && (
                      <button type="button" className="link-btn sm" style={{ textAlign: 'left' }} onClick={() => setMoreWriters((m) => !m)}>
                        {moreWriters ? 'Show fewer' : `Show ${writers.length - 4} more`}
                      </button>
                    )}
                  </div>
                </div>
                <div>
                  <p className="fh">Project</p>
                  <SelectMenu
                    label="Project"
                    width="100%"
                    value={state.project}
                    onChange={(v) => setParams({ project: v })}
                    options={[{ value: '', label: 'All projects' }, ...(facets.projects ?? []).map((pr) => ({ value: pr.value, label: `${pr.value} · ${fmtCompact(pr.count)}` }))]}
                  />
                </div>
                {(
                <div>
                  <p className="fh">Domain tags</p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {domains.length === 0 && <span className="sm muted">No domain tags yet</span>}
                    {(moreDomains ? domains : domains.slice(0, 5)).map((d) => (
                      <button
                        key={d.value}
                        type="button"
                        className="tag"
                        aria-pressed={state.domain.includes(d.value)}
                        title={`${d.count} memories`}
                        style={{ border: state.domain.includes(d.value) ? '1px solid #0066cc' : '1px solid transparent', cursor: 'pointer', background: state.domain.includes(d.value) ? '#e7f1fa' : undefined }}
                        onClick={() => setParams({ domain: toggleIn(state.domain, d.value) })}
                      >
                        {d.value}
                      </button>
                    ))}
                    {domains.length > 5 && (
                      <button type="button" className="tag" style={{ border: 0, cursor: 'pointer' }} onClick={() => setMoreDomains((m) => !m)}>
                        {moreDomains ? 'less' : `+${domains.length - 5}`}
                      </button>
                    )}
                  </div>
                </div>
                )}
                <WeightFilter value={state.minWeight} disabled={filtersDisabled} onCommit={(v) => setParams({ minw: v ? v.toFixed(2) : '' })} />
                <div>
                  <p className="fh">Flags</p>
                  <div className="fx">
                    {(['contradicted', 'has_branches', 'near_duplicate'] as const).map((f) => (
                      <label key={f}>
                        <span>
                          <input type="checkbox" disabled={filtersDisabled} checked={state.flag.includes(f)} onChange={() => setParams({ flag: toggleIn(state.flag, f) })} />{' '}
                          {FLAG_LABEL[f]}
                        </span>
                        <span className="muted sm">{facets.flags[f] === null ? '—' : fmtCompact(facets.flags[f] as number)}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </>
            )}
          </aside>

          <section className="card" style={{ flex: '999 1 560px', minWidth: 0, padding: 0 }}>
            <form
              style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', padding: '16px 20px' }}
              onSubmit={(e) => {
                e.preventDefault();
                setParams({ q: query.trim(), sort: '' });
              }}
            >
              <div style={{ position: 'relative', flex: '1 1 300px' }}>
                <Icon.Search size={16} stroke="#4d4d4d" style={{ position: 'absolute', left: 12, top: 11 }} />
                <label className="vh" htmlFor="q">
                  Search memories
                </label>
                <input
                  id="q"
                  className="in"
                  style={{ paddingLeft: 36 }}
                  value={query}
                  disabled={standby}
                  onChange={(e) => setQuery(e.target.value)}
                  onBlur={() => query.trim() !== state.q && setParams({ q: query.trim(), sort: '' })}
                  placeholder={isAdmin ? (grant ? 'Search every scope, including user memories' : 'Search project, campaign, role, organizational and enterprise memories') : 'Semantic search or filter by text'}
                />
              </div>
              {<SelectMenu
                label="Search mode"
                value={state.mode}
                onChange={(v) => setParams({ mode: v === 'semantic' ? '' : v })}
                options={[
                  { value: 'semantic', label: 'Semantic' },
                  { value: 'text', label: 'Text' },
                ]}
              />}
              <SelectMenu
                label="Sort"
                prefix="Sort: "
                value={sort}
                onChange={(v) => setParams({ sort: v })}
                options={[
                  ...(state.q ? [{ value: 'relevance', label: 'Relevance' }] : []),
                  { value: 'updated', label: 'Last updated' },
                  { value: 'created', label: 'Created' },
                  { value: 'weight', label: 'Weight' },
                  { value: 'version', label: 'Version' },
                ]}
              />
              <Dropdown
                align="right"
                toggle={(tp) => (
                  <button type="button" className="sel" {...tp}>
                    Columns
                  </button>
                )}
              >
                {() => (
                  <>
                    {COLUMNS.map((c) => (
                      <label key={c} style={{ display: 'flex', gap: 8, padding: '6px 16px', fontSize: 14, cursor: 'pointer' }}>
                        <input type="checkbox" checked={columns.includes(c)} onChange={() => toggleColumn(c)} />
                        {COLUMN_LABEL[c]}
                      </label>
                    ))}
                  </>
                )}
              </Dropdown>
            </form>
            {(chips.length > 0 || data?.search_mode === 'text') && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '0 20px 14px', alignItems: 'center' }}>
                {chips.length > 0 && <span className="sm muted">Active:</span>}
                {chips.map((c) => (
                  <span className="chip" key={c.label}>
                    {c.label}
                    <button type="button" aria-label={`Remove ${c.label}`} onClick={c.clear}>
                      ✕
                    </button>
                  </span>
                ))}
                {data?.search_mode === 'text' && state.mode === 'semantic' && (
                  <span className="sm warn">Embedding service unavailable — showing text matches.</span>
                )}
              </div>
            )}
            {selected.size > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', background: '#e7f1fa', borderTop: '1px solid #b9dafc', borderBottom: '1px solid #b9dafc', padding: '10px 20px', fontSize: 14 }}>
                <b>{selected.size} selected</b>
                {state.tab === 'deleted' && !isAdmin ? (
                  <>
                    <button
                      type="button"
                      className="btn bp"
                      onClick={() =>
                        runBulk({ action: 'restore', ids }, `${fmtInt(ids.length)} restored — agents get ${ids.length === 1 ? 'it' : 'them'} again.`).catch((e) =>
                          toast(errorMessage(e), 'err'),
                        )
                      }
                    >
                      Restore
                    </button>
                    <span style={{ marginLeft: 'auto' }} className="sm muted">
                      Brings back every version deleted with it · newest becomes current · audited
                    </span>
                  </>
                ) : isAdmin ? (
                  <>
                    {state.tab === 'deleted' ? (
                      <button
                        type="button"
                        className="btn bp"
                        onClick={() => runBulk({ action: 'restore', ids }, `${fmtInt(ids.length)} restored.`).catch((e) => toast(errorMessage(e), 'err'))}
                      >
                        Restore
                      </button>
                    ) : (
                      <>
                        {state.tab !== 'quarantined' && (
                          <button type="button" className="btn bl" onClick={() => setModal('quarantine')}>
                            Quarantine
                          </button>
                        )}
                        <button type="button" className="btn bl danger" onClick={() => setModal('delete')}>
                          Delete
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      className="btn bl"
                      onClick={() => setParams({ view: 'graph', gfocus: 'memory', focus: ids[0] }, false)}
                    >
                      Show in graph
                    </button>
                    <span style={{ marginLeft: 'auto' }} className="sm muted">
                      {grant ? `Incident ${grant.incident_ref} · every action audited with HIGH severity` : 'User memories need incident access · audited'}
                    </span>
                  </>
                ) : (
                <>
                <button type="button" className="btn bl" onClick={() => setModal('weight')}>
                  Change weight
                </button>
                <button type="button" className="btn bl" onClick={() => setModal('relate')}>
                  Add relationship
                </button>
                <button type="button" className="btn bl" onClick={() => setModal('promote')}>
                  Propose promotion
                </button>
                <button type="button" className="btn bl danger" onClick={() => setModal('delete')}>
                  Delete
                </button>
                <button type="button" className="btn bl" onClick={() => setParams({ view: 'graph', gfocus: 'memory', focus: ids[0] }, false)}>
                  Show in graph
                </button>
                <span style={{ marginLeft: 'auto' }} className="sm muted">
                  Soft delete · whole version chain · audited
                </span>
                </>
                )}
              </div>
            )}

            {standby ? (
              <Standby
                compact={false}
                title="No memories yet"
                action={
                  <div style={{ display: 'flex', gap: 8 }}>
                    <a className="btn bp" href={buildHash('/clients')}>
                      Connect an agent
                    </a>
                    <button type="button" className="btn bs" onClick={() => setModal('write')}>
                      Write memory
                    </button>
                  </div>
                }
              >
                Memories appear here, with scope, owner, weight and version, as soon as an agent calls write_memory.
              </Standby>
            ) : error && !data ? (
              <ErrorState error={error} onRetry={reload} />
            ) : loading && !data ? (
              <SkTable rows={8} cols={6} />
            ) : items.length === 0 ? (
              <Empty
                title={state.q || chips.length ? 'No memories match' : state.tab === 'current' ? 'No current memories' : `Nothing ${state.tab === 'all' ? 'here' : state.tab}`}
                action={
                  chips.length || state.q ? (
                    <button type="button" className="btn bs" onClick={() => setParams({ q: '', scope: [], actor: [], project: '', domain: [], minw: '', flag: [], entity: '', entityName: '' })}>
                      Clear search and filters
                    </button>
                  ) : undefined
                }
              >
                {state.q || chips.length
                  ? 'Try a broader query or remove a filter.'
                  : state.tab === 'quarantined'
                    ? 'Writes held by a quarantine rule will be listed here for review.'
                    : state.tab === 'deleted'
                      ? 'Soft-deleted memories stay here, with their version chains. Select one and press Restore to bring it back.'
                      : 'Memories appear here as agents write them.'}
              </Empty>
            ) : (
              <>
                <div className="scroll">
                  <table className="tbl" style={{ minWidth: 900 }}>
                    <thead>
                      <tr>
                        <th style={{ width: 36 }}>
                          <input
                            type="checkbox"
                            aria-label="Select all"
                            checked={allSelected}
                            onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((i) => i.id)))}
                          />
                        </th>
                        <th>Memory</th>
                        {columns.includes('scope') && <th>Scope</th>}
                        {columns.includes('entities') && <th style={{ minWidth: 150 }}>Entities</th>}
                        {columns.includes('owner') && <th>Owner</th>}
                        {columns.includes('weight') && <th style={{ width: 120 }}>Weight</th>}
                        {columns.includes('version') && <th>Ver.</th>}
                        {columns.includes('branches') && <th>Branches</th>}
                        {columns.includes('updated') && <th>Updated</th>}
                        <th style={{ width: 40 }} />
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((m) => (
                        <tr key={m.id} className={selected.has(m.id) || p.get('sel') === m.id ? 'is-sel' : ''}>
                          <td>
                            <input
                              type="checkbox"
                              aria-label="Select memory"
                              checked={selected.has(m.id)}
                              onChange={() => {
                                const next = new Set(selected);
                                if (next.has(m.id)) next.delete(m.id);
                                else next.add(m.id);
                                setSelected(next);
                              }}
                            />
                          </td>
                          <td style={{ maxWidth: 440, minWidth: 300 }}>
                            {m.redacted ? (
                              <div>
                                <span className="redact">
                                  <LockIcon />
                                  Content hidden
                                </span>{' '}
                                <a href={memoryHref(m.id)} className="sm">
                                  Metadata
                                </a>
                                <div className="rbar" aria-hidden="true" style={{ width: `${40 + (parseInt(m.id.slice(0, 2), 16) % 55)}%` }} />
                              </div>
                            ) : (
                              <a href={memoryHref(m.id)} style={{ fontWeight: 500, textDecoration: 'none' }}>
                                {m.content_preview}
                              </a>
                            )}
                            <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                              <span className="mono muted">{shortId(m.id)}</span>
                              {m.domains.map((d) => (
                                <span className="tag" key={d}>
                                  {d}
                                </span>
                              ))}
                              {m.open_contradictions > 0 && <span className="lbl s-role">⚠ contradicted ×{m.open_contradictions}</span>}
                              {m.near_duplicate !== null && <span className="lbl s-role">⚠ near-duplicate {m.near_duplicate.toFixed(2)}</span>}
                              {m.status !== 'active' && <span className="lbl g">{m.status}</span>}
                              {!m.is_current && state.tab === 'all' && <span className="lbl g">v{m.version} · superseded</span>}
                              {m.score !== null && <span className="mono muted">score {m.score.toFixed(2)}</span>}
                            </div>
                          </td>
                          {columns.includes('scope') && (
                            <td>
                              <ScopeLabel scope={m.scope} />
                            </td>
                          )}
                          {columns.includes('entities') && (
                            <td>
                              {m.redacted ? (
                                <span className="sm muted">
                                  {m.entity_count ?? 0} {(m.entity_count ?? 0) === 1 ? 'entity' : 'entities'}
                                </span>
                              ) : m.entities?.length ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                                  {m.entities.slice(0, 3).map((e) => (
                                    <button
                                      key={e.id}
                                      type="button"
                                      className={`ent ${state.entity === e.id ? 'on' : ''}`}
                                      title={`${ENTITY_TYPE[e.type]?.label ?? e.type} · show memories that mention it`}
                                      onClick={() => setParams({ entity: e.id, entityName: e.name })}
                                    >
                                      <EntityIcon type={e.type} />
                                      {e.name}
                                    </button>
                                  ))}
                                  {m.entities.length > 3 && <span className="hint">+{m.entities.length - 3} more</span>}
                                </div>
                              ) : (
                                <span className="muted">—</span>
                              )}
                            </td>
                          )}
                          {columns.includes('owner') && (
                            <td className="sm">
                              <div>{m.scope === 'role' ? `role:${m.scope_id ?? m.owner_id}` : m.scope === 'campaign' ? `campaign:${m.scope_id ?? m.owner_id}` : m.scope_id ?? m.owner_id}</div>
                              <div className="muted">{writtenBy(m)}</div>
                            </td>
                          )}
                          {columns.includes('weight') && (
                            <td>
                              <div className="sm" style={{ marginBottom: 6 }}>
                                {fmtWeight(m.weight)}
                              </div>
                              <div className="bar thin">
                                <span style={{ width: `${Math.round(m.weight * 100)}%` }} />
                              </div>
                            </td>
                          )}
                          {columns.includes('version') && <td className="mono">v{m.version}</td>}
                          {columns.includes('branches') && (
                            <td className="sm">{m.branch_summary.length ? m.branch_summary.map((b) => `${b.type} · ${b.count}`).join(', ') : '—'}</td>
                          )}
                          {columns.includes('updated') && (
                            <td className="sm muted" style={{ whiteSpace: 'nowrap' }} title={new Date(m.updated_at).toLocaleString()}>
                              {fmtRelative(state.tab === 'deleted' && m.deleted_at ? m.deleted_at : m.updated_at)}
                            </td>
                          )}
                          <td>
                            <Dropdown
                              align="right"
                              toggle={(tp) => (
                                <button type="button" className="btn bl" aria-label="Actions" style={{ padding: '4px 8px' }} {...tp}>
                                  ⋮
                                </button>
                              )}
                            >
                              {(close) => (
                                <>
                                  <a href={memoryHref(m.id)}>Open</a>
                                  <a href={buildHash('/memories', { ...Object.fromEntries(p), view: 'graph', gfocus: 'memory', focus: m.id, sel: m.id })}>Open in graph</a>
                                  <a href={buildHash('/memories', { ...Object.fromEntries(p), view: 'timeline', sel: m.id })}>Show on timeline</a>
                                  <a href={buildHash(`/memory/${m.id}`, { tab: 'access' })}>Access log</a>
                                  {isAdmin && !m.redacted && (
                                    <>
                                      <hr />
                                      {state.tab === 'deleted' ? (
                                        <button
                                          type="button"
                                          onClick={() => {
                                            close();
                                            runBulk({ action: 'restore', ids: [m.id] }, 'Memory restored.').catch((e) => toast(errorMessage(e), 'err'));
                                          }}
                                        >
                                          Restore
                                        </button>
                                      ) : (
                                        <>
                                          {state.tab !== 'quarantined' && (
                                            <button
                                              type="button"
                                              onClick={() => {
                                                close();
                                                setSelected(new Set([m.id]));
                                                setModal('quarantine');
                                              }}
                                            >
                                              Quarantine
                                            </button>
                                          )}
                                          <button
                                            type="button"
                                            className="danger"
                                            onClick={() => {
                                              close();
                                              setRowDelete(m);
                                            }}
                                          >
                                            Delete
                                          </button>
                                        </>
                                      )}
                                    </>
                                  )}
                                  {state.tab === 'deleted' && !isAdmin && (
                                    <>
                                      <hr />
                                      <button
                                        type="button"
                                        onClick={() => {
                                          close();
                                          runBulk({ action: 'restore', ids: [m.id] }, 'Memory restored.').catch((e) => toast(errorMessage(e), 'err'));
                                        }}
                                      >
                                        Restore
                                      </button>
                                    </>
                                  )}
                                  {state.tab !== 'deleted' && !isAdmin && (
                                    <>
                                      <hr />
                                      <button
                                        type="button"
                                        className="danger"
                                        onClick={() => {
                                          close();
                                          setRowDelete(m);
                                        }}
                                      >
                                        Delete
                                      </button>
                                    </>
                                  )}
                                </>
                              )}
                            </Dropdown>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pager
                  page={state.page}
                  perPage={state.per}
                  total={data!.total}
                  noun="matching"
                  onPage={(pg) => setParams({ page: pg }, false)}
                  onPerPage={(n) => setParams({ per: n })}
                />
              </>
            )}
          </section>
        </div>
        )}
      </div>

      {docOpen && <UploadDocumentModal onClose={() => setDocOpen(false)} />}
      {modal === 'write' && <WriteMemoryModal onClose={() => setModal(null)} onSaved={() => reload()} />}
      {modal === 'relate' && <RelationshipModal sourceIds={ids} onClose={() => setModal(null)} onDone={reload} />}
      {modal === 'weight' && (
        <Modal
          title={`Change weight of ${ids.length} ${ids.length === 1 ? 'memory' : 'memories'}`}
          onClose={() => setModal(null)}
          actions={
            <>
              <button
                type="button"
                className="btn bp"
                onClick={async () => {
                  setModal(null);
                  await runBulk({ action: 'weight', ids, weight: weightValue }, `Weight set to ${weightValue.toFixed(2)} — new versions created.`).catch((e) =>
                    toast(errorMessage(e), 'err'),
                  );
                }}
              >
                Create new versions
              </button>
              <button type="button" className="btn bg" onClick={() => setModal(null)}>
                Cancel
              </button>
            </>
          }
        >
          <div className="f">
            <label htmlFor="bw">Weight · {weightValue.toFixed(2)}</label>
            <input id="bw" type="range" min={0} max={100} value={Math.round(weightValue * 100)} onChange={(e) => setWeightValue(Number(e.target.value) / 100)} />
            <span className="hint">Each memory gets a new version; old versions stay readable for forensics. Audited.</span>
          </div>
        </Modal>
      )}
      {modal === 'promote' && (
        <Modal
          title="Propose promotion"
          onClose={() => setModal(null)}
          actions={
            <>
              <button
                type="button"
                className="btn bp"
                onClick={async () => {
                  setModal(null);
                  await runBulk(
                    { action: 'promote', ids, target_scope: promoteScope, target_scope_id: promoteScopeId || undefined },
                    'Promotion proposed — waiting in the review queue.',
                  ).catch((e) => toast(errorMessage(e), 'err'));
                }}
              >
                Send to review queue
              </button>
              <button type="button" className="btn bg" onClick={() => setModal(null)}>
                Cancel
              </button>
            </>
          }
        >
          <p className="sm muted" style={{ margin: 0 }}>
            A copy of each selected memory is created at the broader scope with status <span className="mono">pending</span> and a{' '}
            <span className="mono">derived_from</span> link. Agents see it only after a reviewer approves it.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="f">
              <label htmlFor="ps">Target scope</label>
              <select id="ps" className="in" value={promoteScope} onChange={(e) => setPromoteScope(e.target.value)}>
                {SCOPE_ORDER.filter((s) => s !== 'user').map((s) => (
                  <option key={s} value={s}>
                    {scopeMeta(s).label}
                  </option>
                ))}
              </select>
            </div>
            {['project', 'role', 'campaign'].includes(promoteScope) && (
              <div className="f">
                <label htmlFor="psid">{scopeMeta(promoteScope).label} ID</label>
                <input id="psid" className="in" value={promoteScopeId} onChange={(e) => setPromoteScopeId(e.target.value)} />
              </div>
            )}
          </div>
        </Modal>
      )}
      {modal === 'quarantine' && (
        <ConfirmModal
          title={`Quarantine ${ids.length} ${ids.length === 1 ? 'memory' : 'memories'}?`}
          confirmLabel="Quarantine"
          danger
          onClose={() => setModal(null)}
          onConfirm={async () => {
            await runBulk({ action: 'quarantine', ids, reason: qReason.trim() || undefined }, `${fmtInt(ids.length)} quarantined — agents stop receiving ${ids.length === 1 ? 'it' : 'them'}.`);
            setQReason('');
          }}
        >
          Agents stop receiving {ids.length === 1 ? 'it' : 'them'} at once. Quarantined memories wait in the Review queue, where a moderator restores or rejects them. Audited.
          <div className="f" style={{ marginTop: 12 }}>
            <label htmlFor="qr">Reason</label>
            <input id="qr" className="in" maxLength={500} value={qReason} onChange={(e) => setQReason(e.target.value)} placeholder="e.g. Contains a customer contract number" />
          </div>
        </ConfirmModal>
      )}
      {(modal === 'delete' || rowDelete) && (
        <ConfirmModal
          title={rowDelete ? 'Delete memory?' : `Delete ${ids.length} ${ids.length === 1 ? 'memory' : 'memories'}?`}
          confirmLabel="Delete"
          danger
          onClose={() => {
            setModal(null);
            setRowDelete(null);
          }}
          onConfirm={async () => {
            const target = rowDelete ? [rowDelete.id] : ids;
            await runBulk({ action: 'delete', ids: target }, `${fmtInt(target.length)} deleted.`);
          }}
        >
          This soft-deletes {rowDelete ? <b>“{rowDelete.stub}”</b> : <b>{ids.length} memories</b>} together with every version and child branch. Agents stop
          receiving {rowDelete ? 'it' : 'them'} immediately; the rows stay in the Deleted tab for forensics. The action is recorded in the audit log.
        </ConfirmModal>
      )}
    </>
  );
};

const ENTITY_TYPE: Record<string, { label: string; color: string; d: string }> = {
  person: { label: 'Person', color: '#0066cc', d: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c1.5-4 4.5-6 8-6s6.5 2 8 6' },
  organization: { label: 'Organization', color: '#3d7317', d: 'M4 21V5l8-3v19M12 9h8v12M3 21h18M7 8h2M7 12h2M7 16h2M15 13h2M15 17h2' },
  location: { label: 'Location', color: '#009596', d: 'M12 21s-7-6.5-7-11a7 7 0 0114 0c0 4.5-7 11-7 11zM12 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z' },
  object: { label: 'Object', color: '#ca6c0f', d: 'M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10' },
  event: { label: 'Event', color: '#5e40be', d: 'M5 5h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2zM3 10h18M8 3v4M16 3v4' },
};

const EntityIcon: React.FC<{ type: string }> = ({ type }) => {
  const t = ENTITY_TYPE[type] ?? ENTITY_TYPE.object;
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={t.color} strokeWidth="2.2" aria-hidden="true">
      <path d={t.d} />
    </svg>
  );
};

const FLAG_LABEL: Record<string, string> = {
  contradicted: 'Has open contradiction',
  has_branches: 'Has branches',
  near_duplicate: 'Near-duplicate (≥0.90)',
};

const writtenBy = (m: MemoryRow) => {
  const actor = m.actor_id;
  if (!actor || actor === m.owner_id) return m.scope === 'organizational' || m.scope === 'enterprise' ? '' : 'direct';
  if (m.scope === 'organizational' || m.scope === 'role') return `promoted by ${actor}`;
  const driver = m.driver_id && m.driver_id !== actor && m.driver_id !== m.owner_id ? ` · ${m.driver_id}` : '';
  return `via ${actor}${driver}`;
};

const WeightFilter: React.FC<{ value: number; disabled?: boolean; onCommit: (v: number) => void }> = ({ value, disabled, onCommit }) => {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <div>
      <p className="fh">Weight ≥ {v.toFixed(2)}</p>
      <input
        type="range"
        min={0}
        max={100}
        value={Math.round(v * 100)}
        aria-label="Minimum weight"
        style={{ width: '100%' }}
        disabled={disabled}
        onChange={(e) => setV(Number(e.target.value) / 100)}
        onMouseUp={() => onCommit(v)}
        onKeyUp={() => onCommit(v)}
        onTouchEnd={() => onCommit(v)}
      />
    </div>
  );
};

export default Memories;

/** What a delete actually did, in the scope it did it (R1-022: forget reports the real result). */
const forgetReport = (rows: { scope: string; scope_id: string | null; owner_id: string; versions: number; branches: number }[]) => {
  const versions = rows.reduce((a, r) => a + r.versions, 0);
  const branches = rows.reduce((a, r) => a + r.branches, 0);
  const scopes = [...new Set(rows.map((r) => `${scopeMeta(r.scope).label.toLowerCase()} · ${r.scope_id ?? r.owner_id}`))];
  return `Forgot ${rows.length} ${rows.length === 1 ? 'memory' : 'memories'} — ${versions} ${versions === 1 ? 'version' : 'versions'}${
    branches ? ` and ${branches} ${branches === 1 ? 'branch' : 'branches'}` : ''
  } in ${scopes.join(', ')}. Agents no longer receive ${rows.length === 1 ? 'it' : 'them'}; restore from the Deleted tab.`;
};

/** Who you are browsing as and which project — R1-022: the active scope is always visible. */
const ScopeBar: React.FC<{ project: string; onProject: (v: string) => void; tenant: string }> = ({ project, onProject, tenant }) => {
  const { data } = useApi<MyPrefsResponse>(() => api.myPrefs(), []);
  const a = data?.account;
  if (!a) return null;
  return (
    <div className="scopebar" role="region" aria-label="Active scope">
      <span>
        <span className="hint">Signed in as</span> <b className="mono">{a.username}</b>
        {a.agents.length > 0 && (
          <span className="hint">
            {' '}
            + {a.agents.length === 1 ? 'agent' : 'agents'} <span className="mono">{a.agents.join(', ')}</span>
          </span>
        )}
      </span>
      <span>
        <span className="hint">Tenant</span> <b className="mono">{tenant || '—'}</b>
      </span>
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <label className="hint" htmlFor="scope-project">
          Project
        </label>
        <select id="scope-project" className="in auto" value={project} onChange={(e) => onProject(e.target.value)}>
          <option value="">All my projects ({a.projects.length})</option>
          {a.projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </span>
      <span className="hint" style={{ marginLeft: 'auto' }}>
        You see your own memories, your agents’ and what your projects, roles and organization share — the same rules the MCP server applies to agents.
      </span>
    </div>
  );
};
