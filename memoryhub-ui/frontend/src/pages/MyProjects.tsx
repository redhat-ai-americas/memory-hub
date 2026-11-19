import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { Empty, ErrorState, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { ProjectDetail, ProjectRow } from '@/types';
import { fmtInt, fmtRelative } from '@/utils/format';
import { ConfirmModal } from './common';
import { FocusHistory } from './Projects';

const roleLabel = (r: ProjectRow['my_role']) => (r === 'admin' ? 'admin' : r === 'member' ? 'member' : 'open project');

/**
 * Projects for a user: the projects they belong to and open (not invite-only)
 * projects they may read (GET /api/projects). Platform admins add and remove
 * members; a member can leave a project themselves.
 */
const MyProjects: React.FC<{ route: HashRoute }> = ({ route }) => {
  const projects = useApi(() => api.projects(false), []);
  const rows = projects.data?.items ?? [];
  const selected = rows.find((p) => p.name === route.params.get('project')) ?? rows[0] ?? null;
  const select = (name?: string) => navigate('/projects', name ? { project: name } : undefined, { replace: true });

  return (
    <>
      <PageHeader title="Projects" description="Projects you belong to and open projects you can read. Platform admins add and remove members." />
      <div className="body">
        {projects.error && !projects.data ? (
          <div className="card">
            <ErrorState error={projects.error} onRetry={projects.reload} />
          </div>
        ) : projects.loading && !projects.data ? (
          <div className="card">
            <SkLines lines={6} />
          </div>
        ) : rows.length === 0 ? (
          <div className="card">
            <Empty title="You are not in any project yet">Projects are created by platform admins, who add their members.</Empty>
          </div>
        ) : (
          <div className="row-wrap">
            <nav className="card plist" aria-label="Your projects">
              {rows.map((p) => (
                <button key={p.name} type="button" className={p.name === selected?.name ? 'on' : ''} aria-current={p.name === selected?.name ? 'true' : undefined} onClick={() => select(p.name)}>
                  <span className="b6">{p.name}</span>
                  <span className="hint">
                    {roleLabel(p.my_role)} · {fmtInt(p.members)} members · {fmtInt(p.memories)} memories
                  </span>
                </button>
              ))}
            </nav>
            <div className="col-main" style={{ flex: '999 1 620px' }}>
              {selected && (
                <ProjectView
                  key={selected.name}
                  row={selected}
                  onLeft={() => {
                    select(undefined);
                    projects.reload();
                  }}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div className="sm muted">{label}</div>
    <div className="kpi">{value}</div>
  </div>
);

const ProjectView: React.FC<{ row: ProjectRow; onLeft: () => void }> = ({ row, onLeft }) => {
  const toast = useToast();
  const { me } = useApp();
  const { data, error, loading, reload } = useApi<ProjectDetail>(() => api.project(row.name), [row.name]);
  const [leaving, setLeaving] = useState(false);
  if (error && !data)
    return (
      <div className="card">
        <ErrorState error={error} onRetry={reload} compact />
      </div>
    );
  if (loading && !data)
    return (
      <div className="card">
        <SkLines lines={10} />
      </div>
    );
  if (!data) return null;

  const isMember = Boolean(data.my_role);
  const admins = data.members_list.filter((m) => m.role === 'admin').map((m) => m.user_id);

  return (
    <>
      <section className="card">
        <div className="ch" style={{ alignItems: 'flex-start' }}>
          <div>
            <h2 className="card-title">{data.name}</h2>
            <div className="sm muted">
              Created by {data.created_by}
              {admins.length > 0 && ` · admins ${admins.join(', ')}`}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span className="lbl blue lg">{isMember ? `Your role: ${data.my_role}` : 'Open project'}</span>
            <a className="btn bs sm" href={buildHash('/memories', { project: data.name })}>
              Browse memories
            </a>
          </div>
        </div>
        {data.description && <p className="sm muted" style={{ margin: '0 0 12px' }}>{data.description}</p>}
        <div className="stat4">
          <Stat label="Memories" value={fmtInt(data.memories)} />
          <Stat label="Members" value={fmtInt(data.members)} />
          <Stat label="Last write" value={data.last_write ? fmtRelative(data.last_write) : '—'} />
        </div>
      </section>

      <div className="grid-eq">
        <section className="card">
          <div className="ch">
            <h2 data-h="3">Members</h2>
            <span className="sm muted">Read only</span>
          </div>
          {data.members_list.length === 0 ? (
            <p className="sm muted">{isMember ? 'No members yet.' : 'Only members see who else is in the project.'}</p>
          ) : (
            data.members_list.map((m) => (
              <div key={m.user_id} className="evrow" style={{ justifyContent: 'space-between' }}>
                <span className="sm">
                  {m.user_id}
                  {m.user_id === me?.username && ' (you)'}
                </span>
                <span className={`lbl ${m.role === 'admin' ? 'blue' : 'g'}`}>{m.role}</span>
              </div>
            ))
          )}
        </section>
        <section className="card">
          <div className="ch">
            <h2 data-h="3">Campaigns</h2>
          </div>
          {data.campaigns.length === 0 ? (
            <p className="sm muted" style={{ margin: 0 }}>This project is not part of a campaign.</p>
          ) : (
            data.campaigns.map((c) => (
              <div key={c.id} className="evrow" style={{ justifyContent: 'space-between' }}>
                <span className="sm">{c.name}</span>
                <span className={`lbl ${c.status === 'active' ? 'grn' : 'g'}`}>{c.status}</span>
              </div>
            ))
          )}
        </section>
      </div>

      <FocusHistory data={data} />

      {isMember && (
        <section className="card">
          <div className="ch">
            <h2 data-h="3">Membership</h2>
            <span className="lbl g lg">You are a {data.my_role}</span>
          </div>
          <p className="sm muted" style={{ margin: 0 }}>
            Members are added and removed by a platform admin who administers this project. Leaving removes only your own membership: agents that were added to the project separately stay members until an admin removes them.
          </p>
          <button type="button" className="btn bl" style={{ marginTop: 6, paddingLeft: 0 }} onClick={() => setLeaving(true)}>
            Leave project…
          </button>
        </section>
      )}

      {leaving && me && (
        <ConfirmModal
          title={`Leave ${data.name}?`}
          confirmLabel="Leave project"
          danger
          onClose={() => setLeaving(false)}
          onConfirm={async () => {
            await api.removeMember(data.name, me.username);
            toast(`You left ${data.name}. You no longer read or write its memories from the dashboard.`);
            onLeft();
          }}
        >
          You lose read and write access to <b>{data.name}</b> project memories. Agents that are members of the project in their own right keep theirs. Memories you wrote stay in the project. A platform admin can add you again.
        </ConfirmModal>
      )}
    </>
  );
};

export default MyProjects;
