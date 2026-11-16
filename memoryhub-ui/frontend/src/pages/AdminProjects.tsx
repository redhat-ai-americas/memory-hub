import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, Modal, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { ProjectDetail, ProjectRow, TeamRow } from '@/types';
import { errorMessage, fmtInt, fmtRelative } from '@/utils/format';
import { ConfirmModal } from './common';
import { LockIcon } from './MemoryGraph';
import { CampaignForm, CampaignPanel, EnrollForm, LifecycleModal, MemberForm, ProjectForm, ProjectPanel } from './Projects';
import { TeamForm, TeamPanel, TeamsTable } from './Teams';

/**
 * Projects & teams for platform admins: every project in a table on top, the
 * selected project's members, policy, focus and lifecycle below. A double
 * click opens a short summary with a way to the full settings page.
 */

type Kind = 'projects' | 'teams' | 'campaigns' | 'archived';

const ROLE_NAME: Record<string, string> = { owner: 'Owner', admin: 'Project Manager', manager: 'Project Manager', member: 'Contributor', contributor: 'Contributor', viewer: 'Viewer' };
const RIGHTS: Record<string, [boolean, boolean, boolean]> = {
  owner: [true, true, true],
  admin: [true, true, true],
  manager: [true, true, true],
  member: [true, true, false],
  contributor: [true, true, false],
  viewer: [true, false, false],
};

const ownerOf = (p: { owner?: string | null; created_by: string }) => p.owner || p.created_by;
const quotaPct = (p: ProjectRow) => (p.policies?.max_memories ? Math.round((p.memories / p.policies.max_memories) * 100) : null);

