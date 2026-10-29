import React, { useState } from 'react';
import { api } from '@/api/client';
import { useApp } from '@/components/Shell';
import { Empty, Modal, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import type { ProjectRow, TeamRow } from '@/types';
import { avatarColor, errorMessage, fmtRelative, initials } from '@/utils/format';
import { ConfirmModal } from './common';

/**
 * Teams — groups of people. A team works on several projects and a project
 * has members from several teams; linking a team to a project gives every
 * member project access (kept in sync by the backend).
 */

export const TeamsTable: React.FC<{
  teams: TeamRow[];
  loading: boolean;
  active: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  filter: string;
}> = ({ teams, loading, active, onSelect, onCreate, filter }) => {
  const rows = teams.filter((t) => t.name.toLowerCase().includes(filter.toLowerCase()) || t.members.some((m) => m.user_id.includes(filter.toLowerCase())));
  if (loading) return <SkTable rows={4} cols={4} />;
  if (rows.length === 0)
    return (
      <Empty
        title={filter ? 'No teams match' : 'No teams yet'}
        action={
          !filter && (
            <button type="button" className="btn bp" onClick={onCreate}>
              Create team
            </button>
          )
        }
      >
        {filter ? 'Try another name or person.' : 'A team is a group of people. Link it to projects and every member gets access — one team can work on many projects.'}
      </Empty>
    );
  return (
    <div className="scroll">
      <table className="tbl" style={{ minWidth: 640 }}>
        <thead>
          <tr>
            <th>Team</th>
            <th>People</th>
            <th>Projects</th>
            <th>Lead</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => {
            const lead = t.members.find((m) => m.role === 'lead');
            return (
              <tr key={t.id} className={`clickable ${t.id === active ? 'is-sel' : ''}`} onClick={() => onSelect(t.id)}>
                <td>
                  <span style={{ fontWeight: 600, color: '#0066cc' }}>{t.name}</span>
                  <div className="sm muted">{t.description || '—'}</div>
                </td>
                <td>
                  <div className="avstack" aria-label={`${t.members.length} people`}>
                    {t.members.slice(0, 5).map((m) => (
                      <span key={m.user_id} className="mav" title={m.user_id} style={{ background: avatarColor(m.user_id) }}>
                        {initials(m.user_id)}
                      </span>
                    ))}
                    {t.members.length > 5 && <span className="sm muted">+{t.members.length - 5}</span>}
                    {t.members.length === 0 && <span className="sm muted">—</span>}
                  </div>
                </td>
                <td>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {t.projects.length ? (
                      t.projects.map((p) => (
                        <span className="lbl s-project" key={p}>
                          {p}
                        </span>
                      ))
                    ) : (
                      <span className="sm muted">No projects</span>
                    )}
                  </div>
                </td>
                <td className="sm">{lead?.user_id ?? '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export const TeamPanel: React.FC<{ team: TeamRow; projects: ProjectRow[]; onChanged: () => void; onDeleted: () => void }> = ({ team, projects, onChanged, onDeleted }) => {
  const toast = useToast();
  const { me, role } = useApp();
  const canManage = role !== 'user' || team.members.some((m) => m.user_id === me?.username && m.role === 'lead');
  const [modal, setModal] = useState<null | 'member' | 'project' | 'delete' | 'edit'>(null);
  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      toast(done);
      onChanged();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };
  const freeProjects = projects.filter((p) => !team.projects.includes(p.name));
  return (
    <>
      <div className="card">
        <div className="ch">
          <div>
            <span className="lbl pur">Team</span>
            <h3 style={{ fontSize: 20, marginTop: 8 }}>{team.name}</h3>
          </div>
          {canManage && (
            <button type="button" className="btn bg" onClick={() => setModal('edit')}>
              Edit
            </button>
          )}
        </div>
        <p className="sm muted" style={{ margin: '0 0 14px' }}>
          {team.description ? `${team.description}. ` : ''}Created {fmtRelative(team.created_at)} by {team.created_by}.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, marginBottom: 18 }}>
          <div>
            <div className="sm muted">People</div>
            <div className="num-lg">{team.members.length}</div>
          </div>
          <div>
            <div className="sm muted">Projects</div>
            <div className="num-lg">{team.projects.length}</div>
          </div>
        </div>

        <div className="ch" style={{ marginBottom: 10 }}>
          <b className="sm">Works on</b>
          {canManage && (
            <button type="button" className="btn bl sm" disabled={!freeProjects.length} onClick={() => setModal('project')}>
              + Add project
            </button>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 18 }}>
          {team.projects.length === 0 && <span className="sm muted">Not linked to any project yet. Linked projects give every member access.</span>}
          {team.projects.map((p) => (
            <div key={p} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="lbl s-project">project</span>
              <a href={buildHash('/projects', { project: p })} style={{ flex: 1 }}>
                {p}
              </a>
              {canManage && (
                <button
                  type="button"
                  className="btn bl sm"
                  aria-label={`Unlink ${p}`}
                  style={{ padding: '2px 6px' }}
                  onClick={() => run(() => api.unlinkTeamProject(team.id, p), `${team.name} no longer works on ${p}.`)}
                >
                  ✕
                </button>
              )}
            </div>
          ))}
        </div>

        <div className="ch" style={{ marginBottom: 10 }}>
          <b className="sm">People</b>
          {canManage && (
            <button type="button" className="btn bl sm" onClick={() => setModal('member')}>
              + Add person
            </button>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14 }}>
          {team.members.map((m) => (
            <div key={m.user_id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="mav" style={{ background: avatarColor(m.user_id) }}>
                {initials(m.user_id)}
              </span>
              <span style={{ flex: 1 }}>
                {m.user_id}
                {m.user_id === me?.username && <span className="sm muted"> (you)</span>}
              </span>
              <span className={`lbl ${m.role === 'lead' ? 'blue' : 'g'}`}>{m.role}</span>
              {canManage && m.role !== 'lead' && (
                <button type="button" className="btn bl sm" onClick={() => run(() => api.addTeamMember(team.id, m.user_id, 'lead'), `${m.user_id} now leads ${team.name}.`)}>
                  Make lead
                </button>
              )}
              {(canManage || m.user_id === me?.username) && (
                <button
                  type="button"
                  className="btn bl sm"
                  aria-label={`Remove ${m.user_id}`}
                  style={{ padding: '2px 6px' }}
                  onClick={() => run(() => api.removeTeamMember(team.id, m.user_id), `${m.user_id} left ${team.name}.`)}
                >
                  ✕
                </button>
              )}
            </div>
          ))}
        </div>
        <p className="hint" style={{ margin: '14px 0 0' }}>
          Members get access to every project the team works on. Direct project memberships are not touched.
        </p>
        {canManage && (
          <button type="button" className="btn bl danger sm" style={{ marginTop: 10 }} onClick={() => setModal('delete')}>
            Delete team
          </button>
        )}
      </div>

      {modal === 'member' && (
        <PersonModal
          title={`Add a person to ${team.name}`}
          exclude={team.members.map((m) => m.user_id)}
          onClose={() => setModal(null)}
          onPick={(user, asLead) => {
            setModal(null);
            void run(() => api.addTeamMember(team.id, user, asLead ? 'lead' : 'member'), `${user} joined ${team.name}.`);
          }}
        />
      )}
      {modal === 'project' && (
        <Modal title={`Link ${team.name} to a project`} onClose={() => setModal(null)}>
          <p className="sm muted" style={{ margin: 0 }}>
            Every member of {team.name} gets access to the project. You need to be an admin of that project.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {freeProjects.map((p) => (
              <button
                key={p.name}
                type="button"
                className="item"
                onClick={() => {
                  setModal(null);
                  void run(() => api.linkTeamProject(team.id, p.name), `${team.name} now works on ${p.name}.`);
                }}
              >
                <b>{p.name}</b>
                <div className="sm muted">
                  {p.members} members · {p.description || 'no description'}
                </div>
              </button>
            ))}
          </div>
        </Modal>
      )}
      {modal === 'edit' && (
        <TeamForm
          existing={team}
          projects={projects}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            onChanged();
          }}
        />
      )}
      {modal === 'delete' && (
        <ConfirmModal
          title={`Delete ${team.name}?`}
          confirmLabel="Delete team"
          danger
          onClose={() => setModal(null)}
          onConfirm={async () => {
            await api.deleteTeam(team.id);
            toast(`${team.name} deleted.`);
            onDeleted();
          }}
        >
          Members lose the project access they had only through this team ({team.projects.join(', ') || 'no projects'}). Their memories stay. The change is audited.
        </ConfirmModal>
      )}
    </>
  );
};

export const TeamForm: React.FC<{ existing?: TeamRow; projects: ProjectRow[]; onClose: () => void; onSaved: (id: string) => void }> = ({ existing, projects, onClose, onSaved }) => {
  const toast = useToast();
  const [name, setName] = useState(existing?.name ?? '');
  const [description, setDescription] = useState(existing?.description ?? '');
  const [people, setPeople] = useState('');
  const [chosen, setChosen] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (existing) {
        await api.updateTeam(existing.id, { name: name.trim(), description: description.trim() });
        toast('Team updated.');
        onSaved(existing.id);
      } else {
        const res = await api.createTeam({
          name: name.trim(),
          description: description.trim() || undefined,
          members: people.split(/[\s,]+/).map((p) => p.trim()).filter(Boolean),
          projects: chosen,
        });
        toast(`Team ${res.name} created${res.added ? ` · ${res.added} project memberships granted` : ''}.`);
        onSaved(res.id);
      }
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={existing ? `Edit ${existing.name}` : 'Create team'}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={busy || !name.trim()} onClick={save}>
            {existing ? 'Save' : 'Create team'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="tn">Team name</label>
        <input id="tn" className="in" value={name} onChange={(e) => setName(e.target.value)} placeholder="Platform SRE" />
      </div>
      <div className="f">
        <label htmlFor="td">Description (optional)</label>
        <input id="td" className="in" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Runs the OpenShift AI clusters" />
      </div>
      {!existing && (
        <>
          <div className="f">
            <label htmlFor="tp">People</label>
            <input id="tp" className="in mono" value={people} onChange={(e) => setPeople(e.target.value)} placeholder="arivera, mchen, jpatel" />
            <span className="hint">Usernames, comma-separated. You join as team lead.</span>
          </div>
          <div className="f">
            <span className="lbl-t">Works on projects</span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {projects.length === 0 && <span className="sm muted">No projects yet.</span>}
              {projects.map((p) => (
                <label key={p.name} className="tg" style={{ background: chosen.includes(p.name) ? '#e7f1fa' : '#fff' }}>
                  <input
                    type="checkbox"
                    checked={chosen.includes(p.name)}
                    onChange={() => setChosen((c) => (c.includes(p.name) ? c.filter((x) => x !== p.name) : [...c, p.name]))}
                  />{' '}
                  {p.name}
                </label>
              ))}
            </div>
            <span className="hint">Members get access to these projects. Needs project admin rights.</span>
          </div>
        </>
      )}
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

const PersonModal: React.FC<{ title: string; exclude: string[]; onClose: () => void; onPick: (user: string, asLead: boolean) => void }> = ({ title, exclude, onClose, onPick }) => {
  const { data } = useApi(() => api.identities().catch(() => null), []);
  const [user, setUser] = useState('');
  const [lead, setLead] = useState(false);
  const people = (data?.items ?? []).filter((i) => i.type === 'user' && !exclude.includes(i.id)).slice(0, 12);
  return (
    <Modal
      title={title}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bp" disabled={!user.trim()} onClick={() => onPick(user.trim(), lead)}>
            Add
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="pu">Username</label>
        <input id="pu" className="in mono" value={user} onChange={(e) => setUser(e.target.value)} placeholder="OpenShift username" autoFocus />
      </div>
      {people.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {people.map((p) => (
            <button key={p.id} type="button" className="tg" onClick={() => setUser(p.id)}>
              {p.id}
            </button>
          ))}
        </div>
      )}
      <label className="tg" style={{ alignSelf: 'flex-start' }}>
        <input type="checkbox" checked={lead} onChange={(e) => setLead(e.target.checked)} /> Team lead (can manage the team)
      </label>
    </Modal>
  );
};

/** On a project: which teams work on it, and add one. */
export const ProjectTeams: React.FC<{ project: string; teams: { id: string; name: string; members: number }[]; onChanged: () => void }> = ({ project, teams, onChanged }) => {
  const toast = useToast();
  const all = useApi(() => api.teams(), []);
  const [open, setOpen] = useState(false);
  const free = (all.data?.items ?? []).filter((t) => !teams.some((x) => x.id === t.id));
  return (
    <>
      <div className="ch" style={{ margin: '18px 0 10px' }}>
        <b className="sm">Teams</b>
        <button type="button" className="btn bl sm" disabled={!free.length} onClick={() => setOpen(true)}>
          + Add team
        </button>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {teams.length === 0 && <span className="sm muted">No team works on this project yet.</span>}
        {teams.map((t) => (
          <a key={t.id} className="lbl pur link-plain" href={buildHash('/projects', { kind: 'teams', team: t.id })}>
            {t.name} · {t.members}
          </a>
        ))}
      </div>
      {open && (
        <Modal title={`Add a team to ${project}`} onClose={() => setOpen(false)}>
          <p className="sm muted" style={{ margin: 0 }}>
            Every member of the team gets access to {project}.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {free.map((t) => (
              <button
                key={t.id}
                type="button"
                className="item"
                onClick={async () => {
                  setOpen(false);
                  try {
                    const res = await api.linkTeamProject(t.id, project);
                    toast(`${t.name} now works on ${project}${res.added ? ` · ${res.added} people got access` : ''}.`);
                    onChanged();
                  } catch (e) {
                    toast(errorMessage(e), 'err');
                  }
                }}
              >
                <b>{t.name}</b>
                <div className="sm muted">
                  {t.members.length} people · {t.projects.length} projects
                </div>
              </button>
            ))}
          </div>
        </Modal>
      )}
    </>
  );
};
