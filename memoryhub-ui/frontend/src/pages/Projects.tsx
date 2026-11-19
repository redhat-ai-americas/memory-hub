import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { PeoplePicker } from '@/components/PeoplePicker';
import { Empty, ErrorState, Icon, Modal, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { ProjectDetail } from '@/types';
import { avatarColor, errorMessage, fmtInt, fmtRelative, initials } from '@/utils/format';
import { ConfirmModal } from './common';
import { LockIcon } from './MemoryGraph';

/**
 * Projects for platform admins (GET /api/projects). Admins create projects and,
 * in projects they administer, add and remove members. Seeing a project here
 * does not open its memories: content follows membership.
 */
const AdminProjects: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const projects = useApi(() => api.projects(false), []);
  const [creating, setCreating] = useState(false);
  const rows = projects.data?.items ?? [];
  const selected = rows.find((p) => p.name === route.params.get('project')) ?? rows[0] ?? null;
  const select = (name: string) => navigate('/projects', { project: name }, { replace: true });

  return (
    <>
      <PageHeader
        title="Projects"
        description="Create projects and manage the members of the projects you administer. Managing a project does not let you read its memory — that follows membership."
        actions={
          projects.data?.can_create && (
            <button type="button" className="btn bp" onClick={() => setCreating(true)}>
              <Icon.Plus />
              Create project
            </button>
          )
        }
      />
      <div className="body">
        <section className="card" style={{ padding: '6px 14px 4px' }}>
          {projects.error && !projects.data ? (
            <ErrorState error={projects.error} onRetry={projects.reload} />
          ) : projects.loading && !projects.data ? (
            <SkTable rows={5} cols={6} />
          ) : rows.length === 0 ? (
            <Empty title="No projects yet">Create a project for each shared context and add its members.</Empty>
          ) : (
            <div className="scroll">
              <table className="tbl proj-tbl" style={{ minWidth: 820 }}>
                <thead>
                  <tr>
                    <th>Project</th>
                    <th>Created by</th>
                    <th>Members</th>
                    <th>Memories</th>
                    <th>Last write</th>
                    <th>Your access</th>
                    <th>
                      <span className="vh">Open</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={p.name} className={`clickable ${p.name === selected?.name ? 'is-sel' : ''}`} onClick={() => select(p.name)}>
                      <td>
                        <span className="b6">{p.name}</span>
                        {p.invite_only && <span className="lbl g" style={{ marginLeft: 6 }}>invite-only</span>}
                        {p.description && (
                          <div className="hint ellipsis" style={{ maxWidth: 260 }}>
                            {p.description}
                          </div>
                        )}
                      </td>
                      <td className="sm">{p.created_by}</td>
                      <td>{fmtInt(p.members)}</td>
                      <td>{fmtInt(p.memories)}</td>
                      <td className="sm">{p.last_write ? fmtRelative(p.last_write) : '—'}</td>
                      <td>
                        {p.my_role === 'admin' ? (
                          <span className="lbl blue">Project admin</span>
                        ) : p.my_role ? (
                          <span className="lbl s-project">Member · content</span>
                        ) : (
                          <span className="lbl g">
                            <LockIcon size={11} /> Metadata only
                          </span>
                        )}
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <a className="sm" href={buildHash(`/project/${encodeURIComponent(p.name)}`)}>
                          Open
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {selected && <ProjectPanel key={selected.name} name={selected.name} onChanged={projects.reload} />}
      </div>
      {creating && (
        <ProjectForm
          onClose={() => setCreating(false)}
          onSaved={(name) => {
            toast(`Project ${name} created.`);
            projects.reload();
            select(name);
          }}
        />
      )}
    </>
  );
};

/** Session focus topics agents declared in the project over 30 days (Valkey, when configured). */
export const FocusHistory: React.FC<{ data: ProjectDetail }> = ({ data }) => {
  const total = (data.focus_history ?? []).reduce((a, f) => a + f.count, 0);
  return (
    <section className="card">
      <div className="ch">
        <h2 data-h="3">Session focus · last 30 days</h2>
        <span className="sm muted">Topics only · no memory text</span>
      </div>
      {!data.focus_available || !data.focus_history?.length ? (
        <p className="sm muted" style={{ margin: 0 }}>
          {data.focus_available ? 'No agent declared a session focus here in the last 30 days.' : 'Focus history is not available on this deployment.'}
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {data.focus_history.map((f) => {
            const pct = total ? Math.round((f.count / total) * 100) : 0;
            return (
              <div key={f.focus}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }} className="sm">
                  <span>{f.focus}</span>
                  <span>{pct}%</span>
                </div>
                <div className="bar thin">
                  <span style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

/** One project: details, members (add and remove when you administer it) and session focus. */
const ProjectPanel: React.FC<{ name: string; onChanged?: () => void }> = ({ name, onChanged }) => {
  const toast = useToast();
  const { me } = useApp();
  const { data, error, loading, reload } = useApi<ProjectDetail>(() => api.project(name), [name]);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  if (error && !data)
    return (
      <div className="card">
        <ErrorState error={error} onRetry={reload} compact />
      </div>
    );
  if (loading && !data)
    return (
      <div className="card">
        <SkLines lines={8} />
      </div>
    );
  if (!data) return null;
  const changed = () => {
    reload();
    onChanged?.();
  };

  return (
    <div className="detail-grid">
      <section className="card" style={{ flex: '999 1 560px', minWidth: 0 }}>
        <div className="ch">
          <div>
            <span className="lbl s-project">Project</span>
            <h2 data-h="3" style={{ fontSize: 20, marginTop: 8 }}>
              {data.name}
            </h2>
          </div>
        </div>
        <p className="sm muted" style={{ margin: '0 0 14px' }}>
          {data.description ? `${data.description}. ` : ''}
          {data.invite_only ? 'Invite-only: members are added by a project admin.' : 'Open: users in the tenant can see it; members are added by a project admin.'}
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12, marginBottom: 18 }}>
          <div>
            <div className="sm muted">Memories</div>
            <div className="num-lg">{fmtInt(data.memories)}</div>
          </div>
          <div>
            <div className="sm muted">Members</div>
            <div className="num-lg">{fmtInt(data.members)}</div>
          </div>
          <div>
            <div className="sm muted">Last write</div>
            <div className="num-lg">{data.last_write ? fmtRelative(data.last_write) : '—'}</div>
          </div>
        </div>
        <div className="ch" style={{ marginBottom: 10 }}>
          <b className="sm">Members</b>
          {data.can_manage && (
            <button type="button" className="btn bl sm" onClick={() => setAdding(true)}>
              + Add member
            </button>
          )}
        </div>
        {!data.can_manage && (
          <p className="hint" style={{ margin: '0 0 10px' }}>
            Only an admin of this project can add or remove members.
          </p>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14 }}>
          {data.members_list.length === 0 && <span className="sm muted">No members yet.</span>}
          {data.members_list.map((m) => (
            <div key={m.user_id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="mav" style={{ background: avatarColor(m.user_id) }}>
                {initials(m.user_id)}
              </span>
              <span style={{ flex: 1, minWidth: 0 }}>
                {m.user_id}
                {m.user_id === me?.username && ' (you)'}
                {m.joined_at && (
                  <span className="hint" style={{ display: 'block' }}>
                    Joined {fmtRelative(m.joined_at).toLowerCase()}
                  </span>
                )}
              </span>
              <span className={`lbl ${m.role === 'admin' ? 'blue' : 'g'}`}>{m.role}</span>
              {/* The BFF never lets an admin remove themselves (the last-admin guard stays with Core). */}
              {data.can_manage && m.user_id !== me?.username && (
                <button type="button" className="btn bl sm" aria-label={`Remove ${m.user_id}`} style={{ padding: '2px 6px' }} onClick={() => setRemoving(m.user_id)}>
                  ✕
                </button>
              )}
            </div>
          ))}
        </div>
      </section>

      <aside className="col-side" style={{ flex: '1 1 340px' }}>
        <FocusHistory data={data} />
        {data.campaigns.length > 0 && (
          <section className="card">
            <h2 data-h="3" style={{ marginBottom: 12 }}>
              Campaigns
            </h2>
            {data.campaigns.map((c) => (
              <div key={c.id} className="evrow" style={{ justifyContent: 'space-between' }}>
                <span className="sm">{c.name}</span>
                <span className={`lbl ${c.status === 'active' ? 'grn' : 'g'}`}>{c.status}</span>
              </div>
            ))}
          </section>
        )}
      </aside>

      {adding && (
        <MemberForm
          project={data.name}
          current={data.members_list.map((m) => m.user_id)}
          onClose={() => setAdding(false)}
          onSaved={() => {
            toast('Members updated.');
            changed();
          }}
        />
      )}
      {removing && (
        <ConfirmModal
          title="Remove member?"
          confirmLabel="Remove"
          danger
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            await api.removeMember(data.name, removing);
            toast(`${removing} removed from ${data.name}.`);
            changed();
          }}
        >
          <b>{removing}</b> loses read and write access to <b>{data.name}</b> project memories. Their existing memories stay. The change is audited.
        </ConfirmModal>
      )}
    </div>
  );
};

/** /project/{name}: the same panel on its own page, for links. */
export const ProjectSettings: React.FC<{ route: HashRoute }> = ({ route }) => {
  const name = decodeURIComponent(route.path.slice('/project/'.length));
  return (
    <>
      <PageHeader
        title={name}
        crumbs={[{ label: 'Projects', href: buildHash('/projects', { project: name }) }, { label: name }]}
        description="Details, members and recent session focus. Adding and removing members is audited."
        actions={
          <a className="btn bs" href={buildHash('/projects', { project: name })}>
            Back to list
          </a>
        }
      />
      <div className="body">
        <ProjectPanel name={name} />
      </div>
    </>
  );
};

/** POST /api/projects: name, description, invite-only and the first members. */
const ProjectForm: React.FC<{ onClose: () => void; onSaved: (name: string) => void }> = ({ onClose, onSaved }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [inviteOnly, setInviteOnly] = useState(true);
  const [admins, setAdmins] = useState<string[]>([]);
  const [members, setMembers] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const memberIds = members.filter((u) => !admins.includes(u));
  const count = admins.length + memberIds.length;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.createProject({
        name: name.trim(),
        description: description.trim() || undefined,
        invite_only: inviteOnly,
        members: [...admins.map((u) => ({ user_id: u, role: 'admin' as const })), ...memberIds.map((u) => ({ user_id: u, role: 'member' as const }))],
      });
      onSaved(name.trim());
      onClose();
    } catch (e2) {
      setErr(errorMessage(e2));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="Create project" onClose={onClose}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="f">
          <label htmlFor="pn">Name</label>
          <input id="pn" className="in" required pattern="[A-Za-z0-9][A-Za-z0-9._\-]*" value={name} onChange={(e) => setName(e.target.value)} placeholder="memoryhub-ui" />
          <span className="hint">Letters, numbers, dots, dashes and underscores. Agents use this as the project ID in .memoryhub.yaml.</span>
        </div>
        <div className="f">
          <label htmlFor="pd">Description</label>
          <input id="pd" className="in" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="f">
          <label htmlFor="pa">Project admins</label>
          <PeoplePicker id="pa" value={admins} onChange={setAdmins} kinds={['person']} placeholder="Choose who manages members" />
          <span className="hint">You become an admin of the project you create. Add other admins here.</span>
        </div>
        <div className="f">
          <label htmlFor="pm">Members</label>
          <PeoplePicker id="pm" value={members} onChange={setMembers} exclude={admins} excludeNote="already an admin" placeholder="Choose people and their agents" />
          <span className="hint">Only members can read and write this project’s memories. Add the agents people use, too.</span>
        </div>
        <label className="swrow">
          <span>
            <b>Invite-only</b>
            <div className="hint">Hidden from users who are not members. Open projects are listed for every user in the tenant.</div>
          </span>
          <input type="checkbox" checked={inviteOnly} onChange={(e) => setInviteOnly(e.target.checked)} />
        </label>
        {err && <div className="alert err-a">{err}</div>}
        <div className="modal-actions">
          <button type="submit" className="btn bp" disabled={busy}>
            {count ? `Create with ${count} ${count === 1 ? 'person' : 'people'}` : 'Create project'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
};

/** POST /api/projects/{name}/members, one person at a time. */
const MemberForm: React.FC<{ project: string; current: string[]; onClose: () => void; onSaved: () => void }> = ({ project, current, onClose, onSaved }) => {
  const [people, setPeople] = useState<string[]>([]);
  const [role, setRole] = useState<'member' | 'admin'>('member');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const add = async () => {
    setBusy(true);
    setErr(null);
    const failed: string[] = [];
    for (const user_id of people) {
      try {
        await api.addMember(project, { user_id, role });
      } catch (e) {
        failed.push(`${user_id}: ${errorMessage(e)}`);
      }
    }
    setBusy(false);
    if (failed.length) {
      setErr(failed.join(' · '));
      setPeople(people.filter((p) => failed.some((f) => f.startsWith(`${p}:`))));
      if (failed.length < people.length) onSaved();
      return;
    }
    onSaved();
    onClose();
  };
  return (
    <Modal
      title={`Add members to ${project}`}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={!people.length || busy} onClick={add}>
            {busy ? 'Adding…' : people.length > 1 ? `Add ${people.length} members` : 'Add member'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="mu">People and agents</label>
        <PeoplePicker id="mu" value={people} onChange={setPeople} exclude={current} placeholder="Choose who to add" autoFocus />
      </div>
      <div className="f">
        <label htmlFor="mr">Role</label>
        <select id="mr" className="in" value={role} onChange={(e) => setRole(e.target.value as 'member' | 'admin')}>
          <option value="member">member — reads and writes project memories</option>
          <option value="admin">admin — also manages members</option>
        </select>
      </div>
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

export default AdminProjects;
