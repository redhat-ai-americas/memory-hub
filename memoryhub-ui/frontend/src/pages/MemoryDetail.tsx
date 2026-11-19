import React, { useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Modal, ScopeLabel, Sk, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { MemoryContext } from '@/types';
import { errorMessage, fmtDateTime, fmtMonthDay, fmtRelative, fmtShortDateTime, fmtWeight, scopeMeta, shortId, truncate } from '@/utils/format';
import { ConfirmModal, memoryHref, MemoryLink, RelationshipModal } from './common';

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
  // /history carries no weight per version; only compare weights we know.
  if (Number.isFinite(prev.weight) && Number.isFinite(v.weight) && prev.weight !== v.weight) parts.push(`Weight ${fmtWeight(prev.weight)} → ${fmtWeight(v.weight)}`);
  return parts.join(' · ') || 'New version';
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
  const userView = role === 'user';
  const { data, error, loading, reload } = useApi<MemoryContext>(() => api.memoryContext(id), [id]);
  const [modal, setModal] = useState<null | 'contradiction' | 'branch' | 'edit' | 'delete' | 'relate' | 'quarantine' | 'restore'>(null);
  const [qReason, setQReason] = useState('');
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
  const threshold = data?.contradiction_threshold ?? 5;
  const unresolved = (data?.contradictions ?? []).filter((c) => !c.resolved);
  const deleted = Boolean(m?.deleted_at);
  const canWrite = Boolean(m?.capabilities?.write);
  /** #671: authors (and project admins) delete; moderation alone is not enough for shared memories. */
  const canDelete = Boolean(m?.can_delete);
  /** Admin moderation (POST /api/memories/bulk with one id): quarantine an active memory, restore a quarantined one. */
  const canModerate = !userView && Boolean(m?.capabilities?.moderate) && !deleted;
  /** The BFF blanks what a personal memory says for admins; show that instead of an empty page. */
  const hidden = Boolean(m?.redacted);

  return (
    <>
      <PageHeader
        long
        topAlign
        crumbs={[
          { label: 'Memory browser', href: buildHash('/memories') },
          { label: <span className="mono">{shortId(id)}</span> },
        ]}
        title={
          m ? (
            hidden ? (
              <span className="muted">{m.scope === 'user' ? 'Personal memory · content hidden' : 'Content hidden'}</span>
            ) : m.content.length > 160 ? (
              truncate(m.content, 160)
            ) : (
              m.content
            )
          ) : (
            <Sk w={480} h={28} />
          )
        }
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
          m && !deleted ? (
            <>
              {canWrite && (
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
                </>
              )}
              {canModerate && m.status === 'active' && (
                <button type="button" className="btn bd outline" onClick={() => setModal('quarantine')}>
                  Quarantine
                </button>
              )}
              {canModerate && m.status === 'quarantined' && (
                <button type="button" className="btn bs" onClick={() => setModal('restore')}>
                  Restore
                </button>
              )}
              {canDelete && !userView && (
                <button type="button" className="btn bd outline" onClick={() => setModal('delete')}>
                  Delete memory
                </button>
              )}
            </>
          ) : undefined
        }
        tabs={
          <Tabs
            label="Memory sections"
            value={tab}
            onChange={(t) => (t === 'relationships' ? navigate('/memories', { view: 'graph', gfocus: 'memory', focus: id, sel: id }) : setTab(t))}
            tabs={[
              { value: 'details', label: 'Details' },
              { value: 'versions', label: 'Versions', count: data ? versions.length : null },
              { value: 'branches', label: 'Branches', count: data ? data.branches.length : null },
              { value: 'relationships', label: 'Relationships', count: data ? data.relationships.length : null },
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
        ) : data && m && userView && tab === 'details' ? (
          <UserMemoryView data={data} byVersion={byVersion} canWrite={canWrite} canDelete={canDelete} deleted={deleted} onDelete={() => setModal('delete')} onRelate={() => setModal('relate')} />
        ) : data && m ? (
          (
            <div className="row-wrap">
              <div className="col-main">
                {hidden && (
                  <div className="alert" role="note">
                    <b>{m.scope === 'user' ? 'Personal memory.' : 'Content hidden.'}</b> What it says is private to its owner, so versions and branches below show
                    metadata only: who changed it, when and with what weight.
                  </div>
                )}
                {(tab === 'details' || tab === 'versions') && (
                  <div className="card">
                    <div className="ch">
                      <h2 data-h="3">Version history</h2>
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
                                  <div className="sm">{hidden ? (prev && prev.weight !== v.weight ? `weight ${fmtWeight(prev.weight)} → ${fmtWeight(v.weight)}` : <span className="muted">content hidden</span>) : changeSummary(v, prev)}</div>
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
                        {hidden ? (
                          <div className="diff">
                            <div className="same">Content hidden</div>
                          </div>
                        ) : diffPair ? (
                          <>
                            {!compare && (
                              <div className="sm muted" style={{ marginBottom: 8 }}>
                                v{diffPair[0].version} → v{diffPair[1].version}
                              </div>
                            )}
                            <div className="diff">
                              {diffPair[0].content === diffPair[1].content ? (
                                <div className="same">Content unchanged{Number.isFinite(diffPair[0].weight) && Number.isFinite(diffPair[1].weight) && diffPair[0].weight !== diffPair[1].weight ? ` · weight ${fmtWeight(diffPair[0].weight)} → ${fmtWeight(diffPair[1].weight)}` : ''}</div>
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
                      <h2 data-h="3">Branches</h2>
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
                          {hidden || !b.content ? <span className="sm muted">Content hidden</span> : b.content}
                        </div>
                      ))}
                      {!deleted && canWrite && (
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
                      <h2 data-h="3">Relationships</h2>
                      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                        {!deleted && canWrite && (
                          <button type="button" className="btn bl sm" onClick={() => setModal('relate')}>
                            + Add relationship
                          </button>
                        )}
                        <a className="sm" href={buildHash('/memories', { view: 'graph', gfocus: 'memory', focus: id, sel: id })}>
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
                    </div>
                  </div>
                )}
              </div>

              <aside className="col-side" style={{ flex: '1 1 320px' }}>
                <div className="card">
                  <h2 data-h="3" style={{ marginBottom: 14 }}>Details</h2>
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
                    <dt>Upstream trust</dt>
                    <dd>{m.upstream_trust_level ?? 'Not recorded'}</dd>
                    <dt>Relevant until</dt>
                    <dd>{m.relevant_until ? fmtDateTime(m.relevant_until) : 'No semantic expiry'}</dd>
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
                    <h2 data-h="3">Contradictions</h2>
                    {role === 'admin' && (
                      <a className="sm" href={buildHash('/review', { memory: id })}>
                        Review
                      </a>
                    )}
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
                  <h2 data-h="3" style={{ marginBottom: 12 }}>Similar memories</h2>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14 }}>
                    {data.similar.length === 0 && <span className="sm muted">{m.embedding_dims ? 'No close neighbours.' : 'This memory has no embedding.'}</span>}
                    {data.similar.map((s) => (
                      <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                        <a href={memoryHref(s.id)}>{truncate(s.stub, 48)}</a>
                        <span className="mono">{s.score.toFixed(2)}</span>
                      </div>
                    ))}
                    {data.similar.length > 0 && !deleted && canWrite && (
                      <button type="button" className="btn bs" style={{ alignSelf: 'flex-start', marginTop: 4 }} onClick={() => setModal('relate')}>
                        Link a memory
                      </button>
                    )}
                  </div>
                </div>
              </aside>
            </div>
          )
        ) : null}
      </div>

      {modal === 'contradiction' && canWrite && <ContradictionModal id={id} onClose={() => setModal(null)} onDone={reload} />}
      {modal === 'branch' && canWrite && <BranchModal id={id} onClose={() => setModal(null)} onDone={reload} />}
      {modal === 'edit' && m && canWrite && (
        <EditModal
          id={id}
          content={m.content}
          weight={m.weight}
          domains={m.domains}
          metadata={m.metadata}
          onClose={() => setModal(null)}
          onDone={(newId) => {
            toast('New version created.');
            navigate(`/memory/${newId}`);
          }}
        />
      )}
      {modal === 'relate' && canWrite && <RelationshipModal sourceIds={[id]} onClose={() => setModal(null)} onDone={reload} />}
      {modal === 'delete' && m && canDelete && (
        <ConfirmModal
          title="Delete memory?"
          confirmLabel="Delete"
          danger
          onClose={() => setModal(null)}
          onConfirm={async () => {
            await api.deleteMemory(id);
            toast('Memory deleted. Agents no longer receive it.');
            refreshCounts();
            navigate('/memories');
          }}
        >
          This soft-deletes <b>{hidden ? shortId(id) : `“${truncate(m.content, 80)}”`}</b>, all {versions.length} version{versions.length === 1 ? '' : 's'} and {data?.branches.length ?? 0}{' '}
          branch{data?.branches.length === 1 ? '' : 'es'}. Agents stop receiving it immediately. The deletion is recorded in the audit log.
        </ConfirmModal>
      )}
      {modal === 'quarantine' && m && canModerate && (
        <ConfirmModal
          title="Quarantine memory?"
          confirmLabel="Quarantine"
          danger
          onClose={() => setModal(null)}
          onConfirm={async () => {
            await api.bulk({ action: 'quarantine', ids: [id], reason: qReason.trim() || undefined });
            setQReason('');
            toast('Memory quarantined — agents stop receiving it.');
            refreshCounts();
            reload();
          }}
        >
          Agents stop receiving it at once. It waits in the Quarantined tab of Content moderation, where a moderator restores it. Audited.
          <div className="f" style={{ marginTop: 12 }}>
            <label htmlFor="mqr">Reason</label>
            <input id="mqr" className="in" maxLength={500} value={qReason} onChange={(e) => setQReason(e.target.value)} placeholder="e.g. Contains a customer contract number" />
          </div>
        </ConfirmModal>
      )}
      {modal === 'restore' && m && canModerate && (
        <ConfirmModal
          title="Restore memory?"
          confirmLabel="Restore"
          onClose={() => setModal(null)}
          onConfirm={async () => {
            await api.bulk({ action: 'restore', ids: [id] });
            toast('Memory restored — agents get it again.');
            refreshCounts();
            reload();
          }}
        >
          It leaves quarantine and agents receive it again. Audited.
        </ConfirmModal>
      )}
    </>
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
  const [type, setType] = useState<'rationale' | 'provenance' | 'evidence' | 'description'>('rationale');
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
        <select id="bt" className="in" value={type} onChange={(e) => setType(e.target.value as typeof type)}>
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
  metadata: Record<string, unknown> | null;
  onClose: () => void;
  onDone: (newId: string) => void;
}> = ({ id, content: initial, weight: initialWeight, domains: initialDomains, metadata: initialMetadata, onClose, onDone }) => {
  const [content, setContent] = useState(initial);
  const [weight, setWeight] = useState(initialWeight);
  const [domains, setDomains] = useState(initialDomains.join(', '));
  const initialMetadataText = JSON.stringify(initialMetadata ?? {}, null, 2);
  const [metadataText, setMetadataText] = useState(initialMetadataText);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const domainList = domains.split(',').map((d) => d.trim()).filter(Boolean);
  const changed = content !== initial || weight !== initialWeight || domainList.join(',') !== initialDomains.join(',') || metadataText !== initialMetadataText;
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
                const metadata: unknown = JSON.parse(metadataText);
                if (metadata === null || Array.isArray(metadata) || typeof metadata !== 'object') throw new Error('Metadata must be a JSON object.');
                const res = await api.newVersion(id, {
                  content: content !== initial ? content.trim() : undefined,
                  weight: weight !== initialWeight ? weight : undefined,
                  domains: domainList.join(',') !== initialDomains.join(',') ? domainList : undefined,
                  metadata: metadataText !== initialMetadataText ? metadata as Record<string, unknown> : undefined,
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
      <div className="f">
        <label htmlFor="edit-metadata">Metadata (JSON object)</label>
        <textarea id="edit-metadata" className="in mono" value={metadataText} onChange={(e) => setMetadataText(e.target.value)} />
      </div>
      <span className="hint">The current version is kept for forensics; agents receive the new version from now on.</span>
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

export default MemoryDetail;

/** Do agents act on this memory when search returns it? From the audit log. */

const UserMemoryView: React.FC<{
  data: MemoryContext;
  byVersion: Version[];
  canWrite: boolean;
  canDelete: boolean;
  deleted: boolean;
  onDelete: () => void;
  onRelate: () => void;
}> = ({ data, byVersion, canWrite, canDelete, deleted, onDelete, onRelate }) => {
  const { me } = useApp();
  const m = data.memory;
  const [compare, setCompare] = useState(false);
  const unresolved = (data.contradictions ?? []).filter((c) => !c.resolved);
  const you = (id: string | null | undefined) => (id && id === me?.username ? `${id} (you)` : id || '—');
  const owner = m.scope === 'user' ? `Personal · ${you(m.owner_id)}` : `${scopeMeta(m.scope).label} ${m.scope_id ?? m.owner_id}`;
  const latest = byVersion[byVersion.length - 1];
  const previous = byVersion[byVersion.length - 2];
  return (
    <div className="row-wrap">
      <div className="col-main">
        {deleted && (
          <div className="alert" role="note">
            <div>
              <b>Deleted {fmtRelative(m.deleted_at as string).toLowerCase()}.</b> Agents no longer receive it.
            </div>
          </div>
        )}
        <section className="card">
          <div className="ch">
            <h2 data-h="3">Content</h2>
            <span className="sm muted">
              {canWrite ? `You can edit this ${m.scope === 'user' ? 'personal' : scopeMeta(m.scope).label.toLowerCase()} memory` : 'Read only for you'}
            </span>
          </div>
          <p style={{ margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{m.content}</p>
          {m.domains.length > 0 && (
            <div className="chips" style={{ marginTop: 12 }}>
              {m.domains.map((d) => (
                <a key={d} className="tag link-plain" href={buildHash('/memories', { domain: d })}>
                  {d}
                </a>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <h2 data-h="3" style={{ marginBottom: 12 }}>Details</h2>
          <dl className="kv wide">
            <dt>Owner (scope)</dt>
            <dd>{owner}</dd>
            <dt>Actor</dt>
            <dd>{you(m.actor_id)}</dd>
            <dt>Driver</dt>
            <dd>{you(m.driver_id)}</dd>
            <dt>Relevant until</dt>
            <dd>{m.relevant_until ? fmtDateTime(m.relevant_until) : 'No expiry'}</dd>
            <dt>Status</dt>
            <dd>
              <span className={`lbl ${m.status === 'active' ? 'grn' : 'ylw'}`}>{m.status}</span>
            </dd>
            <dt>Weight</dt>
            <dd>
              {fmtWeight(m.weight)} · {m.injection === 'full' ? 'agents get the full text' : 'agents get a stub'}
            </dd>
            <dt>Created / updated</dt>
            <dd>
              {fmtShortDateTime(byVersion[0]?.created_at ?? m.created_at)} · {fmtShortDateTime(m.updated_at)}
            </dd>
            <dt>Indexing</dt>
            <dd>{m.embedding_dims ? <span className="ok">● Indexed · searchable</span> : <span className="muted">Not indexed — found by text only</span>}</dd>
          </dl>
        </section>

        <section className="card">
          <div className="ch">
            <h2 data-h="3">Version history</h2>
            {previous && (
              <button type="button" className="btn bl sm" onClick={() => setCompare((c) => !c)}>
                {compare ? 'Hide comparison' : 'Compare'}
              </button>
            )}
          </div>
          <div className="vlist">
            {[...byVersion].reverse().map((v, i) => {
              const prev = byVersion[byVersion.indexOf(v) - 1];
              return (
                <div key={v.id} className="vrow">
                  <span className={`vbadge ${v.is_current ? 'cur' : ''}`}>v{v.version}</span>
                  <div style={{ minWidth: 0 }}>
                    <div className={i === 0 ? 'b6' : ''}>{prev ? changeSummary(v, prev) : truncate(v.content, 90)}</div>
                    <div className="hint">
                      {fmtMonthDay(v.created_at)} · {v.is_current ? 'current' : 'superseded'}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {compare && previous && latest && (
            <div className="diff" style={{ marginTop: 12 }}>
              {lineDiff(previous.content, latest.content).map((l, i) => (
                <div key={i} className={l.kind}>
                  {l.kind === 'del' ? '− ' : l.kind === 'add' ? '+ ' : '  '}
                  {l.text}
                </div>
              ))}
            </div>
          )}
        </section>

      </div>

      <aside className="col-side" style={{ flex: '1 1 300px' }}>
        <section className="card">
          <div className="ch">
            <h2 data-h="3">Contradictions</h2>
            {unresolved.length > 0 && <span className="lbl ylw">{unresolved.length} open</span>}
          </div>
          {unresolved.length === 0 ? (
            <p className="sm muted" style={{ margin: 0 }}>
              No open reports.
            </p>
          ) : (
            unresolved.map((c) => (
              <div key={c.id} className="side-item">
                <div className="sm">“{c.observed_behavior}”</div>
                <div className="hint">
                  Reported by {c.reporter} · {fmtMonthDay(c.created_at)} · resolved by a platform admin
                </div>
              </div>
            ))
          )}
        </section>

        <section className="card">
          <div className="ch">
            <h2 data-h="3">Relationships</h2>
            {!deleted && canWrite && (
              <button type="button" className="btn bl sm" onClick={onRelate}>
                + Add
              </button>
            )}
          </div>
          {data.relationships.length === 0 && (
            <p className="sm muted" style={{ margin: 0 }}>
              No relationships yet.
            </p>
          )}
          {data.relationships.map((r) => (
            <div key={r.id} className="side-item row">
              <span className="tag">{r.type}</span>
              <MemoryLink id={r.other.id} className="sm">
                {truncate(r.other.stub, 60)}
              </MemoryLink>
            </div>
          ))}
        </section>

        <section className="card">
          <h2 data-h="3" style={{ marginBottom: 10 }}>Branches</h2>
          {data.branches.length === 0 && (
            <p className="sm muted" style={{ margin: 0 }}>
              No branches yet.
            </p>
          )}
          {data.branches.map((b) => (
            <div key={b.id} className="side-item row">
              <span className="tag">{b.branch_type ?? 'branch'}</span>
              <span className="sm">{b.content}</span>
            </div>
          ))}
        </section>

        <section className="card">
          <h2 data-h="3" style={{ marginBottom: 10 }}>Similar memories</h2>
          {data.similar.length === 0 && (
            <p className="sm muted" style={{ margin: 0 }}>
              {m.embedding_dims ? 'No close neighbours.' : 'This memory has no embedding.'}
            </p>
          )}
          {data.similar.map((x) => (
            <div key={x.id} className="side-item row">
              <span className="sm muted mono">{x.score.toFixed(2)}</span>
              <a className="sm" href={memoryHref(x.id)}>
                {truncate(x.stub, 60)}
              </a>
            </div>
          ))}
          <p className="hint" style={{ margin: '8px 0 0' }}>
            Only memories you can read are compared.
          </p>
        </section>

        {canDelete && !deleted && (
          <button type="button" className="btn bd outline" style={{ alignSelf: 'flex-start' }} onClick={onDelete}>
            Delete memory…
          </button>
        )}
      </aside>
    </div>
  );
};