const AdminProjects: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const raw = route.params.get('kind');
  const kind: Kind = raw === 'teams' || raw === 'campaigns' || raw === 'archived' ? raw : 'projects';
  const projects = useApi(() => api.projects(false), []);
  const teams = useApi(() => api.teams(), []);
  const campaigns = useApi(() => api.campaigns(), []);
  const [modal, setModal] = useState<null | 'project' | 'team' | 'campaign' | 'edit' | 'member' | 'enroll'>(null);
  const [lifecycle, setLifecycle] = useState<null | { action: 'archive' | 'unarchive' | 'delete'; project: ProjectRow }>(null);
  const [peek, setPeek] = useState<null | { kind: 'project'; row: ProjectRow } | { kind: 'team'; row: TeamRow }>(null);
  const [token, setToken] = useState(0);

  const all = projects.data?.items ?? [];
  const active = all.filter((p) => !p.archived);
  const archived = all.filter((p) => p.archived);
  const rows = kind === 'archived' ? archived : active;
  const selected = rows.find((p) => p.name === route.params.get('project')) ?? rows[0] ?? null;
  const teamRows = teams.data?.items ?? [];
  const selTeam = teamRows.find((t) => t.id === route.params.get('team')) ?? teamRows[0] ?? null;
  const camps = campaigns.data?.items ?? [];
  const selCampaign = camps.find((c) => c.id === route.params.get('campaign')) ?? camps[0] ?? null;

  const setParam = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(route.params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    navigate('/projects', next, { replace: true });
  };
  const reloadAll = () => {
    projects.reload();
    teams.reload();
    campaigns.reload();
    setToken((t) => t + 1);
  };

  return (
    <>
      <PageHeader
        title="Projects & teams"
        description="Create, archive, restore and delete projects; set owners, quotas, policies and project roles; manage teams and time-boxed campaigns. Managing a project here does not let you read its memory — that follows membership or an assigned workflow."
        actions={
          <>
            {kind === 'campaigns' ? (
              <button type="button" className="btn bs" onClick={() => setModal('campaign')}>
                Create campaign
              </button>
            ) : (
              <button type="button" className="btn bs" onClick={() => setModal('team')}>
                Create team
              </button>
            )}
            <button type="button" className="btn bp" onClick={() => setModal('project')}>
              <Icon.Plus />
              Create project
            </button>
          </>
        }
        tabs={
          <Tabs
            label="Kind"
            value={kind}
            onChange={(k) => navigate('/projects', k === 'projects' ? undefined : { kind: k }, { replace: true })}
            tabs={[
              { value: 'projects', label: 'Projects', count: projects.data ? active.length : null },
              { value: 'teams', label: 'Teams', count: teams.data ? teamRows.length : null },
              { value: 'campaigns', label: 'Campaigns', count: campaigns.data ? camps.length : null },
              { value: 'archived', label: 'Archived', count: projects.data ? archived.length : null },
            ]}
          />
        }
      />
      <div className="body">
        {kind === 'projects' || kind === 'archived' ? (
          <>
            <section className="card" style={{ padding: '6px 14px 4px' }}>
              {projects.error && !projects.data ? (
                <ErrorState error={projects.error} onRetry={projects.reload} />
              ) : projects.loading && !projects.data ? (
                <SkTable rows={5} cols={7} />
              ) : rows.length === 0 ? (
                <Empty title={kind === 'archived' ? 'No archived projects' : 'No projects yet'}>
                  {kind === 'archived'
                    ? 'Archived projects are read-only and can be restored here.'
                    : 'Create a project for each shared context and add its members.'}
                </Empty>
              ) : (
                <div className="scroll">
                  <table className="tbl proj-tbl" style={{ minWidth: 900 }}>
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Owner</th>
                        <th>Members</th>
                        <th>Memories</th>
                        <th>Quota</th>
                        <th>Your access</th>
                        <th>Status</th>
                        <th>
                          <span className="vh">Manage</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((p) => {
                        const pct = quotaPct(p);
                        return (
                          <tr
                            key={p.name}
                            className={`clickable ${p.name === selected?.name ? 'is-sel' : ''}`}
                            onClick={() => setParam({ project: p.name })}
                            onDoubleClick={() => setPeek({ kind: 'project', row: p })}
                            title="Double-click for a summary"
                          >
                            <td>
                              <span className="b6">{p.name}</span>
                              {p.description && <div className="hint ellipsis" style={{ maxWidth: 260 }}>{p.description}</div>}
                            </td>
                            <td className="sm">{ownerOf(p)}</td>
                            <td>{fmtInt(p.members)}</td>
                            <td>{fmtInt(p.memories)}</td>
                            <td style={{ minWidth: 120 }}>
                              {pct === null ? (
                                <span className="sm muted">No limit</span>
                              ) : (
                                <>
                                  <div className="bar thin" style={{ maxWidth: 110 }}>
                                    <span style={{ width: `${Math.min(100, pct)}%`, background: pct >= 90 ? '#c9190b' : pct >= 75 ? '#f0ab00' : undefined }} />
                                  </div>
                                  <div className="hint">
                                    {pct}% of {fmtInt(p.policies!.max_memories!)}
                                  </div>
                                </>
                              )}
                            </td>
                            <td>
                              {p.my_role ? (
                                <span className="lbl s-project">Member · content</span>
                              ) : (
                                <span className="lbl g">
                                  <LockIcon size={11} /> Metadata only
                                </span>
                              )}
                            </td>
                            <td>{p.archived ? <span className="lbl g">Archived</span> : <span className="lbl grn">Active</span>}</td>
                            <td onClick={(e) => e.stopPropagation()}>
                              <a className="sm" href={buildHash(`/project/${encodeURIComponent(p.name)}`)}>
                                Manage
                              </a>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            {selected && (
              <SelectedProject
                key={`${selected.name}-${token}`}
                row={selected}
                onAddMember={() => setModal('member')}
                onEdit={() => setModal('edit')}
                onLifecycle={(action) => setLifecycle({ action, project: selected })}
              />
            )}
          </>
        ) : kind === 'teams' ? (
          <>
            <section className="card" style={{ padding: 0 }}>
              <TeamsTable
                teams={teamRows}
                loading={teams.loading && !teams.data}
                active={selTeam?.id ?? null}
                onSelect={(id) => setParam({ team: id })}
                onOpen={(id) => {
                  const t = teamRows.find((x) => x.id === id);
                  if (t) setPeek({ kind: 'team', row: t });
                }}
                onCreate={() => setModal('team')}
                filter=""
              />
            </section>
            {selTeam && (
              <div className="detail-grid">
                <TeamPanel
                  key={selTeam.id}
                  team={selTeam}
                  projects={all}
                  onChanged={reloadAll}
                  onDeleted={() => {
                    setParam({ team: undefined });
                    reloadAll();
                  }}
                />
              </div>
            )}
          </>
        ) : (
          <>
            <section className="card" style={{ padding: '6px 14px 4px' }}>
              {camps.length === 0 ? (
                <Empty title="No campaigns yet">Campaigns group projects under one policy and memory lifetime for a bounded initiative.</Empty>
              ) : (
                <div className="scroll">
                  <table className="tbl" style={{ minWidth: 700 }}>
                    <thead>
                      <tr>
                        <th>Campaign</th>
                        <th>Status</th>
                        <th>Projects</th>
                        <th>Memories</th>
                        <th>Default TTL</th>
                      </tr>
                    </thead>
                    <tbody>
                      {camps.map((c) => (
                        <tr key={c.id} className={`clickable ${c.id === selCampaign?.id ? 'is-sel' : ''}`} onClick={() => setParam({ campaign: c.id })}>
                          <td>
                            <span className="b6">{c.name}</span>
                            <div className="hint">{c.description || '—'}</div>
                          </td>
                          <td>
                            <span className={`lbl ${c.status === 'active' ? 'grn' : 'g'}`}>{c.status}</span>
                          </td>
                          <td>{c.projects.length}</td>
                          <td>{fmtInt(c.memories)}</td>
                          <td className="sm">{c.default_ttl_days ? `${c.default_ttl_days} days` : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            {selCampaign && (
              <div className="detail-grid">
                <CampaignPanel campaign={selCampaign} projects={all} onChanged={reloadAll} onEnroll={() => setModal('enroll')} />
              </div>
            )}
          </>
        )}
      </div>

      {peek?.kind === 'project' && <ProjectPeek row={peek.row} onClose={() => setPeek(null)} />}
      {peek?.kind === 'team' && <TeamPeek team={peek.row} onClose={() => setPeek(null)} />}
      {modal === 'project' && (
        <ProjectForm
          onClose={() => setModal(null)}
          onSaved={(name) => {
            toast(`Project ${name} created.`);
            reloadAll();
            setParam({ kind: undefined, project: name });
          }}
        />
      )}
      {modal === 'edit' && selected && (
        <ProjectForm
          existing={selected}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Project updated.');
            reloadAll();
          }}
        />
      )}
      {modal === 'member' && selected && (
        <MemberForm
          project={selected.name}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Member added.');
            reloadAll();
          }}
        />
      )}
      {modal === 'team' && (
        <TeamForm
          projects={all}
          onClose={() => setModal(null)}
          onSaved={(id) => {
            setModal(null);
            reloadAll();
            navigate('/projects', { kind: 'teams', team: id }, { replace: true });
          }}
        />
      )}
      {modal === 'campaign' && (
        <CampaignForm
          projects={all}
          onClose={() => setModal(null)}
          onSaved={(id) => {
            toast('Campaign created.');
            reloadAll();
            navigate('/projects', { kind: 'campaigns', campaign: id }, { replace: true });
          }}
        />
      )}
      {modal === 'enroll' && selCampaign && (
        <EnrollForm
          campaign={selCampaign}
          projects={all.filter((p) => !selCampaign.projects.includes(p.name))}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Project enrolled.');
            reloadAll();
          }}
        />
      )}
      {lifecycle && (
        <LifecycleModal
          action={lifecycle.action}
          project={lifecycle.project}
          onClose={() => setLifecycle(null)}
          onDone={(message) => {
            toast(message);
            reloadAll();
            setParam({ project: undefined });
          }}
        />
      )}
    </>
  );
};

/** The selected project: members with roles and rights, loading policy, focus and lifecycle. */
const SelectedProject: React.FC<{
  row: ProjectRow;
  onAddMember: () => void;
  onEdit: () => void;
  onLifecycle: (action: 'archive' | 'unarchive' | 'delete') => void;
}> = ({ row, onAddMember, onEdit, onLifecycle }) => {
  const toast = useToast();
  const { me } = useApp();
  const { data, error, loading, reload } = useApi<ProjectDetail>(() => api.project(row.name), [row.name]);
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
  const owner = ownerOf(data);
  const settings = buildHash(`/project/${encodeURIComponent(data.name)}`);
  const total = (data.focus_history ?? []).reduce((a, f) => a + f.count, 0);
  const changeRole = async (userId: string, next: 'member' | 'admin') => {
    try {
      await api.setMemberRole(data.name, userId, next);
      toast(`${userId} is now ${next === 'admin' ? 'a Project Manager' : 'a Contributor'} of ${data.name}.`);
      reload();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };

  return (
    <div className="detail-grid">
      <section className="card" style={{ flex: '999 1 560px', minWidth: 0 }}>
        <div className="ch">
          <h2 data-h="3">{data.name} · members</h2>
          {data.can_manage !== false && !data.archived && (
            <button type="button" className="btn bs sm" onClick={onAddMember}>
              <Icon.Plus />
              Add member
            </button>
          )}
        </div>
        {data.members_list.length === 0 ? (
          <p className="sm muted">No members yet.</p>
        ) : (
          <div className="scroll">
            <table className="tbl" style={{ minWidth: 560 }}>
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Project role</th>
                  <th>Read</th>
                  <th>Write</th>
                  <th>Manage</th>
                  <th>
                    <span className="vh">Remove</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.members_list.map((m) => {
                  const isOwner = m.user_id === owner;
                  const role = isOwner ? 'owner' : m.role;
                  const [r, w, mg] = RIGHTS[role] ?? [true, false, false];
                  const tick = (on: boolean) => (on ? <span className="ok" aria-label="yes">✓</span> : <span className="muted" aria-label="no">–</span>);
                  return (
                    <tr key={m.user_id}>
                      <td>
                        {m.user_id}
                        {m.user_id === me?.username && ' (you)'}
                        {m.via_team && <div className="hint">via team {m.via_team}</div>}
                      </td>
                      <td>
                        {isOwner || role === 'viewer' || data.can_manage === false ? (
                          <span className="lbl g">{ROLE_NAME[role] ?? role}</span>
                        ) : (
                          <select
                            className="in auto sm"
                            aria-label={`Project role of ${m.user_id}`}
                            value={m.role === 'admin' || m.role === 'manager' ? 'admin' : 'member'}
                            onChange={(e) => changeRole(m.user_id, e.target.value as 'member' | 'admin')}
                          >
                            <option value="admin">Project Manager</option>
                            <option value="member">Contributor</option>
                          </select>
                        )}
                      </td>
                      <td>{tick(r)}</td>
                      <td>{tick(w)}</td>
                      <td>{tick(mg)}</td>
                      <td>
                        {!isOwner && data.can_manage !== false && (
                          <button type="button" className="btn bl sm" onClick={() => setRemoving(m.user_id)}>
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <aside className="col-side" style={{ flex: '1 1 340px' }}>
        <section className="card">
          <div className="ch">
            <h2 data-h="3">Agent loading policy</h2>
            <a className="sm" href={settings}>
              Edit
            </a>
          </div>
          {data.loading ? (
            <dl className="kv">
              <dt>Load at session start</dt>
              <dd>{data.loading.session_start}</dd>
              <dt>Pinned</dt>
              <dd>{data.loading.always_include}</dd>
              <dt>Superseded</dt>
              <dd>{data.loading.superseded}</dd>
            </dl>
          ) : (
            <pre style={{ margin: 0 }}>{data.loading_policy}</pre>
          )}
        </section>
        <section className="card">
          <h2 data-h="3" style={{ marginBottom: 12 }}>Session focus · 30 d</h2>
          {!data.focus_available || !data.focus_history?.length ? (
            <p className="sm muted" style={{ margin: 0 }}>
              {data.focus_available ? 'No session focus declared in the last 30 days.' : 'Focus history is not available on this deployment.'}
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {data.focus_history.slice(0, 5).map((f) => (
                <div key={f.focus}>
                  <div className="sm">{f.focus}</div>
                  <div className="bar thin">
                    <span style={{ width: `${total ? Math.round((f.count / total) * 100) : 0}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
          <p className="hint" style={{ margin: '10px 0 0' }}>
            Topics only · no memory text
          </p>
        </section>
        <section className="card">
          <h2 data-h="3" style={{ marginBottom: 12 }}>Lifecycle</h2>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" className="btn bs sm" onClick={onEdit} disabled={data.archived}>
              Set quota
            </button>
            <button type="button" className="btn bs sm" onClick={onEdit} disabled={data.archived}>
              Edit policies
            </button>
            <a className="btn bs sm" href={settings}>
              Transfer owner
            </a>
            <button type="button" className="btn bd outline sm" onClick={() => onLifecycle(data.archived ? 'unarchive' : 'archive')}>
              {data.archived ? 'Restore' : 'Archive'}
            </button>
            {data.can_delete !== false && (
              <button type="button" className="btn bd outline sm" onClick={() => onLifecycle('delete')}>
                Delete project…
              </button>
            )}
          </div>
          <p className="sm muted" style={{ margin: '12px 0 0' }}>
            Archived projects can be restored from the Archived tab. Delete follows the procedure: reason, owner notice, second admin.
          </p>
        </section>
      </aside>

      {removing && (
        <ConfirmModal
          title="Remove member?"
          confirmLabel="Remove"
          danger
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            await api.removeMember(data.name, removing);
            toast(`${removing} removed from ${data.name}.`);
            reload();
          }}
        >
          <b>{removing}</b> loses read and write access to <b>{data.name}</b> project memories. Their existing memories stay. The change is audited.
        </ConfirmModal>
      )}
    </div>
  );
};

/** Double-click summary of a project, with the way to its settings page. */
const ProjectPeek: React.FC<{ row: ProjectRow; onClose: () => void }> = ({ row, onClose }) => {
  const pct = quotaPct(row);
  return (
    <Modal
      title={row.name}
      onClose={onClose}
      actions={
        <>
          <a className="btn bp" href={buildHash(`/project/${encodeURIComponent(row.name)}`)}>
            Settings
          </a>
          {row.my_role && (
            <a className="btn bs" href={buildHash('/memories', { project: row.name })}>
              Browse memories
            </a>
          )}
          <button type="button" className="btn bg" onClick={onClose}>
            Close
          </button>
        </>
      }
    >
      <p style={{ margin: '0 0 14px' }}>{row.description || <span className="muted">No description.</span>}</p>
      <dl className="kv wide">
        <dt>Owner</dt>
        <dd>{ownerOf(row)}</dd>
        <dt>Status</dt>
        <dd>{row.archived ? `Archived${row.archived_at ? ` ${fmtRelative(row.archived_at).toLowerCase()}` : ''}` : 'Active'}</dd>
        <dt>Members</dt>
        <dd>{fmtInt(row.members)}</dd>
        <dt>Memories</dt>
        <dd>
          {fmtInt(row.memories)}
          {pct !== null && ` · ${pct}% of quota`}
        </dd>
        <dt>Last write</dt>
        <dd>{row.last_write ? fmtRelative(row.last_write) : 'Never'}</dd>
        <dt>Campaigns</dt>
        <dd>{row.campaigns.length ? row.campaigns.map((c) => c.name).join(', ') : '—'}</dd>
        <dt>Your access</dt>
        <dd>{row.my_role ? 'Member · content' : 'Metadata only — you manage it, you do not read it'}</dd>
      </dl>
    </Modal>
  );
};

const TeamPeek: React.FC<{ team: TeamRow; onClose: () => void }> = ({ team, onClose }) => (
  <Modal
    title={team.name}
    onClose={onClose}
    actions={
      <>
        <a className="btn bp" href={buildHash(`/team/${encodeURIComponent(team.id)}`)}>
          Settings
        </a>
        <button type="button" className="btn bg" onClick={onClose}>
          Close
        </button>
      </>
    }
  >
    <p style={{ margin: '0 0 14px' }}>{team.description || <span className="muted">No description.</span>}</p>
    <dl className="kv wide">
      <dt>Leads</dt>
      <dd>{team.members.filter((m) => m.role === 'lead').map((m) => m.user_id).join(', ') || '—'}</dd>
      <dt>People</dt>
      <dd>{team.members.length}</dd>
      <dt>Projects</dt>
      <dd>{team.projects.length ? team.projects.join(', ') : '—'}</dd>
      <dt>Created</dt>
      <dd>
        {fmtRelative(team.created_at)} by {team.created_by}
      </dd>
    </dl>
  </Modal>
);

/* ------------------------------------------------------------------ */
/* Settings pages: one project or team, everything an admin can change */
/* ------------------------------------------------------------------ */

export const ProjectSettings: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const name = decodeURIComponent(route.path.replace(/^\/project\//, ''));
  const list = useApi(() => api.projects(false), []);
  const row = list.data?.items.find((p) => p.name === name);
  const [modal, setModal] = useState<null | 'edit' | 'member'>(null);
  const [lifecycle, setLifecycle] = useState<null | { action: 'archive' | 'unarchive' | 'delete'; project: ProjectRow }>(null);
  const [token, setToken] = useState(0);
  const back = buildHash('/projects', { project: name });
  return (
    <>
      <PageHeader
        title={`${name} · settings`}
        crumbs={[{ label: 'Projects & teams', href: back }, { label: name }]}
        description="Details, quota and policies, members and their project roles, linked teams, and the project's lifecycle. Every change is audited."
        actions={
          <>
            <a className="btn bs" href={back}>
              Back to list
            </a>
            {row?.my_role && (
              <a className="btn bs" href={buildHash('/memories', { project: name })}>
                Browse memories
              </a>
            )}
          </>
        }
      />
      <div className="body">
        {list.error && !list.data ? (
          <div className="card">
            <ErrorState error={list.error} onRetry={list.reload} />
          </div>
        ) : list.data && !row ? (
          <div className="card">
            <Empty title="Project not found">It may have been deleted or renamed.</Empty>
          </div>
        ) : (
          <div className="settings-cols">
            <ProjectPanel
              key={`${name}-${token}`}
              name={name}
              onEdit={() => setModal('edit')}
              onAddMember={() => setModal('member')}
              onLifecycle={(action, project) => setLifecycle({ action, project })}
            />
          </div>
        )}
      </div>
      {modal === 'edit' && row && (
        <ProjectForm
          existing={row}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Project updated.');
            list.reload();
            setToken((t) => t + 1);
          }}
        />
      )}
      {modal === 'member' && (
        <MemberForm
          project={name}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Member added.');
            setToken((t) => t + 1);
          }}
        />
      )}
      {lifecycle && (
        <LifecycleModal
          action={lifecycle.action}
          project={lifecycle.project}
          onClose={() => setLifecycle(null)}
          onDone={(message) => {
            toast(message);
            if (lifecycle.action === 'delete') navigate('/projects', undefined, { replace: true });
            else {
              list.reload();
              setToken((t) => t + 1);
            }
          }}
        />
      )}
    </>
  );
};

export const TeamSettings: React.FC<{ route: HashRoute }> = ({ route }) => {
  const id = decodeURIComponent(route.path.replace(/^\/team\//, ''));
  const teams = useApi(() => api.teams(), []);
  const projects = useApi(() => api.projects(false), []);
  const team = teams.data?.items.find((t) => t.id === id);
  const back = buildHash('/projects', { kind: 'teams', team: id });
  return (
    <>
      <PageHeader
        title={team ? `${team.name} · settings` : 'Team settings'}
        crumbs={[{ label: 'Projects & teams', href: buildHash('/projects', { kind: 'teams' }) }, { label: team?.name ?? 'Team' }]}
        description="People and leads, the projects the team works on, and its name and description. Every change is audited."
        actions={
          <a className="btn bs" href={back}>
            Back to list
          </a>
        }
      />
      <div className="body">
        {teams.error && !teams.data ? (
          <div className="card">
            <ErrorState error={teams.error} onRetry={teams.reload} />
          </div>
        ) : !teams.data ? (
          <div className="card">
            <SkLines lines={8} />
          </div>
        ) : !team ? (
          <div className="card">
            <Empty title="Team not found">It may have been deleted.</Empty>
          </div>
        ) : (
          <div className="settings-cols">
            <TeamPanel
              team={team}
              projects={projects.data?.items ?? []}
              onChanged={() => teams.reload()}
              onDeleted={() => navigate('/projects', { kind: 'teams' }, { replace: true })}
            />
          </div>
        )}
      </div>
    </>
  );
};

export default AdminProjects;
