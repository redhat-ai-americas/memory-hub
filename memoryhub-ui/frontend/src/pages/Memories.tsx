import React, { useEffect, useMemo, useState } from 'react';
import { api } from '@/api/client';
import { browseParams } from '@/utils/browse';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Dropdown, Empty, ErrorState, Icon, Pager, ScopeLabel, SelectMenu, SkTable, SkLines, Standby, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { BrowseResponse, MemoryRow } from '@/types';
import { errorMessage, fmtCompact, fmtInt, fmtRelative, fmtWeight, SCOPE_ORDER, scopeMeta, shortId } from '@/utils/format';
import { ConfirmModal, memoryHref, RelationshipModal, WriteMemoryModal } from './common';
import MemoryGraph, { LockIcon } from './MemoryGraph';

const list = (v: string | null) => (v ? v.split(',').filter(Boolean) : []);
const COLUMNS = ['scope', 'entities', 'owner', 'weight', 'version', 'branches', 'relevant', 'updated'] as const;
type Column = (typeof COLUMNS)[number];
const COLUMN_LABEL: Record<Column, string> = { scope: 'Scope', entities: 'Entities', owner: 'Owner', weight: 'Weight', version: 'Ver.', branches: 'Branches', relevant: 'Relevant until', updated: 'Updated' };
// v4 (Nov 2026): Relevant until and Updated are on for everyone again; older saved choices would hide them.
const COLS_KEY = 'memoryhub.browser.columns.v7';

/** Moderators work on scope, owner, weight and dates; entities and branches are one click away in Columns. */
const ADMIN_DEFAULT: Column[] = ['scope', 'owner', 'weight', 'relevant', 'updated'];
const readCols = (admin = false): Column[] => {
  const fallback = admin ? [...ADMIN_DEFAULT] : [...COLUMNS];
  try {
    const raw = window.localStorage.getItem(COLS_KEY);
    const parsed = raw ? (JSON.parse(raw) as Column[]) : null;
    return parsed?.length ? parsed : fallback;
  } catch {
    return fallback;
  }
};

