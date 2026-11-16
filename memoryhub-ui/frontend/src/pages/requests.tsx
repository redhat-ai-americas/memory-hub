import React, { useState } from 'react';
import { api } from '@/api/client';
import { Icon, Modal, ScopeLabel, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import type { MyRequest, MyRequestKind, ProjectRow } from '@/types';
import { errorMessage, shortId } from '@/utils/format';
import { MemoryPicker } from './common';

/** Building blocks for the user's requests, shared by My requests, Overview and My activity. */

export const REQUEST_KIND: Record<MyRequestKind, string> = {
  promotion: 'Promotion',
  shared_knowledge: 'Shared knowledge',
  project_access: 'Project access',
  restore: 'Restore',
  contradiction: 'Contradiction report',
};

/** The scope a request starts from and the one it asks for, as two labels. */
export const ScopeStep: React.FC<{ scope?: string | null; label?: string | null }> = ({ scope, label }) => {
  if (!scope) return null;
  if (scope === 'quarantined') return <span className="lbl ylw">{label || 'Quarantined'}</span>;
  return <ScopeLabel scope={scope}>{label || undefined}</ScopeLabel>;
};

export const ScopeChain: React.FC<{ r: MyRequest }> = ({ r }) => {
  if (r.kind === 'project_access')
    return (
      <span className="chain">
        <ScopeStep scope="project" label={r.project ?? r.to_label} />
        {r.project_role && <span className="sm"> · {r.project_role}</span>}
      </span>
    );
  return (
    <span className="chain">
      <ScopeStep scope={r.from_scope} label={r.from_label} />
      {r.from_scope && r.to_scope && <span className="muted" aria-label="to">→</span>}
      <ScopeStep scope={r.to_scope} label={r.to_label} />
    </span>
  );
};

/** Where an open request is waiting, as a yellow pill with a clock. */
export const RequestStatus: React.FC<{ r: MyRequest; short?: boolean }> = ({ r, short }) => {
  if (r.state === 'withdrawn') return <span className="lbl g">Withdrawn</span>;
  if (r.state === 'decided')
    return r.outcome === 'rejected' ? (
      <span className="lbl red">
        <Icon.X /> Rejected
      </span>
    ) : (
      <span className="lbl grn">
        <Icon.Check /> Approved
      </span>
    );
  return (
    <span className="lbl ylw pill-pending">
      <Icon.Clock />
      {short ? 'Pending' : r.waiting_for === 'project_owner' ? 'Waiting for project owner' : 'Waiting for review'}
    </span>
  );
};

export const requestIds = (r: MyRequest) => (
  <span className="mono hint">
    {r.id}
    {r.memory_id ? ` · ${shortId(r.memory_id)}` : ''}
  </span>
);

/** One line for a request: "Promote “Use metric units” to Organizational". */
export const RequestSentence: React.FC<{ r: MyRequest }> = ({ r }) => {
  if (r.kind === 'project_access')
    return (
      <>
        Join project <b>{r.project ?? r.to_label}</b>
      </>
    );
  if (r.kind === 'promotion')
    return (
      <>
        Promote “{r.title}” to <ScopeStep scope={r.to_scope} label={r.to_label} />
      </>
    );
  if (r.kind === 'restore') return <>{/^restore\b/i.test(r.title) ? r.title : `Restore “${r.title}”`}</>;
  if (r.kind === 'shared_knowledge') return <>Share “{r.title}”</>;
  return <>Report: {r.title}</>;
};

/** Submit a new request. The reviewer sees the submitted record only. */
export const NewRequestModal: React.FC<{ onClose: () => void; onCreated: (r: MyRequest) => void; initialKind?: MyRequestKind }> = ({
  onClose,
  onCreated,
  initialKind = 'promotion',
}) => {
  const toast = useToast();
  const [kind, setKind] = useState<MyRequestKind>(initialKind);
  const [memory, setMemory] = useState<{ id: string; stub: string; scope: string } | null>(null);
  const [target, setTarget] = useState('organizational');
  const [project, setProject] = useState('');
  const [projectRole, setProjectRole] = useState('contributor');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const projects = useApi<{ items: ProjectRow[] }>(() => api.projects(false), []);
  const joinable = (projects.data?.items ?? []).filter((p) => !p.my_role && !p.archived);
  const needsMemory = kind !== 'project_access';
  const ready = needsMemory ? Boolean(memory) : Boolean(project);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.createMyRequest({
        kind,
        memory_id: needsMemory ? memory?.id : undefined,
        target_scope: kind === 'promotion' || kind === 'shared_knowledge' ? target : undefined,
        project: kind === 'project_access' ? project : undefined,
        project_role: kind === 'project_access' ? projectRole : undefined,
        reason: reason.trim() || undefined,
      });
      toast('Request submitted. You can follow it in My requests.');
      onCreated(r);
      onClose();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="New request"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={!ready || busy} onClick={submit}>
            {busy ? 'Submitting…' : 'Submit request'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="form-stack">
        <div>
          <label htmlFor="nr-kind" className="flabel">
            What do you need?
          </label>
          <select id="nr-kind" className="in" value={kind} onChange={(e) => setKind(e.target.value as MyRequestKind)}>
            <option value="promotion">Promote a memory to a wider scope</option>
            <option value="shared_knowledge">Submit a memory as shared knowledge</option>
            <option value="project_access">Join a project</option>
            <option value="restore">Restore a quarantined or deleted memory</option>
          </select>
        </div>
        {needsMemory &&
          (memory ? (
            <div>
              <span className="flabel">Memory</span>
              <div className="chip">
                <ScopeLabel scope={memory.scope} />
                <span className="ellipsis" style={{ maxWidth: 320 }}>
                  {memory.stub}
                </span>
                <button type="button" aria-label="Choose another memory" onClick={() => setMemory(null)}>
                  ✕
                </button>
              </div>
            </div>
          ) : (
            <div>
              <span className="flabel">Memory</span>
              <MemoryPicker onPick={setMemory} placeholder="Search your memories" />
            </div>
          ))}
        {(kind === 'promotion' || kind === 'shared_knowledge') && (
          <div>
            <label htmlFor="nr-target" className="flabel">
              Target scope
            </label>
            <select id="nr-target" className="in" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="project">Project</option>
              <option value="campaign">Campaign</option>
              <option value="organizational">Organizational</option>
            </select>
          </div>
        )}
        {kind === 'project_access' && (
          <>
            <div>
              <label htmlFor="nr-project" className="flabel">
                Project
              </label>
              <select id="nr-project" className="in" value={project} onChange={(e) => setProject(e.target.value)}>
                <option value="">Choose a project</option>
                {joinable.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
              {projects.data && joinable.length === 0 && <p className="hint">You are already a member of every project you can see.</p>}
            </div>
            <div>
              <label htmlFor="nr-role" className="flabel">
                Role you ask for
              </label>
              <select id="nr-role" className="in" value={projectRole} onChange={(e) => setProjectRole(e.target.value)}>
                <option value="viewer">Viewer — read only</option>
                <option value="contributor">Contributor — read and write</option>
              </select>
            </div>
          </>
        )}
        <div>
          <label htmlFor="nr-reason" className="flabel">
            Why (shown to the reviewer)
          </label>
          <textarea id="nr-reason" className="in" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <p className="hint" style={{ margin: 0 }}>
          A Platform Admin or the project owner decides. While the request is open the reviewer can read the submitted version of that one memory — nothing else in your
          personal memory.
        </p>
        {err && <div className="alert err-a">{err}</div>}
      </div>
    </Modal>
  );
};
