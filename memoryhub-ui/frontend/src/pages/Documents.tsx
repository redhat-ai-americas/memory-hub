import React, { useEffect, useRef, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { Empty, ErrorState, Modal, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate } from '@/hooks/useHashRoute';
import type { DocumentDetail, DocumentRow } from '@/types';
import { errorMessage, fmtInt, fmtRelative, SCOPE_ORDER, scopeMeta, truncate } from '@/utils/format';
import { ConfirmModal, memoryHref } from './common';
import { KnowledgeTabs } from './Knowledge';

const ACCEPT = '.txt,.md,.markdown,.csv,.json,.html,.htm,.log,.yaml,.yml,text/*';
const MAX_BYTES = 2_000_000;

/**
 * Documents memories are written from, with every memory linked to its
 * passage. Lives inside Knowledge: /knowledge/documents[/<id>].
 */
export const docHref = (id?: string) => buildHash(id ? `/knowledge/documents/${id}` : '/knowledge/documents');
const CRUMBS = [
  { label: 'Knowledge', href: buildHash('/knowledge') },
  { label: 'Documents', href: buildHash('/knowledge/documents') },
];

export const DocumentsSection: React.FC<{ id?: string }> = ({ id }) => (id ? <DocumentPage id={id} /> : <DocumentList />);

export const UploadDocumentModal: React.FC<{ onClose: () => void; onDone?: (id: string) => void }> = ({ onClose, onDone }) => {
  const toast = useToast();
  const { refreshCounts } = useApp();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [mime, setMime] = useState('text/plain');
  const [project, setProject] = useState('');
  const [projects, setProjects] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .projects(true)
      .then((r) => setProjects(r.items.map((p) => p.name)))
      .catch(() => undefined);
  }, []);
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    if (f.size > MAX_BYTES) {
      toast('That file is larger than 2 MB.', 'err');
      return;
    }
    if (f.type === 'application/pdf' || /\.(pdf|docx?|xlsx?|pptx?)$/i.test(f.name)) {
      toast('Only text formats for now — Markdown, plain text, CSV, JSON, HTML. Paste the text of PDFs and Office files.', 'err');
      return;
    }
    setBody(await f.text());
    setMime(f.type || 'text/plain');
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ''));
  };
  const save = async () => {
    setBusy(true);
    try {
      const { id } = await api.createDocument({ title: title.trim(), body, mime, project: project || null });
      refreshCounts();
      onClose();
      if (onDone) onDone(id);
      else navigate(`/knowledge/documents/${id}`);
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Add a document"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={busy || !title.trim() || !body.trim()} onClick={save}>
            {busy ? 'Adding…' : 'Add document'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <p className="sm muted" style={{ margin: 0 }}>
        Nothing is written to memory yet. Next you pick the passages that should become memories; each one keeps a link to its source.
      </p>
      <div className="f">
        <label htmlFor="df">File</label>
        <input id="df" type="file" accept={ACCEPT} onChange={(e) => void onFile(e.target.files?.[0])} />
        <span className="hint">Markdown, plain text, CSV, JSON or HTML, up to 2 MB. Or paste below.</span>
      </div>
      <div className="f">
        <label htmlFor="dt">Title</label>
        <input id="dt" className="in" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="f">
        <label htmlFor="db">Text</label>
        <textarea id="db" className="in" style={{ minHeight: 160 }} value={body} onChange={(e) => setBody(e.target.value)} />
        <span className="hint">{fmtInt(body.length)} characters</span>
      </div>
      <div className="f">
        <label htmlFor="dp">Share with</label>
        <select id="dp" className="in" value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="">Only me</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              Project {p}
            </option>
          ))}
        </select>
      </div>
    </Modal>
  );
};