const Memories: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { standby, refreshCounts, role, me } = useApp();
  const isAdmin = role === 'admin';
  const canWrite = (me?.write?.scopes ?? []).length > 0;
  const p = new URLSearchParams(route.params);
  if (isAdmin) p.delete('actor');
  const view: 'table' | 'graph' = p.get('view') === 'graph' ? 'graph' : 'table';
  const state = {
    entity: p.get('entity') || '',
    entityName: p.get('entityName') || '',
    tab: p.get('tab') || 'current',
    q: p.get('q') || '',
    mode: p.get('mode') || 'text',
    scope: list(p.get('scope')),
    actor: list(p.get('actor')),
    project: p.get('project') || '',
    domain: list(p.get('domain')),
    minWeight: p.get('minw') ? Number(p.get('minw')) : 0,
    maxWeight: p.get('maxw') || '',
    createdFrom: p.get('from') || '',
    createdTo: p.get('to') || '',
    branchType: p.get('branch') || '',
    flag: list(p.get('flag')),
    sort: p.get('sort') || '',
    page: Number(p.get('page') || 1),
    per: Number(p.get('per') || 20),
  };
  // The BFF has no relevance ranking for browse (it would sort by last update), so it is not offered.
  const sort = state.sort && state.sort !== 'relevance' ? state.sort : 'updated';

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

  const params = browseParams(p);
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
  const [columns, setColumns] = useState<Column[]>(() => readCols(isAdmin));
  const [moreWriters, setMoreWriters] = useState(false);
  const [moreDomains, setMoreDomains] = useState(false);
  const [modal, setModal] = useState<null | 'write' | 'relate' | 'delete' | 'quarantine'>(null);
  const [qReason, setQReason] = useState('');
  const [rowDelete, setRowDelete] = useState<MemoryRow | null>(null);

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
  const selectedItems = items.filter((item) => selected.has(item.id));
  const selectionKnown = ids.length > 0 && selectedItems.length === ids.length;
  const selectionCanWrite = selectionKnown && selectedItems.every((item) => item.capabilities?.write);
  const selectionCanModerate = selectionKnown && selectedItems.every((item) => item.capabilities?.moderate);
  // #671: people delete what they or their agents wrote; project admins anything in their project.
  const selectionCanDelete = selectionKnown && selectedItems.every((item) => item.can_delete);
  const undeletable = items.filter((m) => selected.has(m.id) && m.can_delete === false).length;

  const chips = useMemo(() => {
    const out: { label: string; clear: () => void }[] = [];
    if (state.scope.length) out.push({ label: `Scope: ${state.scope.map((s) => scopeMeta(s).label).join(', ')}`, clear: () => setParams({ scope: [] }) });
    if (state.actor.length) out.push({ label: `Written by: ${state.actor.join(', ')}`, clear: () => setParams({ actor: [] }) });
    if (state.project) out.push({ label: `Project: ${state.project}`, clear: () => setParams({ project: '' }) });
    if (state.domain.length) out.push({ label: `Domain: ${state.domain.join(', ')}`, clear: () => setParams({ domain: [] }) });
    if (state.entity) out.push({ label: `Entity: ${state.entityName || state.entity.slice(0, 8)}`, clear: () => setParams({ entity: '', entityName: '' }) });
    if (state.minWeight) out.push({ label: `Weight ≥ ${state.minWeight.toFixed(2)}`, clear: () => setParams({ minw: '' }) });
    if (state.maxWeight) out.push({ label: `Weight ≤ ${Number(state.maxWeight).toFixed(2)}`, clear: () => setParams({ maxw: '' }) });
    if (state.createdFrom) out.push({ label: `Created from ${state.createdFrom}`, clear: () => setParams({ from: '' }) });
    if (state.createdTo) out.push({ label: `Created through ${state.createdTo}`, clear: () => setParams({ to: '' }) });
    if (state.branchType) out.push({ label: `Branch: ${state.branchType}`, clear: () => setParams({ branch: '' }) });
    state.flag.forEach((f) =>
      out.push({ label: FLAG_LABEL[f] ?? f, clear: () => setParams({ flag: state.flag.filter((x) => x !== f) }) }),
    );
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const toggleIn = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  /**
   * POST /api/memories/bulk: one transaction for delete and relate (anyone with
   * the right on every memory) and quarantine / restore (admins).
   */
  const runBulk = async (body: Parameters<typeof api.bulk>[0], done: string) => {
    const res = await api.bulk(body);
    if (res.errors.length) toast(`${res.errors.length} failed: ${res.errors[0].detail}`, 'err');
    else if (res.done.length) toast(done);
    setSelected(new Set());
    reload();
    refreshCounts();
  };
  const moderate = (action: 'quarantine' | 'restore', targets: string[], done: string, reason?: string) =>
    runBulk({ action, ids: targets, reason }, done);

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
              <span className="lbl g" style={{ fontFamily: 'var(--mh-font-text)' }}>
                <LockIcon size={12} />
                Personal memories: metadata only
              </span>
            </span>
          ) : (
            'Memory browser'
          )
        }
        crumbs={[{ label: isAdmin ? 'Content moderation' : 'Memory browser' }]}
        description={
          isAdmin
            ? 'Search, quarantine, restore and delete memories in the scopes you moderate — as a table or a graph of how they connect. What a personal (user-scope) memory says stays private.'
            : 'Every memory you are allowed to read — your own, and what your projects, campaigns, roles and organization share with you — as a table or a graph of how they connect.'
        }
        actions={
          <>
            {view === 'table' && (
              <a className={`btn ${isAdmin ? 'bs' : 'bg'}`} href={api.exportUrl(params)} download aria-disabled={standby}>
                {isAdmin ? 'Export metadata CSV' : 'Export JSONL'}
              </a>
            )}
            {canWrite && (
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
                  ...(isAdmin ? [
                  { value: 'quarantined', label: 'Quarantined', count: tabCounts?.quarantined ?? null },
                  { value: 'deleted', label: 'Deleted', count: tabCounts?.deleted ?? null },
                  ] : []),
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
              </div>
            </div>
          </div>
        }
      />
      <div className="body">
        {isAdmin && (
          <div className="alert" role="note">
            <LockIcon size={18} />
            <div style={{ flex: '1 1 400px', minWidth: 0 }}>
              <b>Personal memories are private.</b> You read and moderate the {(me?.access?.hidden_scopes ?? []).length ? 'scopes not hidden from you' : 'tenant’s shared scopes'}. User-scope memories show
              metadata only and are left out of search{data?.hidden_scopes?.includes('user') && (facets?.scopes.find((f) => f.value === 'user')?.count ?? 0) > 0
                ? ` (${fmtCompact(facets!.scopes.find((f) => f.value === 'user')!.count)} here)`
                : ''}
              . Only their owner can read them.
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
            <span className="sm muted">The graph uses the same filters and search as the table.</span>
            <button type="button" className="btn bl sm" onClick={() => setParams({ view: '' }, false)}>
              Edit filters
            </button>
          </div>
        )}
        {view === 'graph' ? (
          <MemoryGraph route={{ ...route, params: p }} setParams={setParams} />
        ) : (
        <div className="row-wrap">
          <aside className="card" style={{ flex: '1 1 230px', maxWidth: '100%', padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 20 }} aria-label="Filters">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 data-h="3">Filters</h2>
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
                {!isAdmin && <div>
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
                </div>}
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
                <div className="f">
                  <label htmlFor="maximum-weight">Maximum weight</label>
                  <input id="maximum-weight" className="in" type="number" min={0} max={1} step={0.05}
                    value={state.maxWeight} disabled={filtersDisabled} placeholder="No upper bound"
                    onChange={(e) => setParams({ maxw: e.target.value })} />
                </div>
                <div className="f">
                  <label htmlFor="created-from">Created from (UTC)</label>
                  <input id="created-from" className="in" type="date" value={state.createdFrom}
                    disabled={filtersDisabled} onChange={(e) => setParams({ from: e.target.value })} />
                </div>
                <div className="f">
                  <label htmlFor="created-to">Created through (UTC)</label>
                  <input id="created-to" className="in" type="date" value={state.createdTo}
                    disabled={filtersDisabled} onChange={(e) => setParams({ to: e.target.value })} />
                </div>
                <div className="f">
                  <label htmlFor="branch-type">Has branch type</label>
                  <input id="branch-type" className="in" list="branch-types" value={state.branchType}
                    disabled={filtersDisabled} placeholder="Any branch type"
                    onChange={(e) => setParams({ branch: e.target.value })} />
                  <datalist id="branch-types"><option value="rationale" /><option value="provenance" /><option value="evidence" /></datalist>
                </div>
                <div>
                  <p className="fh">Flags</p>
                  <div className="fx">
                    {(['contradicted', 'has_branches'] as const).map((f) => (
                      <label key={f}>
                        <span>
                          <input type="checkbox" disabled={filtersDisabled} checked={state.flag.includes(f)} onChange={() => setParams({ flag: toggleIn(state.flag, f) })} />{' '}
                          {FLAG_LABEL[f]}
                        </span>
                        {facets.flags[f] !== null && <span className="muted sm">{fmtCompact(facets.flags[f] as number)}</span>}
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
                  placeholder={isAdmin ? 'Search the scopes you moderate' : 'Filter by text'}
                />
              </div>
              {<SelectMenu
                label="Search mode"
                value={state.mode}
                onChange={(v) => setParams({ mode: v === 'text' ? '' : v })}
                options={[
                  { value: 'text', label: 'Text' },
                  { value: 'metadata', label: 'ID or owner' },
                ]}
              />}
              <SelectMenu
                label="Sort"
                prefix="Sort: "
                value={sort}
                onChange={(v) => setParams({ sort: v })}
                options={[
                  { value: 'updated', label: 'Last updated' },
                  { value: 'created', label: 'Created' },
                  { value: 'weight', label: 'Weight' },
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
              </div>
            )}
            {selected.size > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', background: '#e7f1fa', borderTop: '1px solid #b9dafc', borderBottom: '1px solid #b9dafc', padding: '10px 20px', fontSize: 14 }}>
                <b>{selected.size} selected</b>
                {isAdmin ? (
                  <>
                    {state.tab === 'quarantined' ? (
                      <button
                        type="button"
                        className="btn bp"
                        disabled={!selectionCanModerate}
                        title={!selectionCanModerate ? 'Moderation access is required for every selected memory.' : undefined}
                        onClick={() => moderate('restore', ids, `${fmtInt(ids.length)} restored — agents get ${ids.length === 1 ? 'it' : 'them'} again.`).catch((e) => toast(errorMessage(e), 'err'))}
                      >
                        Restore
                      </button>
                    ) : state.tab !== 'deleted' ? (
                      <>
                        <button type="button" className="btn bl" disabled={!selectionCanModerate} title={!selectionCanModerate ? 'Moderation access is required for every selected memory.' : undefined} onClick={() => setModal('quarantine')}>
                          Quarantine
                        </button>
                        <button type="button" className="btn bl danger" disabled={!selectionCanDelete} title={!selectionCanDelete ? 'Delete needs authorship, or project admin, for every selected memory.' : undefined} onClick={() => setModal('delete')}>
                          Delete
                        </button>
                      </>
                    ) : null}
                    {state.tab !== 'deleted' && (
                      <button type="button" className="btn bl" onClick={() => setParams({ view: 'graph', gfocus: 'memory', focus: ids[0] }, false)}>
                        Show in graph
                      </button>
                    )}
                    <span style={{ marginLeft: 'auto' }} className="sm muted">
                      Personal memories stay metadata only · audited
                    </span>
                  </>
                ) : (
                <>
                <button type="button" className="btn bl" disabled={!selectionCanWrite} title={!selectionCanWrite ? 'Write access is required for every selected memory.' : undefined} onClick={() => setModal('relate')}>
                  Add relationship
                </button>
                <button type="button" className="btn bl danger" disabled={!selectionCanDelete} title={!selectionCanDelete ? 'Delete needs authorship, or project admin, for every selected memory.' : undefined} onClick={() => setModal('delete')}>
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
                    <a className="btn bp" href={buildHash(isAdmin ? '/clients' : '/identities', isAdmin ? undefined : { view: 'keys' })}>
                      Connect an agent
                    </a>
                    {canWrite && (
                      <button type="button" className="btn bs" onClick={() => setModal('write')}>
                        Write memory
                      </button>
                    )}
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
                      ? 'Soft-deleted memories stay here, with their version chains, for forensics.'
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
                        {columns.includes('relevant') && <th>Relevant until</th>}
                        {columns.includes('updated') && <th>Updated</th>}
                        <th style={{ width: 40 }}><span className="vh">Actions</span></th>
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
                              <a href={memoryHref(m.id)} className="hidden-box lg link-plain" title="Open the metadata view">
                                <Icon.EyeOff size={18} />
                                {m.scope === 'user' ? 'Personal content hidden' : 'Content hidden'}
                              </a>
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
                              {(m.flags ?? []).map((f) => (
                                <span key={f.label} className={`lbl ${f.kind === 'duplicate' ? 'ylw' : 'red'}`}>
                                  {f.label}
                                </span>
                              ))}
                              {!m.flags?.some((f) => f.kind === 'conflict') && m.open_contradictions > 0 && (
                                <span className="lbl red">{m.open_contradictions === 1 ? 'open contradiction' : `${m.open_contradictions} open contradictions`}</span>
                              )}
                              {m.status === 'quarantined' && !m.flags?.length && <span className="lbl red">quarantined</span>}
                              {m.status !== 'active' && m.status !== 'quarantined' && <span className="lbl g">{m.status}</span>}
                              {!m.is_current && state.tab === 'all' && <span className="lbl g">v{m.version} · superseded</span>}
                              {m.score !== null && <span className="mono muted">score {m.score.toFixed(2)}</span>}
                            </div>
                          </td>
                          {columns.includes('scope') && (
                            <td>
                              {m.redacted ? (
                                <ScopeLabel scope={m.scope}>
                                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                                    <LockIcon size={12} />
                                    {scopeMeta(m.scope).label}
                                  </span>
                                </ScopeLabel>
                              ) : (
                                <ScopeLabel scope={m.scope} />
                              )}
                            </td>
                          )}
                          {columns.includes('entities') && (
                            <td>
                              {m.entities?.length ? (
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
                          {columns.includes('relevant') && (
                            <td className="sm" style={{ whiteSpace: 'nowrap' }} title={m.relevant_until ? new Date(m.relevant_until).toLocaleString() : 'No end date'}>
                              {m.relevant_until ? (
                                <>
                                  {new Date(m.relevant_until).toLocaleDateString()}
                                  {m.temporal_status === 'expired' && <span className="lbl ylw" style={{ marginLeft: 6 }}>Historical</span>}
                                  {m.temporal_status === 'expiring_soon' && <span className="lbl" style={{ marginLeft: 6 }}>Expiring soon</span>}
                                </>
                              ) : (
                                <span className="muted">—</span>
                              )}
                            </td>
                          )}
                          {columns.includes('updated') && (
                            <td className="sm muted" style={{ minWidth: 96 }} title={new Date(m.updated_at).toLocaleString()}>
                              {state.tab === 'deleted' && m.deleted_at ? (
                                <>deleted<br />{fmtRelative(m.deleted_at).toLowerCase()}</>
                              ) : m.version > 1 || new Date(m.updated_at).getTime() - new Date(m.created_at).getTime() > 1000 ? (
                                fmtRelative(m.updated_at)
                              ) : (
                                <>created<br />{fmtRelative(m.created_at).toLowerCase()}</>
                              )}
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
                                  {isAdmin && m.capabilities?.moderate && state.tab !== 'deleted' && (
                                    <>
                                      <hr />
                                      {state.tab === 'quarantined' ? (
                                        <button
                                          type="button"
                                          onClick={() => {
                                            close();
                                            moderate('restore', [m.id], 'Memory restored.').catch((e) => toast(errorMessage(e), 'err'));
                                          }}
                                        >
                                          Restore
                                        </button>
                                      ) : (
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
                                    </>
                                  )}
                                  {state.tab !== 'deleted' && m.can_delete && (
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

      {modal === 'write' && (
        <WriteMemoryModal
          onClose={() => setModal(null)}
          onSaved={() => reload()}
          initialScope={isAdmin ? 'organizational' : undefined}
        />
      )}
      {modal === 'relate' && <RelationshipModal sourceIds={ids} onClose={() => setModal(null)} onDone={reload} />}
      {modal === 'quarantine' && (
        <ConfirmModal
          title={`Quarantine ${ids.length} ${ids.length === 1 ? 'memory' : 'memories'}?`}
          confirmLabel="Quarantine"
          danger
          onClose={() => setModal(null)}
          onConfirm={async () => {
            await moderate('quarantine', ids, `${fmtInt(ids.length)} quarantined — agents stop receiving ${ids.length === 1 ? 'it' : 'them'}.`, qReason.trim() || undefined);
            setQReason('');
          }}
        >
          Agents stop receiving {ids.length === 1 ? 'it' : 'them'} at once. Quarantined memories wait in the Quarantined tab, where a moderator restores them. Audited.
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
          receiving {rowDelete ? 'it' : 'them'} immediately; the rows are kept for forensics. The action is recorded in the audit log.
          {!rowDelete && undeletable > 0 && (
            <div className="alert warn-a" style={{ marginTop: 12 }}>
              {fmtInt(undeletable)} of them {undeletable === 1 ? 'was' : 'were'} written by someone else and will be skipped: only the author or a project admin can delete a shared memory.
            </div>
          )}
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

/** Who you are browsing as and which project — R1-022: the active scope is always visible. */
const ScopeBar: React.FC<{ project: string; onProject: (v: string) => void; tenant: string }> = ({ project, onProject, tenant }) => {
  const { me } = useApp();
  if (!me) return null;
  const projects = me.write?.project_ids ?? [];
  return (
    <div className="scopebar" role="region" aria-label="Active scope">
      <span>
        <span className="hint">Signed in as</span> <b className="mono">{me.username}</b>
      </span>
      <span>
        <span className="hint">Tenant</span> <b className="mono">{tenant || '—'}</b>
      </span>
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <label className="hint" htmlFor="scope-project">
          Project
        </label>
        <select id="scope-project" className="in auto" value={project} onChange={(e) => onProject(e.target.value)}>
          <option value="">All my projects ({projects.length})</option>
          {projects.map((p) => (
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
