import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { Empty, ErrorState, Modal, ScopeLabel, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { EntitiesResponse, EntityDetail as EntityDetailT, EntityMergePreview } from '@/types';
import { errorMessage, fmtInt, fmtRelative, fmtWeight, scopeMeta } from '@/utils/format';
import { memoryHref } from './common';

const TYPES = [
  { value: 'person', label: 'Person', cls: 'blue' },
  { value: 'organization', label: 'Organization', cls: 'pur' },
  { value: 'location', label: 'Location', cls: 's-project' },
  { value: 'object', label: 'Object', cls: 'org' },
  { value: 'event', label: 'Event', cls: 'ylw' },
];
const typeOf = (t: string) => TYPES.find((x) => x.value === t) ?? { value: t, label: t, cls: 'g' };

/** One entity: the memories that mention it, when, with whom, and its aliases. */
const EntityDetail: React.FC<{ route: HashRoute }> = ({ route }) => {
  const id = route.path.split('/')[2] ?? '';
  const toast = useToast();
  const { me } = useApp();
  const { data, error, loading, reload } = useApi<EntityDetailT>(() => api.entity(id), [id]);
  const [modal, setModal] = useState<null | 'edit' | 'merge'>(null);

  if (error && !data) {
    return (
      <>
        <PageHeader title="Entity" crumbs={[{ label: 'Entities', href: buildHash('/entities') }, { label: 'Not found' }]} />
        <div className="body">
          <div className="card">
            {(error as { status?: number }).status === 404 ? (
              <Empty title="Entity not found" action={<a className="btn bs" href={buildHash('/entities')}>Back to entities</a>}>
                It may have been merged into another entity, or none of the memories that mention it are yours to read.
              </Empty>
            ) : (
              <ErrorState error={error} onRetry={reload} />
            )}
          </div>
        </div>
      </>
    );
  }

  const e = data;
  const maxMonth = Math.max(1, ...(e?.months ?? []).map((m) => m.count));
  const filter = e ? { entity: e.id, entityName: e.name } : {};

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Entities', href: buildHash('/entities') }, { label: e?.name ?? '…' }]}
        title={
          e ? (
            <span style={{ display: 'inline-flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              {e.name}
              <span className={`lbl ${typeOf(e.entity_type).cls}`} style={{ fontFamily: 'var(--mh-font-text)' }}>
                {typeOf(e.entity_type).label}
              </span>
            </span>
          ) : (
            'Entity'
          )
        }
        description={
          e
            ? e.aliases.length
              ? `Also known as ${e.aliases.join(', ')}.`
              : 'No aliases yet. Add the other names agents use for it so they resolve to this entity.'
            : undefined
        }
        actions={
          e && (
            <>
              {me?.labs && (
                <>
                  <button type="button" className="btn bg" onClick={() => setModal('edit')}>
                    Rename · aliases
                  </button>
                  <button type="button" className="btn bs" onClick={() => setModal('merge')}>
                    Merge into…
                  </button>
                </>
              )}
              <a className="btn bp" href={buildHash('/memories', filter)}>
                Open in Memory browser
              </a>
            </>
          )
        }
      />
      <div className="body">
        {loading && !e ? (
          <div className="card">
            <SkLines lines={8} />
          </div>
        ) : (
          e && (
            <div className="row-wrap">
              <div className="col-main">
                <section className="card">
                  <div className="stats4">
                    <div>
                      <div className="statv">{fmtInt(e.memory_count)}</div>
                      <div className="hint">memories mention it</div>
                    </div>
                    <div>
                      <div className="statv">{e.first_seen ? fmtRelative(e.first_seen) : '—'}</div>
                      <div className="hint">first seen</div>
                    </div>
                    <div>
                      <div className="statv">{e.last_seen ? fmtRelative(e.last_seen) : '—'}</div>
                      <div className="hint">last change</div>
                    </div>
                    <div>
                      <div className="statv">{fmtInt(e.co_mentions.length)}</div>
                      <div className="hint">related entities</div>
                    </div>
                  </div>
                  {e.hidden_mentions > 0 && (
                    <p className="hint" style={{ margin: '12px 0 0' }}>
                      {fmtInt(e.hidden_mentions)} more {e.hidden_mentions === 1 ? 'memory mentions' : 'memories mention'} it that you cannot read. They are counted, never shown.
                    </p>
                  )}
                </section>

                <section className="card" style={{ padding: 0 }}>
                  <div className="ch" style={{ padding: '18px 20px 0' }}>
                    <h3>Memories</h3>
                    <span style={{ display: 'flex', gap: 12 }}>
                      <a className="sm" href={buildHash('/memories', { ...filter, view: 'graph' })}>
                        Graph
                      </a>
                      <a className="sm" href={buildHash('/memories', { ...filter, view: 'timeline', tdays: '0' })}>
                        Timeline
                      </a>
                    </span>
                  </div>
                  <div className="scroll">
                    <table className="tbl mid">
                      <thead>
                        <tr>
                          <th>Memory</th>
                          <th>Scope</th>
                          <th>Weight</th>
                          <th>Updated</th>
                        </tr>
                      </thead>
                      <tbody>
                        {e.memories.map((m) => (
                          <tr key={m.id}>
                            <td style={{ maxWidth: 460 }}>
                              <a href={memoryHref(m.id)} style={{ fontWeight: 500, textDecoration: 'none' }}>
                                {m.stub}
                              </a>
                            </td>
                            <td>
                              <ScopeLabel scope={m.scope} />
                            </td>
                            <td className="sm">{fmtWeight(m.weight)}</td>
                            <td className="sm muted">{fmtRelative(m.updated_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </div>

              <aside className="col-side">
                <section className="card">
                  <h3>When it comes up</h3>
                  {e.months.length === 0 ? (
                    <p className="sm muted">No dates yet.</p>
                  ) : (
                    <div className="months" role="img" aria-label="Memories that mention it, per month">
                      {e.months.slice(-12).map((m) => (
                        <div key={m.month} title={`${m.month}: ${m.count}`}>
                          <span style={{ height: `${Math.max(6, (m.count / maxMonth) * 64)}px` }} />
                          <small>{new Date(`${m.month}-01T00:00:00`).toLocaleDateString(undefined, { month: 'short' })}</small>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
                <section className="card">
                  <h3>Mentioned together with</h3>
                  {e.co_mentions.length === 0 ? (
                    <p className="sm muted">No other entity appears in the same memories.</p>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 8 }}>
                      {e.co_mentions.map((c) => (
                        <a key={c.id} className="conn link-plain" href={buildHash(`/entity/${c.id}`)}>
                          <span className={`lbl ${typeOf(c.type).cls}`}>{typeOf(c.type).label}</span>
                          <span className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
                            {c.name}
                          </span>
                          <b className="sm">{c.count}</b>
                        </a>
                      ))}
                    </div>
                  )}
                </section>
                <section className="card">
                  <h3>Where</h3>
                  <dl className="dl" style={{ marginTop: 12 }}>
                    <dt>Scopes</dt>
                    <dd>
                      {Object.entries(e.scopes)
                        .map(([s, n]) => `${scopeMeta(s).label} ${n}`)
                        .join(' · ') || '—'}
                    </dd>
                    <dt>Projects</dt>
                    <dd>
                      {e.projects.length
                        ? e.projects.map((p) => (
                            <a key={p.value} className="tag link-plain" href={buildHash('/memories', { ...filter, project: p.value })} style={{ marginRight: 4 }}>
                              {p.value}
                            </a>
                          ))
                        : '—'}
                    </dd>
                    <dt>Written by</dt>
                    <dd>{e.writers.map((w) => `${w.value} (${w.count})`).join(', ') || '—'}</dd>
                  </dl>
                </section>
              </aside>
            </div>
          )
        )}
      </div>
      {modal === 'edit' && e && (
        <EditEntityModal
          entity={e}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            toast('Entity updated.');
            reload();
          }}
        />
      )}
      {modal === 'merge' && e && (
        <MergeModal
          entity={e}
          onClose={() => setModal(null)}
          onMerged={(res) => {
            setModal(null);
            toast(
              res.source_removed
                ? `Merged into ${res.target.name}.`
                : `Moved ${res.moving} mentions to ${res.target.name}. ${res.staying} in memories you cannot read stay here.`,
            );
            if (res.source_removed) navigate(`/entity/${res.target.id}`);
            else reload();
          }}
        />
      )}
    </>
  );
};

const EditEntityModal: React.FC<{ entity: EntityDetailT; onClose: () => void; onSaved: () => void }> = ({ entity, onClose, onSaved }) => {
  const toast = useToast();
  const [name, setName] = useState(entity.name);
  const [type, setType] = useState(entity.entity_type);
  const [aliases, setAliases] = useState(entity.aliases.join(', '));
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateEntity(entity.id, {
        name: name.trim() !== entity.name ? name.trim() : undefined,
        entity_type: type !== entity.entity_type ? type : undefined,
        aliases: aliases
          .split(',')
          .map((a) => a.trim())
          .filter(Boolean),
      });
      onSaved();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Rename · aliases"
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
        <label htmlFor="en">Name</label>
        <input id="en" className="in" value={name} onChange={(ev) => setName(ev.target.value)} />
        <span className="hint">The old name is kept as an alias.</span>
      </div>
      <div className="f">
        <label htmlFor="et">Type</label>
        <select id="et" className="in" value={type} onChange={(ev) => setType(ev.target.value)}>
          {TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>
      <div className="f">
        <label htmlFor="ea">Aliases</label>
        <input id="ea" className="in" value={aliases} onChange={(ev) => setAliases(ev.target.value)} placeholder="Comma-separated" />
        <span className="hint">Other names agents use for it. Recorded in the audit log.</span>
      </div>
    </Modal>
  );
};

const MergeModal: React.FC<{ entity: EntityDetailT; onClose: () => void; onMerged: (r: EntityMergePreview) => void }> = ({ entity, onClose, onMerged }) => {
  const toast = useToast();
  const [q, setQ] = useState('');
  const [into, setInto] = useState<{ id: string; name: string } | null>(null);
  const [preview, setPreview] = useState<EntityMergePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const { data } = useApi<EntitiesResponse>(() => api.entities({ q: q || entity.name.slice(0, 3), per_page: 8 }), [q]);
  const options = (data?.items ?? []).filter((x) => x.id !== entity.id);

  useEffect(() => {
    if (!into) {
      setPreview(null);
      return;
    }
    api
      .mergeEntity(entity.id, into.id, true)
      .then(setPreview)
      .catch((e) => toast(errorMessage(e), 'err'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [into?.id]);

  return (
    <Modal
      title={`Merge “${entity.name}” into…`}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={!preview || busy}
            onClick={async () => {
              if (!into) return;
              setBusy(true);
              try {
                onMerged(await api.mergeEntity(entity.id, into.id, false));
              } catch (e) {
                toast(errorMessage(e), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            Merge
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="mq">Entity to keep</label>
        <input id="mq" className="in" autoFocus value={q} placeholder="Search by name or alias" onChange={(ev) => setQ(ev.target.value)} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflow: 'auto' }}>
        {options.length === 0 && <span className="sm muted">No other entity matches.</span>}
        {options.map((o) => (
          <label key={o.id} className={`radio ${into?.id === o.id ? 'on' : ''}`}>
            <input type="radio" name="into" checked={into?.id === o.id} onChange={() => setInto({ id: o.id, name: o.name })} />
            <span>
              <span className="sm b6">{o.name}</span>{' '}
              <span className="hint">
                {typeOf(o.entity_type).label} · {o.memory_count} memories
              </span>
            </span>
          </label>
        ))}
      </div>
      {preview && (
        <div className="alert" role="status">
          <div>
            <b>
              {preview.moving} {preview.moving === 1 ? 'mention moves' : 'mentions move'} to {preview.target.name}
            </b>
            {preview.both > 0 ? ` (${preview.both} already ${preview.both === 1 ? 'mentions' : 'mention'} both and ${preview.both === 1 ? 'is' : 'are'} folded).` : '.'}{' '}
            {preview.source_removed
              ? `“${entity.name}” is removed and kept as an alias.`
              : `${preview.staying} in memories you cannot read stay on “${entity.name}”.`}
            <div className="hint" style={{ marginTop: 6 }}>
              Aliases after: {preview.aliases_after.join(', ') || '—'}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
};

export default EntityDetail;