const DocumentList: React.FC = () => {
  const { data, error, loading, reload } = useApi<{ items: DocumentRow[] }>(() => api.documents(), []);
  const [upload, setUpload] = useState(false);
  return (
    <>
      <PageHeader
        title="Knowledge"
        crumbs={[{ label: 'Knowledge', href: buildHash('/knowledge') }, { label: 'Documents' }]}
        tabs={<KnowledgeTabs value="documents" />}
        description="Source text memories are written from. Pick passages to turn into memories; each memory shows the passage it came from, and a new version of the document flags memories whose source changed."
        actions={
          <button type="button" className="btn bp" onClick={() => setUpload(true)}>
            Add document
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
            <Empty title="No documents">Add a document to write memories from it.</Empty>
          </div>
        ) : (
          <section className="card" style={{ padding: 0 }}>
            <table className="tbl mid">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Memories</th>
                  <th>Version</th>
                  <th>Shared</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <a href={docHref(d.id)} className="b6" style={{ textDecoration: 'none' }}>
                        {d.title}
                      </a>
                      <div className="hint">
                        {fmtInt(d.size)} characters · {d.mime}
                        {!d.mine ? ` · by ${d.owner}` : ''}
                      </div>
                    </td>
                    <td>
                      {d.memories}
                      {d.changed > 0 && <span className="lbl ylw" style={{ marginLeft: 6 }}>{d.changed} source changed</span>}
                    </td>
                    <td>v{d.version}</td>
                    <td className="sm">{d.project ? `Project ${d.project}` : 'Only you'}</td>
                    <td className="sm muted">{fmtRelative(d.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>
      {upload && <UploadDocumentModal onClose={() => setUpload(false)} />}
    </>
  );
};

const DocumentPage: React.FC<{ id: string }> = ({ id }) => {
  const toast = useToast();
  const { refreshCounts } = useApp();
  const { data, error, loading, reload } = useApi<DocumentDetail>(() => api.document(id), [id]);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [custom, setCustom] = useState<{ start: number; end: number } | null>(null);
  const [write, setWrite] = useState(false);
  const [version, setVersion] = useState(false);
  const [del, setDel] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  if (error && !data)
    return (
      <>
        <PageHeader title="Document" crumbs={[...CRUMBS, { label: 'Not found' }]} />
        <div className="body">
          <ErrorState error={error} onRetry={reload} />
        </div>
      </>
    );
  if (loading && !data)
    return (
      <div className="body">
        <div className="card">
          <SkLines lines={10} />
        </div>
      </div>
    );
  if (!data) return null;

  const linkById = Object.fromEntries(data.links.map((l) => [l.memory_id, l]));
  const changed = data.links.filter((l) => l.status === 'changed');
  const spans = [
    ...data.passages.filter((p) => picked.has(p.i)).map((p) => ({ start: p.start, end: p.end, text: p.text })),
    ...(custom ? [{ ...custom, text: data.body.slice(custom.start, custom.end) }] : []),
  ];

  // A text selection inside one passage becomes a custom span.
  const onSelect = () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !bodyRef.current) return;
    const text = sel.toString().trim();
    if (text.length < 12) return;
    const anchor = (sel.anchorNode?.parentElement?.closest('[data-start]') as HTMLElement | null) ?? null;
    if (!anchor) return;
    const base = Number(anchor.dataset.start);
    const at = data.body.indexOf(text, base);
    if (at >= 0) setCustom({ start: at, end: at + text.length });
  };

  return (
    <>
      <PageHeader
        crumbs={[...CRUMBS, { label: truncate(data.title, 40) }]}
        title={data.title}
        description={`v${data.version} · ${fmtInt(data.body.length)} characters · ${data.passages.length} passages · ${data.links.length} memories written from it${data.mine ? '' : ` · by ${data.owner}`}`}
        actions={
          <>
            {data.mine && (
              <button type="button" className="btn bg" onClick={() => setVersion(true)}>
                Upload new version
              </button>
            )}
            <button type="button" className="btn bp" disabled={!spans.length} onClick={() => setWrite(true)}>
              Write {spans.length || ''} {spans.length === 1 ? 'memory' : 'memories'}
            </button>
          </>
        }
      />
      <div className="body">
        {changed.length > 0 && (
          <div className="alert" role="note">
            <div>
              <b>
                {changed.length} {changed.length === 1 ? 'memory was' : 'memories were'} written from text that is no longer in this version.
              </b>{' '}
              Review {changed.length === 1 ? 'it' : 'them'}: {changed.map((l) => truncate(l.stub, 40)).join(' · ')}
            </div>
          </div>
        )}
        <div className="row-wrap">
          <section className="card col-main" aria-label="Passages">
            <div className="ch">
              <h3>Passages</h3>
              <span className="sm muted">Tick passages, or select any text inside one.</span>
            </div>
            {custom && (
              <div className="carried" style={{ marginBottom: 10 }}>
                <span className="sm">
                  Selected text: “{truncate(data.body.slice(custom.start, custom.end), 90)}”
                </span>
                <button type="button" className="btn bl sm" onClick={() => setCustom(null)}>
                  Clear
                </button>
              </div>
            )}
            <div ref={bodyRef} onMouseUp={onSelect} className="passages">
              {data.passages.map((p) => (
                <div key={p.i} className={`passage ${picked.has(p.i) ? 'on' : ''} ${p.memories.length ? 'linked' : ''}`} data-start={p.start}>
                  <input
                    type="checkbox"
                    aria-label={`Passage ${p.i + 1}`}
                    checked={picked.has(p.i)}
                    onChange={() => {
                      const next = new Set(picked);
                      if (next.has(p.i)) next.delete(p.i);
                      else next.add(p.i);
                      setPicked(next);
                    }}
                  />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="ptext">{p.text}</div>
                    {p.memories.length > 0 && (
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                        {p.memories.map((mid) => (
                          <a key={mid} href={memoryHref(mid)} className={`lbl ${linkById[mid]?.status === 'changed' ? 'ylw' : 'grn'}`} style={{ textDecoration: 'none' }}>
                            memory · {truncate(linkById[mid]?.stub ?? mid, 28)}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
          <aside className="col-side">
            <section className="card">
              <h3>Memories from this document</h3>
              {data.links.length === 0 ? (
                <p className="sm muted">None yet. Tick the passages worth remembering and press Write memories.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>
                  {data.links.map((l) => (
                    <a key={l.memory_id} className="conn link-plain" href={memoryHref(l.memory_id)}>
                      <span className="ellipsis" style={{ flex: 1, minWidth: 0 }}>
                        {l.stub}
                      </span>
                      <span className={`lbl ${l.status === 'changed' ? 'ylw' : l.status === 'deleted' ? 'g' : 'grn'}`}>{l.status === 'ok' ? 'linked' : l.status}</span>
                    </a>
                  ))}
                </div>
              )}
            </section>
            {data.mine && (
              <section className="card">
                <button type="button" className="btn bl danger" onClick={() => setDel(true)}>
                  Delete document
                </button>
                <p className="hint" style={{ margin: '8px 0 0' }}>
                  Memories written from it stay; they keep the title but lose the link to the passage.
                </p>
              </section>
            )}
          </aside>
        </div>
      </div>
      {write && (
        <WriteFromDocument
          docId={id}
          spans={spans}
          onClose={() => setWrite(false)}
          onDone={(n) => {
            setWrite(false);
            setPicked(new Set());
            setCustom(null);
            toast(`${n} ${n === 1 ? 'memory' : 'memories'} written, each linked to its passage.`);
            refreshCounts();
            reload();
          }}
        />
      )}
      {version && (
        <NewVersionModal
          doc={data}
          onClose={() => setVersion(false)}
          onDone={(r) => {
            setVersion(false);
            toast(r ? `New version saved. Links: ${r.ok + r.moved} still match${r.changed ? `, ${r.changed} source changed` : ''}.` : 'Saved.');
            reload();
          }}
        />
      )}
      {del && (
        <ConfirmModal
          title="Delete this document?"
          confirmLabel="Delete"
          danger
          onClose={() => setDel(false)}
          onConfirm={async () => {
            await api.deleteDocument(id);
            refreshCounts();
            navigate('/knowledge/documents');
          }}
        >
          The document and its passage links are removed. Memories written from it are not deleted.
        </ConfirmModal>
      )}
    </>
  );
};

const WriteFromDocument: React.FC<{ docId: string; spans: { start: number; end: number; text: string }[]; onClose: () => void; onDone: (n: number) => void }> = ({
  docId,
  spans,
  onClose,
  onDone,
}) => {
  const toast = useToast();
  const [texts, setTexts] = useState(spans.map((s) => withoutHeadings(s.text)));
  const [scope, setScope] = useState('user');
  const [scopeId, setScopeId] = useState('');
  const [weight, setWeight] = useState(0.7);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .myPrefs()
      .then((p) => {
        setScope(p.prefs.write.default_scope);
        setWeight(p.prefs.write.default_weight);
      })
      .catch(() => undefined);
  }, []);
  const save = async () => {
    setBusy(true);
    try {
      const res = await api.memoriesFromDocument(docId, {
        spans: spans.map((s, i) => ({ start: s.start, end: s.end, content: texts[i] !== s.text ? texts[i] : undefined })),
        scope,
        scope_id: scopeId || undefined,
        weight,
      });
      if (res.failed.length) toast(`${res.failed.length} not written: ${res.failed[0].detail}`, 'err');
      if (res.created.length) onDone(res.created.length);
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={`Write ${spans.length} ${spans.length === 1 ? 'memory' : 'memories'}`}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={busy} onClick={save}>
            {busy ? 'Writing…' : 'Write'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <p className="sm muted" style={{ margin: 0 }}>
        Shorten each passage to the fact worth remembering. The link points to the original passage either way. Curation rules apply as usual.
      </p>
      {texts.map((t, i) => (
        <div className="f" key={i}>
          <label htmlFor={`wt${i}`}>Memory {i + 1}</label>
          <textarea id={`wt${i}`} className="in" value={t} onChange={(e) => setTexts(texts.map((x, j) => (j === i ? e.target.value : x)))} />
        </div>
      ))}
      <div className="fg">
        <div className="f">
          <label htmlFor="ws">Scope</label>
          <select id="ws" className="in" value={scope} onChange={(e) => setScope(e.target.value)}>
            {SCOPE_ORDER.filter((s) => s !== 'enterprise' && s !== 'organizational').map((s) => (
              <option key={s} value={s}>
                {scopeMeta(s).label}
              </option>
            ))}
          </select>
        </div>
        {['project', 'role', 'campaign'].includes(scope) && (
          <div className="f">
            <label htmlFor="wsi">{scopeMeta(scope).label} ID</label>
            <input id="wsi" className="in" value={scopeId} onChange={(e) => setScopeId(e.target.value)} />
          </div>
        )}
        <div className="f">
          <label htmlFor="ww">Weight · {weight.toFixed(2)}</label>
          <input id="ww" type="range" min={0} max={100} value={Math.round(weight * 100)} onChange={(e) => setWeight(Number(e.target.value) / 100)} />
        </div>
      </div>
    </Modal>
  );
};

/** Markdown headings give a passage context but rarely belong in the memory itself. */
const withoutHeadings = (t: string) =>
  t
    .split('\n')
    .filter((line) => !/^\s*#{1,6}\s/.test(line))
    .join('\n')
    .trim() || t.trim();

const NewVersionModal: React.FC<{ doc: DocumentDetail; onClose: () => void; onDone: (r: { ok: number; moved: number; changed: number } | null) => void }> = ({
  doc,
  onClose,
  onDone,
}) => {
  const toast = useToast();
  const [body, setBody] = useState(doc.body);
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title="Upload a new version"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy || body === doc.body}
            onClick={async () => {
              setBusy(true);
              try {
                onDone((await api.updateDocument(doc.id, { body })).reprocessed);
              } catch (e) {
                toast(errorMessage(e), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            Save version {doc.version + 1}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="nvf">File</label>
        <input id="nvf" type="file" accept={ACCEPT} onChange={async (e) => e.target.files?.[0] && setBody(await e.target.files[0].text())} />
      </div>
      <div className="f">
        <label htmlFor="nvb">Text</label>
        <textarea id="nvb" className="in" style={{ minHeight: 200 }} value={body} onChange={(e) => setBody(e.target.value)} />
        <span className="hint">Linked memories are re-anchored: a passage that moved is followed; one whose text is gone is flagged for review.</span>
      </div>
    </Modal>
  );
};

