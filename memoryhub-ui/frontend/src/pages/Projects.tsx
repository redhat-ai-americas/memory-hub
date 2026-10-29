import React, { useEffect, useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs } from '@/components/Shell';
import { Dropdown, Empty, ErrorState, Modal, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CampaignRow, ProjectDetail, ProjectRow } from '@/types';
import { avatarColor, errorMessage, fmtInt, fmtRelative, initials } from '@/utils/format';
import { ConfirmModal } from './common';
import { ProjectTeams, TeamForm, TeamPanel, TeamsTable } from './Teams';

const Projects: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const kindParam = route.params.get('kind');
  const kind = kindParam === 'campaigns' ? 'campaigns' : kindParam === 'teams' ? 'teams' : 'projects';
  const selectedTeam = route.params.get('team');
  const selectedName = route.params.get('project');
  const selectedCampaign = route.params.get('campaign');
  const [mine, setMine] = useState(false);
  const [filter, setFilter] = useState('');
  const [modal, setModal] = useState<null | 'project' | 'campaign' | 'team' | 'edit' | 'member' | 'enroll'>(null);

  const projects = useApi(() => api.projects(mine), [mine]);
  const campaigns = useApi(() => api.campaigns(), []);
  const teams = useApi(() => api.teams(), []);
  const activeTeam = (teams.data?.items ?? []).find((t) => t.id === selectedTeam) ?? teams.data?.items?.[0] ?? null;
  const rows = (projects.data?.items ?? []).filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()) || (p.description ?? '').toLowerCase().includes(filter.toLowerCase()));
  const camps = (campaigns.data?.items ?? []).filter((c) => c.name.toLowerCase().includes(filter.toLowerCase()));
  const activeProject = selectedName ?? rows[0]?.name ?? null;
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
            <button type="button" className="btn bp" onClick={() => setModal('project')}>
              Create project
            </button>
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
              <input id="pf" className="in" placeholder="Filter by name" style={{ flex: '1 1 240px' }} value={filter} onChange={(e) => setFilter(e.target.value)} />
              {kind === 'projects' && (
                <div className="seg" role="group" aria-label="Which projects">
                  <button type="button" className={mine ? 'on' : ''} aria-pressed={mine} onClick={() => setMine(true)}>
                    Mine
                  </button>
                  <button type="button" className={!mine ? 'on' : ''} aria-pressed={!mine} onClick={() => setMine(false)}>
                    All in tenant
                  </button>
                </div>
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
                  title={filter ? 'No projects match' : mine ? 'You are not in any project yet' : 'No projects yet'}
                  action={
                    !filter && (
                      <button type="button" className="btn bp" onClick={() => setModal('project')}>
                        Create project
                      </button>
                    )
                  }
                >
                  {filter ? 'Try another name.' : 'Agents create open projects on their first project-scope write, or you can create one here.'}
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
                            <div className="sm muted">{p.description || '—'}</div>
                          </td>
                          <td>{p.invite_only ? <span className="lbl blue">Invite-only</span> : <span className="lbl g">Open</span>}</td>
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
                                  <button type="button" onClick={() => { close(); setParam({ project: p.name }); setModal('edit'); }}>
                                    Edit
                                  </button>
                                  <button type="button" onClick={() => { close(); setParam({ project: p.name }); setModal('member'); }}>
                                    Add member
                                  </button>
                                  <a href={buildHash('/memories', { project: p.name })}>Browse memories</a>
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
                <ProjectPanel name={activeProject} onEdit={() => setModal('edit')} onAddMember={() => setModal('member')} key={activeProject} />
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
          existing={projects.data?.items.find((p) => p.name === activeProject)}
          onClose={() => setModal(null)}
          onSaved={() => {
            toast('Project updated.');
            reloadAll();
            setParam({ project: activeProject, _r: String(Date.now()) });
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

const ProjectPanel: React.FC<{ name: string; onEdit: () => void; onAddMember: () => void }> = ({ name, onEdit, onAddMember }) => {
  const toast = useToast();
  const { route } = useRouteToken();
  const { data, error, loading, reload } = useApi<ProjectDetail>(() => api.project(name), [name, route]);
  const [showAll, setShowAll] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
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
          <button type="button" className="btn bg" onClick={onEdit}>
            Edit
          </button>
        </div>
        <p className="sm muted" style={{ margin: '0 0 14px' }}>
          {data.description ? `${data.description}. ` : ''}
          {data.invite_only ? 'Invite-only — members are added by a project admin.' : 'Open enrollment — agents join on first project-scope write.'}
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
        <div className="ch" style={{ marginBottom: 10 }}>
          <b className="sm">Members</b>
          <button type="button" className="btn bl sm" onClick={onAddMember}>
            + Add member
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14 }}>
          {data.members_list.length === 0 && <span className="sm muted">No members yet.</span>}
          {members.map((m) => (
            <div key={m.user_id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="mav" style={{ background: avatarColor(m.user_id) }}>
                {initials(m.user_id)}
              </span>
              <span style={{ flex: 1 }}>
                {m.user_id}
                {m.joined_by === m.user_id && <span className="sm muted"> · auto-enrolled</span>}
                {m.via_team && <span className="sm muted"> · via team {m.via_team}</span>}
              </span>
              <span className={`lbl ${m.role === 'admin' ? 'blue' : 'g'}`}>{m.role}</span>
              <button type="button" className="btn bl sm" aria-label={`Remove ${m.user_id}`} style={{ padding: '2px 6px' }} onClick={() => setRemoving(m.user_id)}>
                ✕
              </button>
            </div>
          ))}
          {data.members_list.length > 3 && (
            <button type="button" className="link-btn sm" style={{ alignSelf: 'flex-start' }} onClick={() => setShowAll((s) => !s)}>
              {showAll ? 'Show fewer' : `Show ${data.members_list.length - 3} more`}
            </button>
          )}
        </div>
        <ProjectTeams project={data.name} teams={data.teams ?? []} onChanged={reload} />
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

const ProjectForm: React.FC<{ existing?: ProjectRow; onClose: () => void; onSaved: (name: string) => void }> = ({ existing, onClose, onSaved }) => {
  const [name, setName] = useState(existing?.name ?? '');
  const [description, setDescription] = useState(existing?.description ?? '');
  const [inviteOnly, setInviteOnly] = useState(existing?.invite_only ?? false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      if (existing) await api.updateProject(existing.name, { description: description || null, invite_only: inviteOnly });
      else await api.createProject({ name: name.trim(), description: description.trim() || undefined, invite_only: inviteOnly });
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
            <span className="hint">Letters, numbers, dots, dashes and underscores. Agents use this as the project ID.</span>
          </div>
        )}
        <div className="f">
          <label htmlFor="pd">Description</label>
          <input id="pd" className="in" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <label className="swrow">
          <span>
            <b>Invite-only</b>
            <div className="hint">Agents must be added by a project admin before they can read or write.</div>
          </span>
          <input type="checkbox" checked={inviteOnly} onChange={(e) => setInviteOnly(e.target.checked)} />
        </label>
        {err && <div className="alert err-a">{err}</div>}
        <div className="modal-actions">
          <button type="submit" className="btn bp" disabled={busy}>
            {existing ? 'Save' : 'Create project'}
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
  const [userId, setUserId] = useState('');
  const [role, setRole] = useState('member');
  const [err, setErr] = useState<string | null>(null);
  const { data } = useApi(() => api.identities(), []);
  return (
    <Modal
      title={`Add member to ${project}`}
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={!userId.trim()}
            onClick={async () => {
              try {
                await api.addMember(project, { user_id: userId.trim(), role });
                onSaved();
                onClose();
              } catch (e) {
                setErr(errorMessage(e));
              }
            }}
          >
            Add member
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="f">
        <label htmlFor="mu">User or agent ID</label>
        <input id="mu" className="in" list="member-ids" value={userId} onChange={(e) => setUserId(e.target.value)} />
        <datalist id="member-ids">
          {(data?.items ?? []).map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </datalist>
      </div>
      <div className="f">
        <label htmlFor="mr">Role</label>
        <select id="mr" className="in" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="member">member</option>
          <option value="admin">admin</option>
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

export default Projects;
