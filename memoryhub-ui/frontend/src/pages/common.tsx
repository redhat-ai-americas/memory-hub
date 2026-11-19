import React, { useState } from 'react';
import { api } from '@/api/client';
import { useApp } from '@/components/Shell';
import { Modal, useToast } from '@/components/ui';
import { buildHash } from '@/hooks/useHashRoute';
import type { AuditEvent } from '@/types';
import { errorMessage, scopeMeta, truncate } from '@/utils/format';

export const memoryHref = (id: string) => buildHash(`/memory/${id}`);

export const MemoryLink: React.FC<{ id: string; children: React.ReactNode; style?: React.CSSProperties; className?: string }> = ({
  id,
  children,
  style,
  className,
}) => (
  <a href={memoryHref(id)} style={style} className={className}>
    {children}
  </a>
);

/** Human label and colour for an audit decision, as drawn in the design. */
export const decisionOf = (e: AuditEvent): { label: string; cls: string; note?: string } => {
  const meta = e.metadata || {};
  const reason = (meta.rule as string) || (meta.reason as string) || (meta.detail as string) || '';
  if (e.decision === 'denied') {
    if (e.event_type === 'memory.write' && reason) return { label: `Blocked · ${truncate(reason, 24)}`, cls: 'err', note: reason ? `rule ${reason}` : undefined };
    return { label: 'Denied', cls: 'err', note: reason || undefined };
  }
  if (e.event_type === 'memory.contradiction_reported') return { label: 'Logged', cls: 'muted' };
  if (meta.queued || e.event_type === 'review.promotion_proposed') return { label: 'Queued for review', cls: 'warn', note: 'queued for review' };
  if (e.event_type === 'review.reject') return { label: 'Rejected', cls: 'err' };
  return { label: 'Permitted', cls: 'ok' };
};

export const actorKind = (e: AuditEvent): string => {
  if (meta(e).via === 'dashboard') return 'human · dashboard';
  if (e.actor_type === 'service') return 'service agent';
  if (e.driver_id && e.driver_id !== e.actor_id) return 'user agent';
  if (e.actor_type === 'user') return 'user';
  return e.actor_id.includes('agent') || e.actor_id.includes('curator') ? 'service agent' : 'user';
};

const meta = (e: AuditEvent) => (e.metadata || {}) as Record<string, unknown>;

export const actorName = (e: AuditEvent) =>
  e.driver_id && e.driver_id !== e.actor_id ? `${e.actor_id} · ${e.driver_id}` : e.actor_id;

/** The "Memory" / "Target" cell of an audit row. */
export const EventTarget: React.FC<{ e: AuditEvent; max?: number }> = ({ e, max = 80 }) => {
  const m = meta(e);
  if (e.event_type === 'memory.search') {
    const q = (m.query as string) || 'search';
    const n = (m.result_count as number) ?? (Array.isArray(m.result_ids) ? (m.result_ids as unknown[]).length : null);
    return (
      <span>
        “{truncate(q, max)}”{n !== null && n !== undefined ? ` · ${n} results` : ''}
      </span>
    );
  }
  if (e.event_type === 'access.denied') {
    // QA 2026-11-10 F-CT-19: target of a denied call (path parameters, else the resource).
    const t = (m.target ?? {}) as Record<string, unknown>;
    const params = Object.entries(t).filter(([k]) => k !== 'resource').map(([k, v]) => `${k} ${String(v)}`);
    const label = params.length ? params.join(', ') : String(t.resource ?? '—');
    return <span className="mono sm">{truncate(label, max)}</span>;
  }
  if (e.memory_id && e.memory_stub) return <MemoryLink id={e.memory_id}>{truncate(e.memory_stub, max)}</MemoryLink>;
  if (e.memory_id) return <MemoryLink id={e.memory_id}>{`mem ${e.memory_id.slice(0, 8)}…`}</MemoryLink>;
  if (typeof m.name === 'string') return <span>{m.name}</span>;
  return <span className="muted">—</span>;
};

/* ------------------------------------------------------------------ */
/* Write memory dialog (Overview, Memory browser)                      */
/* ------------------------------------------------------------------ */

type WriteScope = 'user' | 'project' | 'organizational';
const WRITE_SCOPES: WriteScope[] = ['user', 'project', 'organizational'];

