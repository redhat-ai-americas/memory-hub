import React, { useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Modal, Pager, ScopeLabel, Sk, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { AuditEvent, MemoryContext, MemorySource, MemoryUsage } from '@/types';
import { errorMessage, fmtDateTime, fmtMonthDay, fmtRelative, fmtShortDateTime, fmtUtc, fmtWeight, scopeMeta, shortId, truncate } from '@/utils/format';
import { actorName, ConfirmModal, decisionOf, memoryHref, MemoryLink, RelationshipModal } from './common';

type Version = MemoryContext['versions'][number];

/** Minimal line diff (LCS) between two versions' content. */
const lineDiff = (a: string, b: string): { kind: 'same' | 'del' | 'add'; text: string }[] => {
  const x = a.split('\n');
  const y = b.split('\n');
  const dp = Array.from({ length: x.length + 1 }, () => new Array<number>(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i -= 1)
    for (let j = y.length - 1; j >= 0; j -= 1) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { kind: 'same' | 'del' | 'add'; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) {
      out.push({ kind: 'same', text: x[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ kind: 'del', text: x[i++] });
    else out.push({ kind: 'add', text: y[j++] });
  }
  while (i < x.length) out.push({ kind: 'del', text: x[i++] });
  while (j < y.length) out.push({ kind: 'add', text: y[j++] });
  return out;
};

const changeSummary = (v: Version, prev?: Version): string => {
  if (!prev) return 'Initial write';
  const parts: string[] = [];
  if (prev.content !== v.content) {
    if (v.content.startsWith(prev.content.replace(/\.$/, ''))) {
      const added = v.content.slice(prev.content.replace(/\.$/, '').length).replace(/^[;,.\s]+/, '').replace(/\.$/, '');
      parts.push(added ? `Added “${truncate(added, 60)}”` : 'Content edited');
    } else parts.push('Content rewritten');
  }
  if (prev.weight !== v.weight) parts.push(`Weight ${fmtWeight(prev.weight)} → ${fmtWeight(v.weight)}`);
  return parts.join(' · ') || 'Metadata updated';
};

const who = (actor: string | null, driver: string | null, owner: string) => {
  const a = actor || owner;
  if (driver && driver !== a) return `${a} (${driver})`;
  return a;
};

const MemoryDetail: React.FC<{ route: HashRoute }> = ({ route }) => {
  const id = decodeURIComponent(route.path.replace(/^\/memory\//, ''));
  const tab = route.params.get('tab') || 'details';
  const toast = useToast();
  const { refreshCounts, role } = useApp();
  const [restoring, setRestoring] = useState(false);
  const { data, error, loading, reload } = useApi<MemoryContext>(() => api.memoryContext(id), [id]);
  const [modal, setModal] = useState<null | 'contradiction' | 'branch' | 'edit' | 'delete' | 'relate'>(null);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const [compare, setCompare] = useState<{ from: string; to: string } | null>(null);
  const [showAllReports, setShowAllReports] = useState(false);

  const setTab = (t: string) => navigate(`/memory/${id}`, t === 'details' ? undefined : { tab: t }, { replace: true });

  const versions = data?.versions ?? [];
  const byVersion = useMemo(() => [...versions].sort((a, b) => a.version - b.version), [versions]);
  const current = byVersion.find((v) => v.id === (selectedVersion ?? data?.memory.id)) ?? byVersion[byVersion.length - 1];
  const diffPair = useMemo(() => {
    if (compare) {
      const from = versions.find((v) => v.id === compare.from);
      const to = versions.find((v) => v.id === compare.to);
      return from && to ? [from, to] : null;
    }
    if (!current) return null;
    const idx = byVersion.findIndex((v) => v.id === current.id);
    return idx > 0 ? [byVersion[idx - 1], current] : null;
  }, [compare, current, byVersion, versions]);

  if (error && !data) {
    return (
      <>
        <PageHeader title="Memory" crumbs={[{ label: 'Memory browser', href: buildHash('/memories') }, { label: shortId(id) }]} />
        <div className="body">
          <div className="card">
            {(error as { status?: number }).status === 404 ? (
              <Empty title="Memory not found" action={<a className="btn bs" href={buildHash('/memories')}>Back to the memory browser</a>}>
                It may have been deleted, or it belongs to another tenant.
              </Empty>
            ) : (
              <ErrorState error={error} onRetry={reload} />
            )}
          </div>
        </div>
      </>
    );
  }

  const m = data?.memory;
  const unresolved = data?.contradictions.filter((c) => !c.resolved) ?? [];
  const threshold = data?.contradiction_threshold ?? 5;
  const deleted = Boolean(m?.deleted_at);

  return (
    <>
      <PageHeader
        long
        topAlign
        crumbs={[
          { label: 'Memory browser', href: buildHash('/memories') },
          { label: <span className="mono">{shortId(id)}</span> },
        ]}
        title={m ? m.content.length > 160 ? truncate(m.content, 160) : m.content : <Sk w={480} h={28} />}
        below={
          m ? (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <ScopeLabel scope={m.scope}>{scopeMeta(m.scope).label} scope</ScopeLabel>
              <span className="lbl g">
                v{m.version} · {deleted ? 'deleted' : m.is_current ? 'current' : 'superseded'}
              </span>
              <span className="lbl g">Weight {fmtWeight(m.weight)}</span>
              {m.status !== 'active' && <span className="lbl ylw">{m.status}</span>}
              {unresolved.length > 0 && (
                <span className="lbl s-role">
                  ⚠ {unresolved.length} contradiction{unresolved.length === 1 ? '' : 's'} · threshold {threshold}
                </span>
              )}
              <span className="sm muted">
                Owner <b>{m.scope_id ?? m.owner_id}</b>
                {m.actor_id && m.actor_id !== m.owner_id && (
                  <>
                    {' '}
                    · written by <b>{m.actor_id}</b>
                  </>
                )}{' '}
                · updated {fmtRelative(m.updated_at).toLowerCase()}
              </span>
            </div>
          ) : null
        }
        actions={
          m && deleted && (role !== 'admin' || !m.redacted) ? (
            <button
              type="button"
              className="btn bp"
              disabled={restoring}
              onClick={async () => {
                setRestoring(true);
                try {
                  const res = await api.restoreMemory(m.id);
                  toast(`Restored ${res.restored_rows} ${res.restored_rows === 1 ? 'row' : 'rows'} — agents get it again.`);
                  refreshCounts();
                  if (res.id !== m.id) navigate(`/memory/${res.id}`);
                  else reload();
                } catch (e) {
                  toast(errorMessage(e), 'err');
                } finally {
                  setRestoring(false);
                }
              }}
            >
              {restoring ? 'Restoring…' : 'Restore memory'}
            </button>
          ) : m && !deleted ? (
            <>
              <button type="button" className="btn bg" onClick={() => setModal('contradiction')}>
                Report contradiction
              </button>
              <button type="button" className="btn bs" onClick={() => setModal('branch')}>
                Add branch
              </button>
              <button type="button" className="btn bp" disabled={!m.is_current} onClick={() => setModal('edit')}>
                Edit · new version
              </button>
              <button type="button" className="btn bd outline" aria-label="Delete memory" onClick={() => setModal('delete')}>
                Delete
              </button>
            </>
          ) : undefined
        }
        tabs={
          <Tabs
            label="Memory sections"
            value={tab}
            onChange={(t) => (t === 'relationships' ? navigate('/graph', { focus: id }) : setTab(t))}
            tabs={[
              { value: 'details', label: 'Details' },
              { value: 'versions', label: 'Versions', count: data ? versions.length : null },
              { value: 'branches', label: 'Branches', count: data ? data.branches.length : null },
              { value: 'relationships', label: 'Relationships', count: data ? data.relationships.length : null },
              { value: 'access', label: 'Access log', count: data ? data.access_count : null },
            ]}
          />
        }
      />
      <div className="body">
        {loading && !data ? (
          <div className="row-wrap">
            <div className="col-main">
              {[0, 1, 2].map((k) => (
                <div className="card" key={k}>
                  <SkLines lines={4} />
                </div>
              ))}
            </div>
            <div className="col-side" style={{ flex: '1 1 320px' }}>
              <div className="card">
                <SkLines lines={8} />
              </div>
            </div>
          </div>
        ) : data && m ? (
          tab === 'access' ? (
            <AccessLog id={id} />
          ) : (
            <div className="row-wrap">
              <div className="col-main">
                {(tab === 'details' || tab === 'versions') && (
                  <div className="card">
                    <div className="ch">
                      <h3>Version history</h3>
                      {byVersion.length > 1 && (
                        <button
                          type="button"
                          className="btn bl sm"
                          onClick={() =>
                            setCompare(compare ? null : { from: byVersion[0].id, to: byVersion[byVersion.length - 1].id })
                          }
                        >
                          {compare ? 'Done comparing' : 'Compare versions'}
                        </button>
                      )}
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
                      <div className="tl" style={{ flex: '1 1 240px' }}>
                        {[...byVersion].reverse().map((v, i, arr) => {
                          const prev = byVersion[byVersion.indexOf(v) - 1];
                          const last = i === arr.length - 1;
                          return (
                            <div key={v.id} className={`tli ${current?.id === v.id && !compare ? 'is-sel' : ''}`} style={last ? { paddingBottom: 0 } : undefined}>
                              {!last && <span className="ln" />}
                              <span className={`pin ${v.is_current ? '' : 'old'}`} />
                              <button type="button" onClick={() => { setCompare(null); setSelectedVersion(v.id); }} aria-label={`Show version ${v.version}`}>
                                <div>
                                  <div style={{ fontWeight: 600 }}>
                                    v{v.version}
                                    {v.is_current ? ' · current' : v.version === 1 ? ' · created' : ''}
                                  </div>
                                  <div className="sm muted">
                                    {fmtShortDateTime(v.created_at)} · {who(v.actor_id, v.driver_id, v.owner_id)}
                                  </div>
                                  <div className="sm">{changeSummary(v, prev)}</div>
                                </div>
                              </button>
                            </div>
                          );
                        })}
                      </div>
                      <div style={{ flex: '2 1 320px', minWidth: 0 }}>
                        {compare && (
                          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }} className="sm">
                            <select className="in auto" aria-label="From version" value={compare.from} onChange={(e) => setCompare({ ...compare, from: e.target.value })}>
                              {byVersion.map((v) => (
                                <option key={v.id} value={v.id}>
                                  v{v.version}
                                </option>
                              ))}
                            </select>
                            →
                            <select className="in auto" aria-label="To version" value={compare.to} onChange={(e) => setCompare({ ...compare, to: e.target.value })}>
                              {byVersion.map((v) => (
                                <option key={v.id} value={v.id}>
                                  v{v.version}
                                </option>
                              ))}
                            </select>
                          </div>
                        )}
                        {diffPair ? (
                          <>
                            {!compare && (
                              <div className="sm muted" style={{ marginBottom: 8 }}>
                                v{diffPair[0].version} → v{diffPair[1].version}
                              </div>
                            )}
                            <div className="diff">
                              {diffPair[0].content === diffPair[1].content ? (
                                <div className="same">Content unchanged{diffPair[0].weight !== diffPair[1].weight ? ` · weight ${fmtWeight(diffPair[0].weight)} → ${fmtWeight(diffPair[1].weight)}` : ''}</div>
                              ) : (
                                lineDiff(diffPair[0].content, diffPair[1].content).map((l, i) => (
                                  <div key={i} className={l.kind}>
                                    {l.kind === 'del' ? '− ' : l.kind === 'add' ? '+ ' : '  '}
                                    {l.text}
                                  </div>
                                ))
                              )}
                            </div>
                          </>
                        ) : (
                          <div className="diff">
                            <div className="same">{current?.content}</div>
                          </div>
                        )}
                        <p className="sm muted" style={{ margin: '10px 0 0' }}>
                          Old versions stay readable for forensics; agents only receive the current version.
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {(tab === 'details' || tab === 'branches') && (
                  <div className="card">
                    <div className="ch">
                      <h3>Branches</h3>
                      <span className="sm muted">Child nodes that explain or support this memory</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                      {data.branches.length === 0 && <p className="sm muted" style={{ margin: 0 }}>No branches yet.</p>}
                      {data.branches.map((b) => (
                        <div className="br" key={b.id}>
                          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                            <span className="lbl g">{b.branch_type ?? 'branch'}</span>
                            <span className="sm muted">
                              {b.actor_id} · {fmtMonthDay(b.created_at)}
                            </span>
                          </div>
                          {b.content}
                        </div>
                      ))}
                      {!deleted && (
                        <button type="button" className="btn bl" style={{ alignSelf: 'flex-start' }} onClick={() => setModal('branch')}>
                          + Add provenance, evidence or description branch
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {tab === 'details' && (
                  <div className="card">
                    <div className="ch">
                      <h3>Relationships</h3>
                      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                        {!deleted && (
                          <button type="button" className="btn bl sm" onClick={() => setModal('relate')}>
                            + Add relationship
                          </button>
                        )}
                        <a className="sm" href={buildHash('/graph', { focus: id })}>
                          Open in graph
                        </a>
                      </div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 14 }}>
                      {data.relationships.length === 0 && <p className="sm muted" style={{ margin: 0 }}>No relationships yet.</p>}
                      {data.relationships.map((r) => (
                        <div className="relrow" key={r.id}>
                          <span className="mono" style={{ width: 130 }}>
                            {r.direction === 'out' ? '→' : '←'} {r.type}
                          </span>
                          <ScopeLabel scope={r.other.scope} />
                          <MemoryLink id={r.other.id} style={{ flex: 1, minWidth: 200 }}>
                            {r.other.stub}
                            {!r.other.is_current ? ` (v${r.other.version}, retired)` : ''}
                          </MemoryLink>
                        </div>
                      ))}
                      {data.relationships_omitted > 0 && (
                        <div className="sm muted" style={{ paddingTop: 6 }}>
                          {data.relationships_omitted} relationship{data.relationships_omitted === 1 ? '' : 's'} hidden — points to a memory outside your access
                          (omitted_count = {data.relationships_omitted}).
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <aside className="col-side" style={{ flex: '1 1 320px' }}>
                {deleted && (
                  <div className="alert" role="note">
                    <div>
                      <b>Deleted {fmtRelative(m.deleted_at as string).toLowerCase()}.</b> Agents no longer receive it.
                      {role !== 'admin' || !m.redacted ? ' Restore brings back every version deleted with it and makes the newest one current.' : ''}
                    </div>
                  </div>
                )}
                <SourceCard id={m.id} />
                <UsageCard id={m.id} />
                <div className="card">
                  <h3 style={{ marginBottom: 14 }}>Details</h3>
                  <dl className="dl">
                    <dt>ID</dt>
                    <dd className="mono">{m.id}</dd>
                    <dt>Scope</dt>
                    <dd>
                      {m.scope} · owner {m.scope_id ?? m.owner_id}
                    </dd>
                    <dt>Tenant</dt>
                    <dd className="mono">{m.tenant_id}</dd>
                    <dt>Written by</dt>
                    <dd>{who(m.actor_id, m.driver_id, m.owner_id)}</dd>
                    <dt>Created</dt>
                    <dd>{fmtDateTime(byVersion[0]?.created_at ?? m.created_at)}</dd>
                    <dt>Domains</dt>
                    <dd>{m.domains.length ? m.domains.join(', ') : '—'}</dd>
                    <dt>Type</dt>
                    <dd>
                      {m.content_type}
                      {m.source ? ` · ${m.source}` : ''}
                    </dd>
                    <dt>Embedding</dt>
                    <dd>{m.embedding_dims ? `${m.embedding_dims}-dim` : 'Not embedded'}</dd>
                    <dt>Injection</dt>
                    <dd>
                      {m.injection === 'full'
                        ? `Full content (weight ≥ ${m.full_content_threshold.toFixed(1)})`
                        : `Stub only (weight < ${m.full_content_threshold.toFixed(1)})`}
                    </dd>
                  </dl>
                  {m.metadata && Object.keys(m.metadata).length > 0 && (
                    <>
                      <div className="sm" style={{ fontWeight: 600, margin: '16px 0 8px' }}>
                        Metadata
                      </div>
                      <pre>{JSON.stringify(m.metadata, null, 2)}</pre>
                    </>
                  )}
                </div>

                <div className="card">
                  <div className="ch">
                    <h3>Contradictions</h3>
                    <a className="sm" href={buildHash('/review', { tab: 'contradictions' })}>
                      Review
                    </a>
                  </div>
                  <div className="sm" style={{ marginBottom: 8 }}>
                    <b>
                      {unresolved.length} of {threshold}
                    </b>{' '}
                    reports before a revision prompt
                  </div>
                  <div className="bar" style={{ marginBottom: 14 }}>
                    <span style={{ width: `${Math.min(100, (unresolved.length / threshold) * 100)}%`, background: '#ca6c0f' }} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14 }}>
                    {unresolved.length === 0 && <span className="sm muted">No open reports.</span>}
                    {(showAllReports ? unresolved : unresolved.slice(0, 2)).map((c) => (
                      <div className="br" key={c.id}>
                        “{c.observed_behavior}”
                        <div className="sm muted" style={{ marginTop: 4 }}>
                          {c.reporter} · confidence {c.confidence.toFixed(1)} · {fmtMonthDay(c.created_at)}
                        </div>
                      </div>
                    ))}
                    {unresolved.length > 2 && (
                      <button type="button" className="link-btn sm" style={{ alignSelf: 'flex-start' }} onClick={() => setShowAllReports((s) => !s)}>
                        {showAllReports ? 'Show fewer' : `Show ${unresolved.length - 2} more`}
                      </button>
                    )}
                  </div>
                </div>

                <div className="card">
                  <h3 style={{ marginBottom: 12 }}>Similar memories</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14 }}>
                    {data.similar.length === 0 && <span className="sm muted">{m.embedding_dims ? 'No close neighbours.' : 'This memory has no embedding.'}</span>}
                    {data.similar.map((s) => (
                      <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                        <a href={memoryHref(s.id)}>{truncate(s.stub, 48)}</a>
                        <span className="mono">{s.score.toFixed(2)}</span>
                      </div>
                    ))}
                    {data.similar.length > 0 && !deleted && (
                      <button type="button" className="btn bs" style={{ alignSelf: 'flex-start', marginTop: 4 }} onClick={() => setModal('relate')}>
                        Suggest merge
                      </button>
                    )}
                  </div>
                </div>
              </aside>
            </div>
          )
        ) : null}
      </div>

      {modal === 'contradiction' && <ContradictionModal id={id} onClose={() => setModal(null)} onDone={reload} />}
      {modal === 'branch' && <BranchModal id={id} onClose={() => setModal(null)} onDone={reload} />}
      {modal === 'edit' && m && (
        <EditModal
          id={id}
          content={m.content}
          weight={m.weight}
          domains={m.domains}
          onClose={() => setModal(null)}
          onDone={(newId) => {
            toast('New version created.');
            navigate(`/memory/${newId}`);
          }}
        />
      )}
      {modal === 'relate' && <RelationshipModal sourceIds={[id]} onClose={() => setModal(null)} onDone={reload} />}
      {modal === 'delete' && m && (
        <ConfirmModal
          title="Delete memory?"
          confirmLabel="Delete"
          danger
          onClose={() => setModal(null)}
          onConfirm={async () => {
            const res = await api.bulk({ action: 'delete', ids: [id] });
            if (res.errors.length) throw new Error(res.errors[0].detail);
            const f = res.forgotten?.[0];
            toast(
              f
                ? `Forgot it — ${f.versions} ${f.versions === 1 ? 'version' : 'versions'}${f.branches ? ` and ${f.branches} branches` : ''} in ${f.scope} · ${f.scope_id ?? f.owner_id}. Restore from the Deleted tab.`
                : 'Memory deleted.',
            );
            refreshCounts();
            navigate('/memories');
          }}
        >
          This soft-deletes <b>“{truncate(m.content, 80)}”</b>, all {versions.length} version{versions.length === 1 ? '' : 's'} and {data?.branches.length ?? 0}{' '}
          branch{data?.branches.length === 1 ? '' : 'es'}. Agents stop receiving it immediately. The deletion is recorded in the audit log.
        </ConfirmModal>
      )}
    </>
  );
};

const AccessLog: React.FC<{ id: string }> = ({ id }) => {
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useApi<{ total: number; items: AuditEvent[] }>(() => api.memoryAccessLog(id, page), [id, page]);
  return (
    <section className="card" style={{ padding: 0 }}>
      <div style={{ padding: '16px 20px' }}>
        <h3>Access log</h3>
      </div>
      {error && !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : loading && !data ? (
        <SkLines lines={5} />
      ) : data!.items.length === 0 ? (
        <Empty title="No recorded access" compact>
          Reads, searches and updates touching this memory will appear here.
        </Empty>
      ) : (
        <>
          <div className="scroll">
            <table className="tbl" style={{ minWidth: 720 }}>
              <thead>
                <tr>
                  <th>Timestamp (UTC)</th>
                  <th>Operation</th>
                  <th>Actor</th>
                  <th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {data!.items.map((e) => {
                  const d = decisionOf(e);
                  return (
                    <tr key={e.id}>
                      <td className="mono muted">{fmtUtc(e.timestamp)}</td>
                      <td className="mono">{e.operation}</td>
                      <td className="sm">{actorName(e)}</td>
                      <td className={`sm ${d.cls}`} style={{ fontWeight: 600 }}>
                        {d.label}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pager page={page} perPage={25} total={data!.total} onPage={setPage} noun="events" />
        </>
      )}
    </section>
  );
};

const ContradictionModal: React.FC<{ id: string; onClose: () => void; onDone: () => void }> = ({ id, onClose, onDone }) => {
  const toast = useToast();
  const [text, setText] = useState('');
  const [confidence, setConfidence] = useState(0.7);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Modal
      title="Report contradiction"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy || !text.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                const res = await api.reportContradiction(id, { observed_behavior: text.trim(), confidence });
                toast(`Contradiction logged · ${res.unresolved} open on this memory.`);
                onDone();
                onClose();
              } catch (e) {
                setErr(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Report
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="cb">Observed behaviour</label>
        <textarea id="cb" className="in" value={text} onChange={(e) => setText(e.target.value)} placeholder="What did the user do that conflicts with this memory?" />
      </div>
      <div className="f">
        <label htmlFor="cc">Confidence · {confidence.toFixed(2)}</label>
        <input id="cc" type="range" min={0} max={100} value={Math.round(confidence * 100)} onChange={(e) => setConfidence(Number(e.target.value) / 100)} />
      </div>
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

const BranchModal: React.FC<{ id: string; onClose: () => void; onDone: () => void }> = ({ id, onClose, onDone }) => {
  const toast = useToast();
  const [type, setType] = useState('rationale');
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Modal
      title="Add branch"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy || !content.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                await api.addBranch(id, { branch_type: type, content: content.trim() });
                toast('Branch added.');
                onDone();
                onClose();
              } catch (e) {
                setErr(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Add branch
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="bt">Branch type</label>
        <select id="bt" className="in" value={type} onChange={(e) => setType(e.target.value)}>
          {['rationale', 'provenance', 'evidence', 'description'].map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </div>
      <div className="f">
        <label htmlFor="bc">Content</label>
        <textarea id="bc" className="in" value={content} onChange={(e) => setContent(e.target.value)} />
      </div>
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

const EditModal: React.FC<{
  id: string;
  content: string;
  weight: number;
  domains: string[];
  onClose: () => void;
  onDone: (newId: string) => void;
}> = ({ id, content: initial, weight: initialWeight, domains: initialDomains, onClose, onDone }) => {
  const [content, setContent] = useState(initial);
  const [weight, setWeight] = useState(initialWeight);
  const [domains, setDomains] = useState(initialDomains.join(', '));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const domainList = domains.split(',').map((d) => d.trim()).filter(Boolean);
  const changed = content !== initial || weight !== initialWeight || domainList.join(',') !== initialDomains.join(',');
  return (
    <Modal
      title="Edit · new version"
      wide
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy || !changed || !content.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                const res = await api.newVersion(id, {
                  content: content !== initial ? content.trim() : undefined,
                  weight: weight !== initialWeight ? weight : undefined,
                  domains: domainList.join(',') !== initialDomains.join(',') ? domainList : undefined,
                });
                onDone(res.id);
                onClose();
              } catch (e) {
                setErr(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? 'Saving…' : 'Save as new version'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="ec">Content</label>
        <textarea id="ec" className="in" style={{ minHeight: 120 }} value={content} onChange={(e) => setContent(e.target.value)} />
      </div>
      <div className="f">
        <label htmlFor="ew">Weight · {weight.toFixed(2)}</label>
        <input id="ew" type="range" min={0} max={100} value={Math.round(weight * 100)} onChange={(e) => setWeight(Number(e.target.value) / 100)} />
      </div>
      <div className="f">
        <label htmlFor="ed">Domain tags</label>
        <input id="ed" className="in" value={domains} onChange={(e) => setDomains(e.target.value)} />
      </div>
      <span className="hint">The current version is kept for forensics; agents receive the new version from now on.</span>
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

export default MemoryDetail;

/** Do agents act on this memory when search returns it? From the audit log. */
const UsageCard: React.FC<{ id: string }> = ({ id }) => {
  const { data } = useApi<MemoryUsage>(() => api.memoryUsage(id, 30), [id]);
  if (!data) return null;
  const measured = data.used + data.skipped;
  return (
    <div className="card">
      <div className="ch">
        <h3>Agent usage</h3>
        <span className="sm muted">30 days</span>
      </div>
      {data.served === 0 ? (
        <p className="sm muted" style={{ margin: 0 }}>
          No agent search returned this memory in the last 30 days.
        </p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginBottom: 10 }}>
            <div>
              <div className="b6" style={{ fontSize: 22 }}>{data.served}</div>
              <div className="hint">times returned</div>
            </div>
            <div>
              <div className="b6" style={{ fontSize: 22 }}>{data.used}</div>
              <div className="hint">acted on</div>
            </div>
            <div>
              <div className="b6" style={{ fontSize: 22 }}>{data.skipped}</div>
              <div className="hint">skipped</div>
            </div>
          </div>
          {measured > 0 && (
            <div className="bar" aria-label={`Used ${Math.round((data.use_rate ?? 0) * 100)}% of the time`}>
              <span style={{ width: `${Math.round((data.use_rate ?? 0) * 100)}%` }} />
            </div>
          )}
          <p className="hint" style={{ margin: '8px 0 0' }}>
            {data.full_text
              ? 'Weight ≥ 0.80: agents get the full text in the search result, so a follow-up read is not needed and skips are not counted.'
              : 'Acted on = the same agent read, updated, linked or reported it within 30 minutes. Memories that are often skipped may need a clearer text, a lower weight, or fading.'}
          </p>
        </>
      )}
    </div>
  );
};

/** The document passage this memory was written from, if any. */
const SourceCard: React.FC<{ id: string }> = ({ id }) => {
  const { data } = useApi<MemorySource>(() => api.memorySource(id), [id]);
  if (!data?.linked) return null;
  return (
    <div className="card">
      <div className="ch">
        <h3>Source</h3>
        {data.status && data.status !== 'ok' && <span className={`lbl ${data.status === 'changed' ? 'ylw' : 'blue'}`}>{data.status === 'changed' ? 'source changed' : 'moved'}</span>}
      </div>
      {data.redacted ? (
        <p className="sm muted" style={{ margin: 0 }}>
          Written from a document. Its text is confidential.
        </p>
      ) : data.document_deleted ? (
        <p className="sm muted" style={{ margin: 0 }}>
          Written from a document that has been deleted. The passage was: “{data.snippet}”
        </p>
      ) : (
        <>
          <div className="sm b6" style={{ marginBottom: 6 }}>
            {data.document_id ? <a href={buildHash(`/knowledge/documents/${data.document_id}`)}>{data.title}</a> : data.title} · v{data.version}
          </div>
          <blockquote className="srcq">
            <span className="muted">{data.before ? `…${data.before.slice(-140)}` : ''}</span>
            <mark>{data.passage}</mark>
            <span className="muted">{data.after ? `${data.after.slice(0, 140)}…` : ''}</span>
          </blockquote>
          {data.status === 'changed' && (
            <p className="hint warn" style={{ margin: '8px 0 0' }}>
              This passage is no longer in version {data.version} of the document (linked from v{data.linked_version}). Check whether the memory still holds.
            </p>
          )}
        </>
      )}
    </div>
  );
};
