import React, { useEffect, useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Dropdown, Empty, ErrorState, Modal, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { PeoplePicker } from '@/components/PeoplePicker';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CampaignRow, ProjectDetail, ProjectPolicies, ProjectRow } from '@/types';
import { avatarColor, errorMessage, fmtInt, fmtRelative, initials } from '@/utils/format';
import { ConfirmModal } from './common';
import { ProjectTeams, TeamForm, TeamPanel, TeamsTable } from './Teams';

const Projects: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { role } = useApp();
  const kindParam = route.params.get('kind');
  const kind = kindParam === 'campaigns' ? 'campaigns' : kindParam === 'teams' ? 'teams' : 'projects';
  const selectedTeam = route.params.get('team');
  const selectedName = route.params.get('project');
  const selectedCampaign = route.params.get('campaign');
  const [mine, setMine] = useState(false);
  const [filter, setFilter] = useState('');
  // #671: archived projects are hidden by default; sort by recent activity, name, creation or size.
  const status = (route.params.get('status') as 'active' | 'archived' | 'all' | null) ?? 'active';
  const sort = (route.params.get('sort') as ProjectSort | null) ?? 'activity';
  const [modal, setModal] = useState<null | 'project' | 'campaign' | 'team' | 'edit' | 'member' | 'enroll'>(null);
  const [lifecycle, setLifecycle] = useState<null | { action: 'archive' | 'unarchive' | 'delete'; project: ProjectRow }>(null);

  const projects = useApi(() => api.projects(mine), [mine]);
  const campaigns = useApi(() => api.campaigns(), []);
  const teams = useApi(() => api.teams(), []);
  const activeTeam = (teams.data?.items ?? []).find((t) => t.id === selectedTeam) ?? teams.data?.items?.[0] ?? null;
  const allRows = projects.data?.items ?? [];
  const archivedCount = allRows.filter((p) => p.archived).length;
  const rows = sortProjects(
    allRows
      .filter((p) => (status === 'all' ? true : status === 'archived' ? p.archived : !p.archived))
      .filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()) || (p.description ?? '').toLowerCase().includes(filter.toLowerCase())),
    sort,
  );
  const canDelete = projects.data?.can_delete ?? role !== 'user';
  const camps = (campaigns.data?.items ?? []).filter((c) => c.name.toLowerCase().includes(filter.toLowerCase()));
  const activeProject = selectedName ?? rows[0]?.name ?? null;
  // #676: with central provisioning only platform admins create projects.
  const canCreate = projects.data?.can_create ?? role !== 'user';
  const central = (projects.data?.provisioning ?? 'central') === 'central';
  const manages = (p: ProjectRow) => role !== 'user' || p.my_role === 'admin';
  const activeCampaign = camps.find((c) => c.id === selectedCampaign) ?? camps[0] ?? null;

  const setParam = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(route.params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    navigate('/projects', next, { replace: true });
  };

  const reloadAll = () => {
    projects.reload();
    campaigns.reload();
    teams.reload();
  };

  return (
    <>
      <PageHeader
        title="Projects & teams"
        description="Projects share memory between every agent working in that context. Teams are groups of people: a project has members from several teams, and one team works on several projects. Campaigns span projects for a bounded initiative."
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
            {canCreate && (
              <button type="button" className="btn bp" onClick={() => setModal('project')}>
                Create project
              </button>
            )}
          </>
        }
        tabs={
          <Tabs
            label="Kind"
            value={kind}
            onChange={(k) => setParam({ kind: k === 'projects' ? undefined : k, project: undefined, campaign: undefined, team: undefined })}
            tabs={[
              { value: 'projects', label: 'Projects', count: projects.data?.total ?? null },
              { value: 'teams', label: 'Teams', count: teams.data?.counts?.teams ?? null },
              { value: 'campaigns', label: 'Campaigns', count: campaigns.data?.items?.length ?? null },
            ]}
          />
        }
      />
      <div className="body">
        <div className="row-wrap">
          <section className="card" style={{ flex: '999 1 560px', padding: 0, minWidth: 0 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: '16px 20px', alignItems: 'center' }}>
              <label htmlFor="pf" className="vh">
                Filter {kind}
              </label>
              <input id="pf" className="in" placeholder="Filter by name" style={{ flex: '1 1 160px' }} value={filter} onChange={(e) => setFilter(e.target.value)} />
              {kind === 'projects' && (
                <>
                  <div className="seg" role="group" aria-label="Which projects">
                    <button type="button" className={mine ? 'on' : ''} aria-pressed={mine} onClick={() => setMine(true)}>
                      Mine
                    </button>
                    <button type="button" className={!mine ? 'on' : ''} aria-pressed={!mine} onClick={() => setMine(false)}>
                      All in tenant
                    </button>
                  </div>
                  <div className="seg" role="group" aria-label="Project status">
                    {(['active', 'archived', 'all'] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        className={status === s ? 'on' : ''}
                        aria-pressed={status === s}
                        onClick={() => setParam({ status: s === 'active' ? undefined : s, project: undefined })}
                      >
                        {s === 'active' ? 'Active' : s === 'archived' ? `Archived${archivedCount ? ` (${archivedCount})` : ''}` : 'All'}
                      </button>
                    ))}
                  </div>
                  <label htmlFor="psort" className="vh">
                    Sort projects
                  </label>
                  <select id="psort" className="in auto" value={sort} onChange={(e) => setParam({ sort: e.target.value === 'activity' ? undefined : e.target.value })}>
                    <option value="activity">Recent activity</option>
                    <option value="name">Name</option>
                    <option value="created">Newest</option>
                    <option value="memories">Most memories</option>
                  </select>
                </>
              )}
            </div>
            {kind === 'teams' ? (
              <TeamsTable
                teams={teams.data?.items ?? []}
                loading={teams.loading && !teams.data}
                active={activeTeam?.id ?? null}
                onSelect={(id) => setParam({ team: id })}
                onCreate={() => setModal('team')}
                filter={filter}
              />
            ) : kind === 'projects' ? (
              projects.error && !projects.data ? (
                <ErrorState error={projects.error} onRetry={projects.reload} />
              ) : projects.loading && !projects.data ? (
                <SkTable rows={6} cols={6} />
              ) : rows.length === 0 ? (
                <Empty
                  title={filter ? 'No projects match' : status === 'archived' ? 'No archived projects' : mine ? 'You are not in any project yet' : 'No projects yet'}
                  action={
                    !filter &&
                    status !== 'archived' &&
                    canCreate && (
                      <button type="button" className="btn bp" onClick={() => setModal('project')}>
                        Create project
                      </button>
                    )
                  }
                >
                  {filter
                    ? 'Try another name.'
                    : status === 'archived'
                      ? 'Archived projects are read-only: their members still read the memories, nobody writes to them.'
                      : central
                      ? canCreate
                        ? 'Create a project for each shared context and add its members; agents cannot create projects on this deployment.'
                        : 'Projects are created by platform admins, who add their members. Ask an admin to add you to your team’s project.'
                      : 'Agents create open projects on their first project-scope write, or you can create one here.'}
                </Empty>
              ) : (
                <div className="scroll">
                  <table className="tbl" style={{ minWidth: 760 }}>
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Enrollment</th>
                        <th>Members</th>
                        <th>Memories</th>
                        <th>Campaigns</th>
                        <th>Last write</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((p) => (
                        <tr key={p.name} className={`clickable ${p.name === activeProject ? 'is-sel' : ''}`} onClick={() => setParam({ project: p.name })}>
                          <td>
                            <a
                              href={buildHash('/projects', { project: p.name })}
                              style={{ fontWeight: 600, textDecoration: 'none' }}
                              onClick={(e) => {
                                e.preventDefault();
                                setParam({ project: p.name });
                              }}
                            >
                              {p.name}
                            </a>
                            {p.archived && (
                              <span className="lbl g" style={{ marginLeft: 8 }} title={p.archived_at ? `Archived ${fmtRelative(p.archived_at).toLowerCase()}${p.archived_by ? ` by ${p.archived_by}` : ''}` : undefined}>
                                Archived
                              </span>
                            )}
                            <div className="sm muted">{p.description || '—'}</div>
                          </td>
                          <td>{central ? <span className="lbl blue">Members only</span> : p.invite_only ? <span className="lbl blue">Invite-only</span> : <span className="lbl g">Open</span>}</td>
                          <td>{fmtInt(p.members)}</td>
                          <td>
                            <a href={buildHash('/memories', { project: p.name })} onClick={(e) => e.stopPropagation()} className="link-plain" style={{ color: 'inherit' }}>
                              {fmtInt(p.memories)}
                            </a>
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                              {p.campaigns.map((c) => (
                                <span className="lbl s-campaign" key={c.id}>
                                  {c.name}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="sm muted">{p.last_write ? fmtRelative(p.last_write) : 'Never'}</td>
                          <td onClick={(e) => e.stopPropagation()}>
                            <Dropdown
                              align="right"
                              toggle={(tp) => (
                                <button type="button" className="btn bl" aria-label="Project actions" style={{ padding: '4px 8px' }} {...tp}>
                                  ⋮
                                </button>
                              )}
                            >
                              {(close) => (
                                <>
                                  {manages(p) && (
                                    <>
                                      <button type="button" onClick={() => { close(); setParam({ project: p.name }); setModal('edit'); }}>
                                        Edit
                                      </button>
                                      {!p.archived && (
                                        <button type="button" onClick={() => { close(); setParam({ project: p.name }); setModal('member'); }}>
                                          Add member
                                        </button>
                                      )}
                                    </>
                                  )}
                                  <a href={buildHash('/memories', { project: p.name })}>Browse memories</a>
                                  {manages(p) && (
                                    <button type="button" onClick={() => { close(); setLifecycle({ action: p.archived ? 'unarchive' : 'archive', project: p }); }}>
                                      {p.archived ? 'Unarchive' : 'Archive'}
                                    </button>
                                  )}
                                  {canDelete && (
                                    <button type="button" className="danger" onClick={() => { close(); setLifecycle({ action: 'delete', project: p }); }}>
                                      Delete…
                                    </button>
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
              )
            ) : campaigns.error && !campaigns.data ? (
              <ErrorState error={campaigns.error} onRetry={campaigns.reload} />
            ) : campaigns.loading && !campaigns.data ? (
              <SkTable rows={3} cols={5} />
            ) : camps.length === 0 ? (
              <Empty
                title="No campaigns yet"
                action={
                  <button type="button" className="btn bp" onClick={() => setModal('campaign')}>
                    Create campaign
                  </button>
                }
              >
                Campaigns group projects under one governance policy and memory TTL for a bounded initiative.
              </Empty>
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
                      <tr key={c.id} className={`clickable ${c.id === activeCampaign?.id ? 'is-sel' : ''}`} onClick={() => setParam({ campaign: c.id })}>
                        <td>
                          <span style={{ fontWeight: 600, color: '#0066cc' }}>{c.name}</span>
                          <div className="sm muted">{c.description || '—'}</div>
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

          <aside className="col-side" style={{ flex: '1 1 380px' }}>
            {kind === 'teams' ? (
              activeTeam ? (
                <TeamPanel
                  key={activeTeam.id}
                  team={activeTeam}
                  projects={projects.data?.items ?? []}
                  onChanged={reloadAll}
                  onDeleted={() => {
                    setParam({ team: undefined });
                    reloadAll();
                  }}
                />
              ) : (
                <div className="card">
                  <Empty compact title="No team selected">
                    Select a team to see its people and the projects it works on.
                  </Empty>
                </div>
              )
            ) : kind === 'projects' ? (
              activeProject ? (
                <ProjectPanel
                  name={activeProject}
                  onEdit={() => setModal('edit')}
                  onAddMember={() => setModal('member')}
                  onLifecycle={(action, project) => setLifecycle({ action, project })}
                  key={activeProject}
                />
              ) : (
                <div className="card">
                  <Empty compact title="No project selected">
                    Select a project to see its members, focus history and loading policy.
                  </Empty>
                </div>
              )
            ) : activeCampaign ? (
              <CampaignPanel campaign={activeCampaign} projects={projects.data?.items ?? []} onChanged={reloadAll} onEnroll={() => setModal('enroll')} />
            ) : (
              <div className="card">
                <Empty compact title="No campaign selected">
                  Select a campaign to see its enrolled projects.
                </Empty>
              </div>
            )}
          </aside>
        </div>
      </div>

      {modal === 'project' && (
        <ProjectForm
          central={central}
          onClose={() => setModal(null)}
          onSaved={(name) => {
            toast(`Project ${name} created.`);
            reloadAll();
            setParam({ kind: undefined, project: name });
          }}
        />
      )}
      {modal === 'edit' && activeProject && (
        <ProjectForm
          central={central}
          existing={projects.data?.items.find((p) => p.name === activeProject)}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Project updated.');
            reloadAll();
            setParam({ project: activeProject, _r: String(Date.now()) });
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
            if (lifecycle.action === 'delete') setParam({ project: undefined });
            else setParam({ project: lifecycle.project.name, status: lifecycle.action === 'archive' && status === 'active' ? 'all' : status === 'active' ? undefined : status, _r: String(Date.now()) });
          }}
        />
      )}
      {modal === 'member' && activeProject && (
        <MemberForm
          project={activeProject}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Member added.');
            reloadAll();
            setParam({ project: activeProject, _r: String(Date.now()) });
          }}
        />
      )}
      {modal === 'team' && (
        <TeamForm
          projects={projects.data?.items ?? []}
          onClose={() => setModal(null)}
          onSaved={(id) => {
            setModal(null);
            reloadAll();
            setParam({ kind: 'teams', team: id });
          }}
        />
      )}
      {modal === 'campaign' && (
        <CampaignForm
          projects={projects.data?.items ?? []}
          onClose={() => setModal(null)}
          onSaved={(id) => {
            toast('Campaign created.');
            reloadAll();
            setParam({ kind: 'campaigns', campaign: id });
          }}
        />
      )}
      {modal === 'enroll' && activeCampaign && (
        <EnrollForm
          campaign={activeCampaign}
          projects={(projects.data?.items ?? []).filter((p) => !activeCampaign.projects.includes(p.name))}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Project enrolled.');
            reloadAll();
          }}
        />
      )}
    </>
  );
};

const ProjectPanel: React.FC<{
  name: string;
  onEdit: () => void;
  onAddMember: () => void;
  onLifecycle: (action: 'archive' | 'unarchive' | 'delete', project: ProjectRow) => void;
}> = ({ name, onEdit, onAddMember, onLifecycle }) => {
  const toast = useToast();
  const { route } = useRouteToken();
  const { data, error, loading, reload } = useApi<ProjectDetail>(() => api.project(name), [name, route]);
  const [showAll, setShowAll] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const { me } = useApp();
  const changeRole = async (userId: string, current: string, next: 'member' | 'admin') => {
    if (current === 'admin' && next === 'member' && !window.confirm(`Make ${userId} a project member? They will lose permission to manage ${name}'s members and settings.`)) return;
    try {
      await api.setMemberRole(name, userId, next);
      toast(next === 'admin' ? `${userId} is now an admin of ${name}.` : `${userId} is now a member of ${name}.`);
      reload();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };
  if (error && !data) return <div className="card"><ErrorState error={error} onRetry={reload} compact /></div>;
  if (loading && !data) return <div className="card"><SkLines lines={10} /></div>;
  if (!data) return null;
  const members = showAll ? data.members_list : data.members_list.slice(0, 3);
  const maxFocus = Math.max(1, ...(data.focus_history ?? []).map((f) => f.count));
  return (
    <>
      <div className="card">
        <div className="ch">
          <div>
            <span className="lbl s-project">Project</span>
            <h3 style={{ fontSize: 20, marginTop: 8 }}>{data.name}</h3>
          </div>
          {(data.can_manage !== false || data.can_delete) && (
            <div style={{ display: 'flex', gap: 8 }}>
              {data.can_manage !== false && (
                <button type="button" className="btn bg" onClick={onEdit}>
                  Edit
                </button>
              )}
              <Dropdown
                align="right"
                toggle={(tp) => (
                  <button type="button" className="btn bg" aria-label={`More actions for ${data.name}`} style={{ padding: '6px 10px' }} {...tp}>
                    ⋮
                  </button>
                )}
              >
                {(close) => (
                  <>
                    {data.can_manage !== false && (
                      <button type="button" onClick={() => { close(); onLifecycle(data.archived ? 'unarchive' : 'archive', data); }}>
                        {data.archived ? 'Unarchive' : 'Archive'}
                      </button>
                    )}
                    {data.can_delete && (
                      <button type="button" className="danger" onClick={() => { close(); onLifecycle('delete', data); }}>
                        Delete…
                      </button>
                    )}
                  </>
                )}
              </Dropdown>
            </div>
          )}
        </div>
        {data.can_manage !== false && !data.members_list.some((m) => m.role === 'admin') && (
          <div className="alert warn-a" role="status" style={{ marginBottom: 14 }}>
            <div>
              <b>No project admin.</b> Only platform admins can manage its members. Make a member an admin below.
            </div>
          </div>
        )}
        {data.archived && (
          <div className="alert warn-a" role="status" style={{ marginBottom: 14 }}>
            <div style={{ flex: 1 }}>
              <b>Archived{data.archived_at ? ` ${fmtRelative(data.archived_at).toLowerCase()}` : ''}{data.archived_by ? ` by ${data.archived_by}` : ''}.</b> Read-only: members still read its memories; agents and people cannot write, edit or join. Authors can still delete their own memories.
            </div>
            {data.can_manage !== false && (
              <button type="button" className="btn bs sm" onClick={() => onLifecycle('unarchive', data)}>
                Unarchive
              </button>
            )}
          </div>
        )}
        <p className="sm muted" style={{ margin: '0 0 14px' }}>
          {data.description ? `${data.description}. ` : ''}
          {data.provisioning !== 'self_service'
            ? 'Members are added by a project admin or a platform admin; writing to the project does not join it.'
            : data.invite_only
              ? 'Invite-only — members are added by a project admin.'
              : 'Open enrollment — agents join on first project-scope write.'}
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
            <div className="sm muted">Agents today</div>
            <div className="num-lg">{fmtInt(data.agents_today)}</div>
          </div>
        </div>
        <PolicySummary policies={data.policies} memories={data.memories} />
        <div className="ch" style={{ marginBottom: 10 }}>
          <b className="sm">Members</b>
          {data.can_manage !== false && !data.archived && (
            <button type="button" className="btn bl sm" onClick={onAddMember}>
              + Add member
            </button>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14 }}>
          {data.members_list.length === 0 && <span className="sm muted">No members yet.</span>}
          {members.map((m) => (
            <div key={m.user_id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="mav" style={{ background: avatarColor(m.user_id) }}>
                {initials(m.user_id)}
              </span>
              <span style={{ flex: 1, minWidth: 0 }}>
                {m.user_id}
                {m.via_team && <span className="sm muted"> · via team {m.via_team}</span>}
                <span className="hint" style={{ display: 'block' }}>
                  {m.joined_by === m.user_id ? 'Auto-enrolled' : m.joined_by && !m.via_team ? `Added by ${m.joined_by}` : 'Joined'}
                  {m.joined_at ? ` ${fmtRelative(m.joined_at).toLowerCase()}` : ''}
                </span>
              </span>
              {data.can_manage !== false ? (
                <select
                  className="in auto sm"
                  aria-label={`Role of ${m.user_id}`}
                  value={m.role}
                  onChange={(e) => changeRole(m.user_id, m.role, e.target.value as 'member' | 'admin')}
                  style={{ width: 'auto', padding: '2px 8px' }}
                >
                  <option value="member">member</option>
                  <option value="admin">admin</option>
                </select>
              ) : (
                <span className={`lbl ${m.role === 'admin' ? 'blue' : 'g'}`}>{m.role}</span>
              )}
              {(data.can_manage !== false || m.user_id === me?.username) && (
                <button
                  type="button"
                  className="btn bl sm"
                  aria-label={m.user_id === me?.username ? `Leave ${name}` : `Remove ${m.user_id}`}
                  style={{ padding: '2px 6px' }}
                  onClick={() => setRemoving(m.user_id)}
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          {data.members_list.length > 3 && (
            <button type="button" className="link-btn sm" style={{ alignSelf: 'flex-start' }} onClick={() => setShowAll((s) => !s)}>
              {showAll ? 'Show fewer' : `Show ${data.members_list.length - 3} more`}
            </button>
          )}
        </div>
        <ProjectTeams project={data.name} teams={data.teams ?? []} onChanged={reload} readOnly={data.archived} />
      </div>

      <div className="card">
        <div className="ch">
          <h3>Session focus · last 30 days</h3>
          <span className="sm muted">get_focus_history</span>
        </div>
        {!data.focus_available ? (
          <p className="sm muted" style={{ margin: 0 }}>
            Focus history is kept in Valkey. Set <span className="mono">MEMORYHUB_VALKEY_URL</span> on the dashboard to show it here.
          </p>
        ) : !data.focus_history?.length ? (
          <p className="sm muted" style={{ margin: 0 }}>
            No agent has declared a session focus in this project in the last 30 days.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {data.focus_history.map((f) => (
              <div className="hb" key={f.focus}>
                <span className="t" title={f.focus}>
                  {f.focus}
                </span>
                <span className="b" style={{ width: `${Math.max(3, (f.count / maxFocus) * 62)}%` }} />
                <span className="muted">{f.count}</span>
              </div>
            ))}
          </div>
        )}
        <p className="sm muted" style={{ margin: '12px 0 0' }}>
          Advisory only — shows where agents spend attention and where coverage is thin.
        </p>
      </div>

      <div className="card">
        <div className="ch">
          <h3>Agent loading policy</h3>
          <span className="mono muted">.memoryhub.yaml</span>
        </div>
        <pre>{data.loading_policy}</pre>
        <p className="sm muted" style={{ margin: '10px 0 0' }}>
          Tenant defaults from Settings. A <span className="mono">.memoryhub.yaml</span> in the repository overrides them.
        </p>
      </div>

      {removing && (
        <ConfirmModal
          title="Remove member?"
          confirmLabel="Remove"
          danger
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            await api.removeMember(name, removing);
            toast(`${removing} removed from ${name}.`);
            reload();
          }}
        >
          <b>{removing}</b> loses read and write access to <b>{name}</b> project memories. Their existing memories stay. The change is audited.
        </ConfirmModal>
      )}
    </>
  );
};

// Re-fetch the side panel when the route token changes after an edit.
const useRouteToken = () => {
  const [route, setRoute] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setRoute(window.location.hash);
    window.addEventListener('hashchange', on);
    window.addEventListener('memoryhub:route', on);
    return () => {
      window.removeEventListener('hashchange', on);
      window.removeEventListener('memoryhub:route', on);
    };
  }, []);
  return { route: useMemo(() => new URLSearchParams(route.split('?')[1] ?? '').get('_r'), [route]) };
};

const CampaignPanel: React.FC<{ campaign: CampaignRow; projects: ProjectRow[]; onChanged: () => void; onEnroll: () => void }> = ({ campaign, onChanged, onEnroll }) => {
  const toast = useToast();
  const setStatus = async (status: string) => {
    try {
      await api.updateCampaign(campaign.id, { status });
      toast(`Campaign marked ${status}.`);
      onChanged();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };
  return (
    <div className="card">
      <div className="ch">
        <div>
          <span className="lbl s-campaign">Campaign</span>
          <h3 style={{ fontSize: 20, marginTop: 8 }}>{campaign.name}</h3>
        </div>
        <Dropdown
          align="right"
          toggle={(p) => (
            <button type="button" className="btn bg" {...p}>
              Status: {campaign.status}
            </button>
          )}
        >
          {(close) =>
            ['active', 'completed', 'archived'].map((s) => (
              <button key={s} type="button" onClick={() => { close(); void setStatus(s); }}>
                {s}
              </button>
            ))
          }
        </Dropdown>
      </div>
      <p className="sm muted" style={{ margin: '0 0 14px' }}>
        {campaign.description || 'No description.'} {campaign.default_ttl_days ? `Memories expire after ${campaign.default_ttl_days} days by default.` : ''}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, marginBottom: 18 }}>
        <div>
          <div className="sm muted">Memories</div>
          <div className="num-lg">{fmtInt(campaign.memories)}</div>
        </div>
        <div>
          <div className="sm muted">Projects</div>
          <div className="num-lg">{campaign.projects.length}</div>
        </div>
      </div>
      <div className="ch" style={{ marginBottom: 10 }}>
        <b className="sm">Enrolled projects</b>
        <button type="button" className="btn bl sm" onClick={onEnroll}>
          + Enroll project
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 14 }}>
        {campaign.projects.length === 0 && <span className="sm muted">No projects enrolled yet.</span>}
        {campaign.projects.map((p) => (
          <a key={p} href={buildHash('/projects', { project: p })}>
            {p}
          </a>
        ))}
      </div>
    </div>
  );
};

const ProjectForm: React.FC<{ existing?: ProjectRow; central?: boolean; onClose: () => void; onSaved: (name: string) => void }> = ({ existing, central = true, onClose, onSaved }) => {
  const [name, setName] = useState(existing?.name ?? '');
  const [description, setDescription] = useState(existing?.description ?? '');
  const [inviteOnly, setInviteOnly] = useState(existing?.invite_only ?? central);
  const [ttl, setTtl] = useState(existing?.policies?.ttl_days?.toString() ?? '');
  const [quota, setQuota] = useState(existing?.policies?.max_memories?.toString() ?? '');
  const [weight, setWeight] = useState(existing?.policies?.default_weight?.toString() ?? '');
  const [admins, setAdmins] = useState<string[]>([]);
  const [members, setMembers] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const adminIds = admins;
  const memberIds = members.filter((u) => !adminIds.includes(u));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      if (existing)
        await api.updateProject(existing.name, {
          description: description || null,
          invite_only: inviteOnly,
          policies: { ttl_days: ttl ? Number(ttl) : null, max_memories: quota ? Number(quota) : null, default_weight: weight ? Number(weight) : null },
        });
      else
        await api.createProject({
          name: name.trim(),
          description: description.trim() || undefined,
          invite_only: inviteOnly,
          members: [...adminIds.map((u) => ({ user_id: u, role: 'admin' as const })), ...memberIds.map((u) => ({ user_id: u, role: 'member' as const }))],
        });
      onSaved(existing?.name ?? name.trim());
      onClose();
    } catch (e2) {
      setErr(errorMessage(e2));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={existing ? `Edit ${existing.name}` : 'Create project'} onClose={onClose}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {!existing && (
          <div className="f">
            <label htmlFor="pn">Name</label>
            <input id="pn" className="in" required pattern="[A-Za-z0-9][A-Za-z0-9._\-]*" value={name} onChange={(e) => setName(e.target.value)} placeholder="memoryhub-ui" />
            <span className="hint">Letters, numbers, dots, dashes and underscores. Agents use this as the project ID in .memoryhub.yaml.</span>
          </div>
        )}
        <div className="f">
          <label htmlFor="pd">Description</label>
          <input id="pd" className="in" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        {!existing && (
          <>
            <div className="f">
              <label htmlFor="pa">Project admins</label>
              <PeoplePicker id="pa" value={admins} onChange={setAdmins} kinds={['person']} placeholder="Choose who manages members" />
              <span className="hint">They manage the project's members. Leave empty to be its admin yourself.</span>
            </div>
            <div className="f">
              <label htmlFor="pm">Members</label>
              <PeoplePicker id="pm" value={members} onChange={setMembers} exclude={adminIds} excludeNote="already an admin" placeholder="Choose people and their agents" />
              <span className="hint">{central ? 'Only members can read and write this project’s memories. Add the agents people use, too.' : 'People and the agents they use.'}</span>
            </div>
          </>
        )}
        {existing && (
          <fieldset className="f" style={{ border: 0, padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <legend style={{ fontWeight: 600, fontSize: 14, marginBottom: 6 }}>Memory policies</legend>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
              <div className="f">
                <label htmlFor="pttl">Keep relevant for (days)</label>
                <input id="pttl" className="in" type="number" min={1} max={3650} step={1} inputMode="numeric" value={ttl} onChange={(e) => setTtl(e.target.value)} placeholder="No limit" />
              </div>
              <div className="f">
                <label htmlFor="pquota">Memory limit</label>
                <input id="pquota" className="in" type="number" min={1} step={1} inputMode="numeric" value={quota} onChange={(e) => setQuota(e.target.value)} placeholder="No limit" />
              </div>
              <div className="f">
                <label htmlFor="pweight">Default weight</label>
                <input id="pweight" className="in" type="number" min={0} max={1} step={0.05} inputMode="decimal" value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="0.7" />
              </div>
            </div>
            <ul className="hint" style={{ margin: 0, paddingLeft: 18, listStyle: 'disc' }}>
              <li>
                <b>Keep relevant</b>: new memories are marked no longer relevant after that many days (they are not deleted). Existing memories are not changed.
              </li>
              <li>
                <b>Memory limit</b>: new memories are refused once the project holds that many current memories. New versions and branches don’t count.
              </li>
              <li>
                <b>Default weight</b>: used only when the agent or person writing doesn’t set a weight. Existing memories keep theirs.
              </li>
            </ul>
            {quota && existing.memories > Number(quota) && (
              <div className="alert warn-a" role="status">
                {existing.name} already holds {fmtInt(existing.memories)} memories. Nothing is removed, but new memories are refused until fewer than {fmtInt(Number(quota))} remain.
              </div>
            )}
          </fieldset>
        )}
        {central ? (
          <p className="hint" style={{ margin: 0 }}>
            Central provisioning: members are always added explicitly, by a project admin or a platform admin. Writing to the project never joins it.
          </p>
        ) : (
          <label className="swrow">
            <span>
              <b>Invite-only</b>
              <div className="hint">
                Agents must be added by a project admin before they can read or write.
                {existing && !existing.invite_only && inviteOnly ? ' Current members keep their access.' : ''}
              </div>
            </span>
            <input type="checkbox" checked={inviteOnly} onChange={(e) => setInviteOnly(e.target.checked)} />
          </label>
        )}
        {err && <div className="alert err-a">{err}</div>}
        <div className="modal-actions">
          <button type="submit" className="btn bp" disabled={busy}>
            {existing ? 'Save' : adminIds.length + memberIds.length ? `Create with ${adminIds.length + memberIds.length} ${adminIds.length + memberIds.length === 1 ? 'person' : 'people'}` : 'Create project'}
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
};

const MemberForm: React.FC<{ project: string; onClose: () => void; onSaved: () => void }> = ({ project, onClose, onSaved }) => {
  const [people, setPeople] = useState<string[]>([]);
  const [role, setRole] = useState<'member' | 'admin'>('member');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { data } = useApi(() => api.project(project), [project]);
  const current = (data?.members_list ?? []).map((m) => m.user_id);
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

const CampaignForm: React.FC<{ projects: ProjectRow[]; onClose: () => void; onSaved: (id: string) => void }> = ({ projects, onClose, onSaved }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [ttl, setTtl] = useState('');
  const [chosen, setChosen] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Modal
      title="Create campaign"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={!name.trim()}
            onClick={async () => {
              try {
                const res = await api.createCampaign({ name: name.trim(), description: description.trim() || undefined, default_ttl_days: ttl ? Number(ttl) : undefined, projects: chosen });
                onSaved(res.id);
                onClose();
              } catch (e) {
                setErr(errorMessage(e));
              }
            }}
          >
            Create campaign
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="cn">Name</label>
        <input id="cn" className="in" value={name} onChange={(e) => setName(e.target.value)} placeholder="modernize-26" />
      </div>
      <div className="f">
        <label htmlFor="cd">Description</label>
        <input id="cd" className="in" value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div className="f">
        <label htmlFor="ct">Default memory TTL (days)</label>
        <input id="ct" className="in" type="number" min={1} value={ttl} onChange={(e) => setTtl(e.target.value)} placeholder="No expiry" />
      </div>
      <div className="f">
        <label>Enroll projects</label>
        <div className="fx" style={{ maxHeight: 180, overflow: 'auto' }}>
          {projects.length === 0 && <span className="sm muted">No projects yet.</span>}
          {projects.map((p) => (
            <label key={p.name}>
              <span>
                <input type="checkbox" checked={chosen.includes(p.name)} onChange={() => setChosen(chosen.includes(p.name) ? chosen.filter((x) => x !== p.name) : [...chosen, p.name])} /> {p.name}
              </span>
            </label>
          ))}
        </div>
      </div>
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

const EnrollForm: React.FC<{ campaign: CampaignRow; projects: ProjectRow[]; onClose: () => void; onSaved: () => void }> = ({ campaign, projects, onClose, onSaved }) => {
  const [project, setProject] = useState(projects[0]?.name ?? '');
  const [err, setErr] = useState<string | null>(null);
  return (
    <Modal
      title={`Enroll a project in ${campaign.name}`}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={!project}
            onClick={async () => {
              try {
                await api.enrollProject(campaign.id, project);
                onSaved();
                onClose();
              } catch (e) {
                setErr(errorMessage(e));
              }
            }}
          >
            Enroll
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      {projects.length === 0 ? (
        <p className="sm muted">Every project is already enrolled.</p>
      ) : (
        <div className="f">
          <label htmlFor="ep">Project</label>
          <select id="ep" className="in" value={project} onChange={(e) => setProject(e.target.value)}>
            {projects.map((p) => (
              <option key={p.name}>{p.name}</option>
            ))}
          </select>
        </div>
      )}
      {err && <div className="alert err-a">{err}</div>}
    </Modal>
  );
};

type ProjectSort = 'activity' | 'name' | 'created' | 'memories';

const sortProjects = (rows: ProjectRow[], sort: ProjectSort): ProjectRow[] => {
  const by: Record<ProjectSort, (a: ProjectRow, b: ProjectRow) => number> = {
    activity: (a, b) => (b.last_write ?? b.created_at).localeCompare(a.last_write ?? a.created_at),
    name: (a, b) => a.name.localeCompare(b.name),
    created: (a, b) => b.created_at.localeCompare(a.created_at),
    memories: (a, b) => b.memories - a.memories || a.name.localeCompare(b.name),
  };
  return [...rows].sort(by[sort]);
};

const PolicySummary: React.FC<{ policies?: ProjectPolicies; memories: number }> = ({ policies, memories }) => {
  const items: string[] = [];
  if (policies?.ttl_days) items.push(`New memories stay relevant ${policies.ttl_days} ${policies.ttl_days === 1 ? 'day' : 'days'}`);
  if (policies?.max_memories) items.push(`Limit ${fmtInt(policies.max_memories)} memories (${fmtInt(memories)} used)`);
  if (policies?.default_weight !== undefined) items.push(`Default weight ${policies.default_weight}`);
  if (!items.length) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <b className="sm">Memory policies</b>
      <ul className="sm" style={{ margin: '6px 0 0', paddingLeft: 18, listStyle: 'disc' }}>
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </div>
  );
};

const LifecycleModal: React.FC<{
  action: 'archive' | 'unarchive' | 'delete';
  project: ProjectRow;
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ action, project, onClose, onDone }) => {
  const [typed, setTyped] = useState('');
  const confirmed = typed.trim() === project.name;
  if (action !== 'delete')
    return (
      <ConfirmModal
        title={action === 'archive' ? `Archive ${project.name}?` : `Unarchive ${project.name}?`}
        confirmLabel={action === 'archive' ? 'Archive' : 'Unarchive'}
        onClose={onClose}
        onConfirm={async () => {
          if (action === 'archive') await api.archiveProject(project.name);
          else await api.unarchiveProject(project.name);
          onDone(action === 'archive' ? `${project.name} archived — read-only.` : `${project.name} is writable again.`);
        }}
      >
        {action === 'archive' ? (
          <>
            <b>{project.name}</b> becomes read-only. Its {fmtInt(project.members)} {project.members === 1 ? 'member keeps' : 'members keep'} reading its {fmtInt(project.memories)} memories; agents and people can no longer write, edit or join. You can unarchive it later.
          </>
        ) : (
          <>
            Members of <b>{project.name}</b> can write to it again.
          </>
        )}
      </ConfirmModal>
    );
  return (
    <ConfirmModal
      title={`Delete ${project.name}?`}
      confirmLabel="Delete project and memories"
      danger
      confirmDisabled={!confirmed}
      onClose={onClose}
      onConfirm={async () => {
        const res = await api.deleteProject(project.name, typed.trim());
        onDone(`${project.name} deleted with ${fmtInt(res.memories_deleted)} ${res.memories_deleted === 1 ? 'memory' : 'memories'}.`);
      }}
    >
      <p style={{ margin: '0 0 8px' }}>Deleting removes more than the project:</p>
      <ul style={{ margin: '0 0 12px', paddingLeft: 20, listStyle: 'disc' }}>
        <li>
          all <b>{fmtInt(project.memories)}</b> project {project.memories === 1 ? 'memory' : 'memories'}, with their versions and branches, for every member and agent;
        </li>
        <li>
          access for its <b>{fmtInt(project.members)}</b> {project.members === 1 ? 'member' : 'members'} and any linked teams;
        </li>
        <li>the name: a new project can never be called {project.name}.</li>
      </ul>
      <p style={{ margin: '0 0 12px' }}>
        The dashboard cannot undo it.{' '}
        {project.archived ? 'The project is archived already: members can still read it until you delete it.' : <b>To keep the memories readable, archive the project instead.</b>}
      </p>
      <div className="f">
        <label htmlFor="pdel">
          Type <span className="mono">{project.name}</span> to confirm
        </label>
        <input id="pdel" className="in" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
      </div>
    </ConfirmModal>
  );
};

export default Projects;