/**
 * POST /api/memories. Users write personal memories and to projects they belong
 * to; admins write to projects they administer and, when granted, organizational
 * memory. /api/me lists exactly where this person may write.
 */
export const WriteMemoryModal: React.FC<{ onClose: () => void; onSaved?: (id: string) => void; initialContent?: string; title?: string; initialScope?: string }> = ({
  onClose,
  onSaved,
  initialContent,
  title,
  initialScope,
}) => {
  const toast = useToast();
  const { me, refreshCounts } = useApp();
  const allowedScopes = WRITE_SCOPES.filter((s) => (me?.write?.scopes ?? []).includes(s));
  const projects = me?.write?.project_ids ?? [];
  const [content, setContent] = useState(initialContent ?? '');
  const [scope, setScope] = useState<WriteScope>(
    allowedScopes.includes(initialScope as WriteScope) ? (initialScope as WriteScope) : (allowedScopes[0] ?? 'user'),
  );
  const [scopeId, setScopeId] = useState(projects.length === 1 ? projects[0] : '');
  const [weight, setWeight] = useState(0.7);
  const [domains, setDomains] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsProject = scope === 'project';

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.writeMemory({
        content: content.trim(),
        scope,
        weight,
        scope_id: needsProject ? scopeId : undefined,
        domains: domains.split(',').map((d) => d.trim()).filter(Boolean),
      });
      toast('Memory written.');
      refreshCounts();
      onSaved?.(res.id);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={title ?? 'Write memory'} onClose={onClose}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="f">
          <label htmlFor="wm-content">Content</label>
          <textarea id="wm-content" className="in" required value={content} onChange={(e) => setContent(e.target.value)} />
          <span className="hint">Runs through the same curation rules as an agent’s write_memory call.</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="f">
            <label htmlFor="wm-scope">Scope</label>
            <select id="wm-scope" className="in" value={scope} onChange={(e) => setScope(e.target.value as WriteScope)} aria-describedby="wm-who">
              {allowedScopes.map((s) => (
                <option key={s} value={s}>
                  {scopeMeta(s).label}
                </option>
              ))}
            </select>
          </div>
          {needsProject ? (
            <div className="f">
              <label htmlFor="wm-sid">Project</label>
              <select id="wm-sid" className="in" required value={scopeId} onChange={(e) => setScopeId(e.target.value)}>
                <option value="">Select a project</option>
                {projects.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="f">
              <label htmlFor="wm-owner">Owner</label>
              <input id="wm-owner" className="in" value={me?.write?.owner_id ?? me?.username ?? ''} readOnly />
            </div>
          )}
        </div>
        <p id="wm-who" className="hint" style={{ margin: '-6px 0 0' }}>
          {scope === 'user'
            ? 'Only you and your agents see it.'
            : scope === 'project'
              ? scopeId
                ? `Every member of ${scopeId} and their agents see it.`
                : 'Every member of the project and their agents see it.'
              : 'Everyone in the tenant sees it.'}
        </p>
        <div className="f">
          <label htmlFor="wm-weight">Weight · {weight.toFixed(2)}</label>
          <input id="wm-weight" type="range" min={0} max={100} value={Math.round(weight * 100)} onChange={(e) => setWeight(Number(e.target.value) / 100)} />
        </div>
        <div className="f">
          <label htmlFor="wm-domains">Domain tags</label>
          <input id="wm-domains" className="in" value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="containers, tooling" />
        </div>
        {allowedScopes.length === 0 && <div className="alert warn-a">You have no scope to write to from the dashboard yet.</div>}
        {error && <div className="alert err-a">{error}</div>}
        <div className="modal-actions">
          <button type="submit" className="btn bp" disabled={busy || !content.trim() || allowedScopes.length === 0 || (needsProject && !scopeId)}>
            {busy ? 'Writing…' : 'Write memory'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
};

/* ------------------------------------------------------------------ */
/* Memory picker (relationships, graph focus)                          */
/* ------------------------------------------------------------------ */

export const MemoryPicker: React.FC<{
  onPick: (m: { id: string; stub: string; scope: string }) => void;
  exclude?: string[];
  placeholder?: string;
  autoFocus?: boolean;
}> = ({ onPick, exclude = [], placeholder = 'Search memories by text', autoFocus }) => {
  const [q, setQ] = useState('');
  const [items, setItems] = useState<{ id: string; stub: string; scope: string }[]>([]);
  const [busy, setBusy] = useState(false);
  React.useEffect(() => {
    let cancelled = false;
    const t = window.setTimeout(() => {
      setBusy(true);
      api
        .browse({ q: q.trim() || undefined, mode: 'semantic', sort: q.trim() ? 'relevance' : 'updated', per_page: 8 })
        .then((r) => !cancelled && setItems(r.items.filter((i) => !exclude.includes(i.id))))
        .catch(() => !cancelled && setItems([]))
        .finally(() => !cancelled && setBusy(false));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <input className="in" value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label={placeholder} autoFocus={autoFocus} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 260, overflow: 'auto' }}>
        {busy && items.length === 0 && <span className="sm muted">Searching…</span>}
        {!busy && items.length === 0 && <span className="sm muted">No matching memories.</span>}
        {items.map((m) => (
          <button key={m.id} type="button" className="item" style={{ padding: '8px 12px', display: 'flex', gap: 8, alignItems: 'center' }} onClick={() => onPick(m)}>
            <span className={`lbl ${scopeMeta(m.scope).cls}`}>{scopeMeta(m.scope).label}</span>
            <span className="ellipsis" style={{ flex: 1 }}>{m.stub}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export const REL_TYPES = ['related_to', 'derived_from', 'supersedes', 'conflicts_with'] as const;

/** Create a relationship from one or more memories to a picked target. */
export const RelationshipModal: React.FC<{ sourceIds: string[]; onClose: () => void; onDone: () => void }> = ({ sourceIds, onClose, onDone }) => {
  const toast = useToast();
  const [type, setType] = useState<(typeof REL_TYPES)[number]>('related_to');
  const [target, setTarget] = useState<{ id: string; stub: string; scope: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      if (sourceIds.length === 1) {
        await api.createRelationship({ source_id: sourceIds[0], target_id: target.id, relationship_type: type });
      } else {
        // One transaction: every source and the target are checked before anything is linked.
        const res = await api.bulk({ action: 'relate', ids: sourceIds, target_id: target.id, relationship_type: type });
        if (res.errors.length) throw new Error(res.errors.map((e) => e.detail).join('; '));
      }
      toast(`Relationship ${type} created.`);
      onDone();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={sourceIds.length > 1 ? `Add relationship from ${sourceIds.length} memories` : 'Add relationship'}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={!target || busy} onClick={submit}>
            {busy ? 'Creating…' : 'Create relationship'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="rel-type">Relationship</label>
        <select id="rel-type" className="in" value={type} onChange={(e) => setType(e.target.value as (typeof REL_TYPES)[number])}>
          {REL_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </div>
      <div className="f">
        <label>Target memory</label>
        {target ? (
          <div className="br" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className={`lbl ${scopeMeta(target.scope).cls}`}>{scopeMeta(target.scope).label}</span>
            <span style={{ flex: 1 }}>{target.stub}</span>
            <button type="button" className="btn bl sm" onClick={() => setTarget(null)}>
              Change
            </button>
          </div>
        ) : (
          <MemoryPicker onPick={setTarget} exclude={sourceIds} autoFocus />
        )}
      </div>
      {error && <div className="alert err-a">{error}</div>}
    </Modal>
  );
};

export const ConfirmModal: React.FC<{
  title: string;
  children: React.ReactNode;
  confirmLabel: string;
  danger?: boolean;
  /** Keep the confirm button off until the dialog's own check passes (e.g. a typed name). */
  confirmDisabled?: boolean;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}> = ({ title, children, confirmLabel, danger, confirmDisabled, onConfirm, onClose }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal
      title={title}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className={`btn ${danger ? 'bd' : 'bp'}`}
            disabled={busy || confirmDisabled}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm();
                onClose();
              } catch (err) {
                setError(errorMessage(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div style={{ fontSize: 14, lineHeight: 1.5 }}>{children}</div>
      {error && <div className="alert err-a">{error}</div>}
    </Modal>
  );
};
