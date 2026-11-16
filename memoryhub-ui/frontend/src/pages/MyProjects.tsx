import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CampaignRow, ProjectDetail, ProjectRole, ProjectRow, TeamRow } from '@/types';
import { fmtInt, fmtRelative } from '@/utils/format';
import { ConfirmModal } from './common';
import { NewRequestModal } from './requests';

/**
 * Projects & teams for a user: read-only. Users see the projects, teams and
 * campaigns they belong to and their role in each; they cannot create teams
 * or manage other members. Joining goes through a request; leaving is theirs.
 */

const ROLE_LABEL: Record<ProjectRole, string> = { owner: 'Owner', manager: 'Project Manager', contributor: 'Contributor', viewer: 'Viewer' };

/** Older backends know admin/member only. */
const projectRole = (role: string | null | undefined): ProjectRole | null => {
  if (!role) return null;
  if (role === 'owner' || role === 'manager' || role === 'contributor' || role === 'viewer') return role;
  if (role === 'admin') return 'manager';
  if (role === 'member') return 'contributor';
  return null;
};
const roleLabel = (role: string | null | undefined) => {
  const r = projectRole(role);
  return r ? ROLE_LABEL[r] : role ?? '—';
};

type Kind = 'projects' | 'teams' | 'campaigns';

const MyProjects: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { me } = useApp();
  const raw = route.params.get('kind');
  const kind: Kind = raw === 'teams' || raw === 'campaigns' ? raw : 'projects';
  const projects = useApi(() => api.projects(true), []);
  const teams = useApi(() => api.teams(), []);
  const campaigns = useApi(() => api.campaigns(), []);
  const [joining, setJoining] = useState(false);

  const myProjects = projects.data?.items ?? [];
  const myTeams = (teams.data?.items ?? []).filter((t) => t.members.some((m) => m.user_id === me?.username));
  const projectNames = new Set(myProjects.map((p) => p.name));
  const myCampaigns = (campaigns.data?.items ?? []).filter((c) => c.projects.some((p) => projectNames.has(p)));

  const setParam = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(route.params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    navigate('/projects', next, { replace: true });
  };
  const selProject = myProjects.find((p) => p.name === route.params.get('project')) ?? myProjects[0] ?? null;
  const selTeam = myTeams.find((t) => t.id === route.params.get('team')) ?? myTeams[0] ?? null;
  const selCampaign = myCampaigns.find((c) => c.id === route.params.get('campaign')) ?? myCampaigns[0] ?? null;

  return (
    <>
      <PageHeader
        title="Projects & teams"
        description="Projects, teams and campaigns you belong to. What you can change depends on your role in each one, not on your account role."
        actions={
          <button type="button" className="btn bs" onClick={() => setJoining(true)}>
            Request to join…
          </button>
        }
        tabs={
          <Tabs
            label="Kind"
            value={kind}
            onChange={(k) => navigate('/projects', k === 'projects' ? undefined : { kind: k }, { replace: true })}
            tabs={[
              { value: 'projects', label: 'Projects', count: projects.data ? myProjects.length : null },
              { value: 'teams', label: 'Teams', count: teams.data ? myTeams.length : null },
              { value: 'campaigns', label: 'Campaigns', count: campaigns.data ? myCampaigns.length : null },
            ]}
          />
        }
      />
      <div className="body">
        {kind === 'projects' ? (
          <Split
            loading={projects.loading && !projects.data}
            error={projects.error && !projects.data ? projects.error : null}
            reload={projects.reload}
            empty={myProjects.length === 0}
            emptyTitle="You are not in any project yet"
            emptyText="Projects are created by platform admins, who add their members. Use Request to join to ask for access."
            list={myProjects.map((p) => ({
              key: p.name,
              title: p.name,
              sub: `${roleLabel(p.my_role)} · ${fmtInt(p.members)} members · ${fmtInt(p.memories)} memories${p.archived ? ' · archived' : ''}`,
              on: p.name === selProject?.name,
              go: () => setParam({ project: p.name }),
            }))}
            detail={selProject ? <ProjectView key={selProject.name} row={selProject} onLeft={() => { setParam({ project: undefined }); projects.reload(); }} /> : null}
          />
        ) : kind === 'teams' ? (
          <Split
            loading={teams.loading && !teams.data}
            error={teams.error && !teams.data ? teams.error : null}
            reload={teams.reload}
            empty={myTeams.length === 0}
            emptyTitle="You are not in a team"
            emptyText="Teams are groups of people set up by a platform admin or a team lead."
            list={myTeams.map((t) => ({
              key: t.id,
              title: t.name,
              sub: `${t.members.find((m) => m.user_id === me?.username)?.role === 'lead' ? 'Lead' : 'Member'} · ${t.members.length} people · ${t.projects.length} projects`,
              on: t.id === selTeam?.id,
              go: () => setParam({ team: t.id }),
            }))}
            detail={selTeam ? <TeamView team={selTeam} self={me?.username} /> : null}
          />
        ) : (
          <Split
            loading={campaigns.loading && !campaigns.data}
            error={campaigns.error && !campaigns.data ? campaigns.error : null}
            reload={campaigns.reload}
            empty={myCampaigns.length === 0}
            emptyTitle="None of your projects is in a campaign"
            emptyText="Campaigns group projects under one policy and memory lifetime for a bounded initiative."
            list={myCampaigns.map((c) => ({
              key: c.id,
              title: c.name,
              sub: `${c.status} · ${c.projects.length} projects · ${fmtInt(c.memories)} memories`,
              on: c.id === selCampaign?.id,
              go: () => setParam({ campaign: c.id }),
            }))}
            detail={selCampaign ? <CampaignView campaign={selCampaign} mine={projectNames} /> : null}
          />
        )}
      </div>
      {joining && <NewRequestModal initialKind="project_access" onClose={() => setJoining(false)} onCreated={() => undefined} />}
    </>
  );
};

/** A narrow list on the left, the selected record on the right. */
const Split: React.FC<{
  loading: boolean;
  error: Error | null;
  reload: () => void;
  empty: boolean;
  emptyTitle: string;
  emptyText: string;
  list: { key: string; title: string; sub: string; on: boolean; go: () => void }[];
  detail: React.ReactNode;
}> = ({ loading, error, reload, empty, emptyTitle, emptyText, list, detail }) => {
  if (error) return <div className="card"><ErrorState error={error} onRetry={reload} /></div>;
  if (loading) return <div className="card"><SkLines lines={6} /></div>;
  if (empty)
    return (
      <div className="card">
        <Empty title={emptyTitle}>{emptyText}</Empty>
      </div>
    );
  return (
    <div className="row-wrap">
      <nav className="card plist" aria-label="Your records">
        {list.map((i) => (
          <button key={i.key} type="button" className={i.on ? 'on' : ''} aria-current={i.on ? 'true' : undefined} onClick={i.go}>
            <span className="b6">{i.title}</span>
            <span className="hint">{i.sub}</span>
          </button>
        ))}
      </nav>
      <div className="col-main" style={{ flex: '999 1 620px' }}>
        {detail}
      </div>
    </div>
  );
};

const ProjectView: React.FC<{ row: ProjectRow; onLeft: () => void }> = ({ row, onLeft }) => {
  const toast = useToast();
  const { me } = useApp();
  const { data, error, loading, reload } = useApi<ProjectDetail>(() => api.project(row.name), [row.name]);
  const [leaving, setLeaving] = useState(false);
  if (error && !data) return <div className="card"><ErrorState error={error} onRetry={reload} compact /></div>;
  if (loading && !data) return <div className="card"><SkLines lines={10} /></div>;
  if (!data) return null;

  const myRole = projectRole(data.my_project_role ?? data.my_role ?? row.my_role);
  const owner = data.owner ?? data.created_by;
  const managers = data.managers ?? data.members_list.filter((m) => projectRole(m.role) === 'manager').map((m) => m.user_id);
  const quota = data.policies?.max_memories ? Math.round((data.memories / data.policies.max_memories) * 100) : null;
  const focusTotal = (data.focus_history ?? []).reduce((a, f) => a + f.count, 0);
  const isMember = Boolean(myRole);

  return (
    <>
      <section className="card">
        <div className="ch" style={{ alignItems: 'flex-start' }}>
          <div>
            <h2 className="card-title">{data.name}</h2>
            <div className="sm muted">
              Owner {owner}
              {managers.length > 0 && ` · Project Manager ${managers.join(', ')}`}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {myRole && <span className="lbl blue lg">Your role: {ROLE_LABEL[myRole]}</span>}
            <a className="btn bs sm" href={buildHash('/memories', { project: data.name })}>
              Browse memories
            </a>
          </div>
        </div>
        {data.archived && (
          <div className="alert warn-a" role="status" style={{ marginBottom: 14 }}>
            <div>
              <b>Archived{data.archived_at ? ` ${fmtRelative(data.archived_at).toLowerCase()}` : ''}.</b> Read-only: members still read its memories; nobody writes to it.
            </div>
          </div>
        )}
        <div className="stat4">
          <Stat label="Memories" value={fmtInt(data.memories)} />
          <Stat label="Written by you" value={data.written_by_me === null || data.written_by_me === undefined ? '—' : fmtInt(data.written_by_me)} />
          <Stat label="Quota" value={quota === null ? '—' : `${quota}%`} />
          <Stat label="Open contradictions" value={data.open_contradictions === null || data.open_contradictions === undefined ? '—' : fmtInt(data.open_contradictions)} />
        </div>
      </section>

      <div className="grid-eq">
        <section className="card">
          <div className="ch">
            <h2 data-h="3">Members</h2>
            <span className="sm muted">Read only</span>
          </div>
          <div>
            {data.members_list.length === 0 && <p className="sm muted">No members yet.</p>}
            {data.members_list.map((m) => {
              const r = m.user_id === owner ? 'owner' : projectRole(m.role);
              return (
                <div key={m.user_id} className="evrow" style={{ justifyContent: 'space-between' }}>
                  <span className="sm">
                    {m.user_id}
                    {m.user_id === me?.username && ' (you)'}
                    {m.via_team && <span className="hint"> · via team {m.via_team}</span>}
                  </span>
                  <span className="lbl g">{r ? ROLE_LABEL[r] : m.role}</span>
                </div>
              );
            })}
          </div>
        </section>
        <section className="card">
          <div className="ch">
            <h2 data-h="3">Agent loading policy</h2>
            <span className="sm muted">Set by the Project Manager</span>
          </div>
          {data.loading ? (
            <dl className="kv">
              <dt>Load at session start</dt>
              <dd>{data.loading.session_start}</dd>
              <dt>Always include</dt>
              <dd>{data.loading.always_include}</dd>
              <dt>Superseded versions</dt>
              <dd>{data.loading.superseded}</dd>
            </dl>
          ) : (
            <pre>{data.loading_policy}</pre>
          )}
        </section>
      </div>

      <section className="card">
        <div className="ch">
          <h2 data-h="3">Session focus · last 30 days</h2>
          <span className="sm muted">Topics your agents worked on in this project</span>
        </div>
        {!data.focus_available || !data.focus_history?.length ? (
          <p className="sm muted" style={{ margin: 0 }}>
            {data.focus_available ? 'No agent declared a session focus here in the last 30 days.' : 'Focus history is not available on this deployment.'}
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {data.focus_history.map((f) => {
              const pct = focusTotal ? Math.round((f.count / focusTotal) * 100) : 0;
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

      <section className="card">
        <div className="ch">
          <h2 data-h="3">Project management</h2>
          <span className="lbl g lg">
            Membership: {isMember ? 'member' : 'none'}
            {myRole ? ` · Project role: ${ROLE_LABEL[myRole]}` : ''}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="btn bs sm" disabled>
            Add member
          </button>
          <button type="button" className="btn bs sm" disabled>
            Edit loading policy
          </button>
          <button type="button" className="btn bs sm" disabled>
            Archive
          </button>
          <button type="button" className="btn bd outline sm" disabled>
            Delete project
          </button>
        </div>
        <p className="sm" style={{ margin: '12px 0 0', display: 'flex', gap: 6, alignItems: 'center' }}>
          <Icon.Lock /> Needs project.manage — Project Manager or Owner. Ask {owner}, or a Platform Admin.
        </p>
        <p className="sm muted" style={{ margin: '8px 0 0' }}>
          Owners transfer ownership and delete the project by procedure. Creating projects and quotas stay in the Tenant Console. Leaving the project removes it from all your
          agents at once.
        </p>
        {isMember && (
          <button type="button" className="btn bl" style={{ marginTop: 6, paddingLeft: 0 }} onClick={() => setLeaving(true)}>
            Leave project…
          </button>
        )}
      </section>

      {leaving && me && (
        <ConfirmModal
          title={`Leave ${data.name}?`}
          confirmLabel="Leave project"
          danger
          onClose={() => setLeaving(false)}
          onConfirm={async () => {
            await api.removeMember(data.name, me.username);
            toast(`You left ${data.name}. Your agents no longer read or write its memories.`);
            onLeft();
          }}
        >
          You and all your agents lose read and write access to <b>{data.name}</b> project memories. Memories you wrote stay in the project. To come back, submit a request to join.
        </ConfirmModal>
      )}
    </>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div className="sm muted">{label}</div>
    <div className="kpi">{value}</div>
  </div>
);

const TeamView: React.FC<{ team: TeamRow; self?: string }> = ({ team, self }) => (
  <>
    <section className="card">
      <h2 className="card-title">{team.name}</h2>
      <div className="sm muted">{team.description || 'No description'} · created by {team.created_by}</div>
    </section>
    <div className="grid-eq">
      <section className="card">
        <div className="ch">
          <h2 data-h="3">People</h2>
          <span className="sm muted">Read only</span>
        </div>
        {team.members.map((m) => (
          <div key={m.user_id} className="evrow" style={{ justifyContent: 'space-between' }}>
            <span className="sm">
              {m.user_id}
              {m.user_id === self && ' (you)'}
            </span>
            <span className="lbl g">{m.role === 'lead' ? 'Lead' : 'Member'}</span>
          </div>
        ))}
      </section>
      <section className="card">
        <div className="ch">
          <h2 data-h="3">Projects this team works on</h2>
        </div>
        {team.projects.length === 0 && <p className="sm muted">None yet.</p>}
        {team.projects.map((p) => (
          <div key={p} className="evrow">
            <a className="sm" href={buildHash('/projects', { project: p })}>
              {p}
            </a>
          </div>
        ))}
      </section>
    </div>
    <p className="sm muted" style={{ margin: 0, display: 'flex', gap: 6, alignItems: 'center' }}>
      <Icon.Lock /> Team members and linked projects are managed by the team lead or a Platform Admin.
    </p>
  </>
);

const CampaignView: React.FC<{ campaign: CampaignRow; mine: Set<string> }> = ({ campaign, mine }) => (
  <>
    <section className="card">
      <div className="ch" style={{ alignItems: 'flex-start' }}>
        <div>
          <h2 className="card-title">{campaign.name}</h2>
          <div className="sm muted">{campaign.description || 'No description'}</div>
        </div>
        <span className={`lbl ${campaign.status === 'active' ? 'grn' : 'g'}`}>{campaign.status}</span>
      </div>
      <div className="stat4">
        <Stat label="Projects" value={fmtInt(campaign.projects.length)} />
        <Stat label="Memories" value={fmtInt(campaign.memories)} />
        <Stat label="Default lifetime" value={campaign.default_ttl_days ? `${campaign.default_ttl_days} d` : '—'} />
      </div>
    </section>
    <section className="card">
      <div className="ch">
        <h2 data-h="3">Enrolled projects</h2>
        <span className="sm muted">Read only</span>
      </div>
      {campaign.projects.map((p) => (
        <div key={p} className="evrow" style={{ justifyContent: 'space-between' }}>
          <a className="sm" href={buildHash('/projects', { project: p })}>
            {p}
          </a>
          {mine.has(p) && <span className="lbl blue">You are a member</span>}
        </div>
      ))}
    </section>
  </>
);

export default MyProjects;
