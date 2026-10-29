import React, { useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader } from '@/components/Shell';
import { copyText, ErrorState, Icon, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';

type Level = 'yes' | 'partial' | 'no' | 'unknown';

interface Host {
  id: string;
  name: string;
  family: string;
  status: string;
  statusCls: string;
  format: string | null; // memoryhub config init --format
  caps: Record<'tools' | 'recall' | 'capture' | 'lifecycle', Level>;
  notes: string;
  issues: string[];
}

/**
 * Host support as recorded in the R1 issue audit (upstream main at 4218eb5).
 * Replace with the published support manifest once R1-007 ships one.
 */
const HOSTS: Host[] = [
  {
    id: 'claude',
    name: 'Claude Code',
    family: 'Generated rules and hooks',
    status: 'In progress',
    statusCls: 'blue',
    format: 'claude-code',
    caps: { tools: 'yes', recall: 'yes', capture: 'partial', lifecycle: 'partial' },
    notes: 'Rules, hooks and generated instructions exist; packaging and a host-tested support claim are still open.',
    issues: ['#551'],
  },
  {
    id: 'openclaw',
    name: 'OpenClaw',
    family: 'Native plugin',
    status: 'In progress',
    statusCls: 'blue',
    format: null,
    caps: { tools: 'yes', recall: 'yes', capture: 'no', lifecycle: 'partial' },
    notes: 'TypeScript plugin with memory tools and automatic recall. Automatic capture is incomplete; session reset needs work.',
    issues: ['#489', '#495', '#496'],
  },
  {
    id: 'opencode',
    name: 'OpenCode',
    family: 'Native plugin',
    status: 'Known issue',
    statusCls: 'ylw',
    format: null,
    caps: { tools: 'yes', recall: 'partial', capture: 'no', lifecycle: 'partial' },
    notes: 'Plugin with memory tools and automatic recall. Pending recall is process-scoped and can bleed between concurrent sessions.',
    issues: ['#509', '#606'],
  },
  {
    id: 'codex',
    name: 'Codex',
    family: 'Generated instructions (planned)',
    status: 'Not available yet',
    statusCls: 'g',
    format: 'agents-md',
    caps: { tools: 'unknown', recall: 'unknown', capture: 'unknown', lifecycle: 'unknown' },
    notes: 'No Codex integration upstream. Generic AGENTS.md instructions plus a manual MCP registration may work but are untested.',
    issues: ['#582'],
  },
  {
    id: 'goose',
    name: 'Goose',
    family: 'To be decided',
    status: 'Not available yet',
    statusCls: 'g',
    format: 'system-prompt',
    caps: { tools: 'unknown', recall: 'unknown', capture: 'unknown', lifecycle: 'unknown' },
    notes: 'No Goose integration upstream and no verified host model yet.',
    issues: ['#312', '#623'],
  },
];

const CAPS: { id: keyof Host['caps']; label: string; hint: string }[] = [
  { id: 'tools', label: 'Memory tools', hint: 'The agent can search, read and write memories.' },
  { id: 'recall', label: 'Automatic recall', hint: 'Relevant memories are loaded without the agent asking.' },
  { id: 'capture', label: 'Automatic capture', hint: 'New memories are extracted from the conversation.' },
  { id: 'lifecycle', label: 'Session lifecycle', hint: 'Session start, reset and cleanup are handled.' },
];

const LEVEL: Record<Level, { text: string; cls: string }> = {
  yes: { text: 'Yes', cls: 'ok' },
  partial: { text: 'Partial', cls: 'warn' },
  no: { text: 'No', cls: 'err' },
  unknown: { text: 'Untested', cls: 'muted' },
};

interface ConnectInfo {
  mcp_url: string;
  auth_url: string;
  tenant: string;
  agents: string[];
  projects: string[];
}

/** Connect an agent: supported hosts and the setup commands. Never generates or stores credentials. */
const Connect: React.FC = () => {
  const toast = useToast();
  const { data, error, loading, reload } = useApi<ConnectInfo>(() => api.connectInfo(), []);
  const [host, setHost] = useState('claude');
  const [project, setProject] = useState('');
  const h = HOSTS.find((x) => x.id === host) ?? HOSTS[0];

  const commands = useMemo(() => {
    if (!data) return '';
    const lines = [
      '# 1. Sign the CLI in (prompts for the client secret; stored in ~/.config/memoryhub, mode 600)',
      `memoryhub login --url ${data.mcp_url} --auth-url ${data.auth_url} --client-id <your-agent-client-id>`,
      '',
      '# 2. In your project folder: write .memoryhub.yaml and the host instructions',
      `memoryhub config init${project ? ` --project ${project}` : ''}${h.format ? ` --format ${h.format}` : ''}`,
    ];
    if (h.id === 'openclaw' || h.id === 'opencode') {
      lines.push('', `# 3. Install the ${h.name} plugin from integrations/${h.id}/ in the MemoryHub repository and point it at the same URL`);
    }
    return lines.join('\n');
  }, [data, h, project]);

  const copy = async () => toast((await copyText(commands)) ? 'Commands copied.' : 'Could not copy.', 'ok');

  return (
    <>
      <PageHeader
        title="Connect an agent"
        description="Point your agent host at this MemoryHub. Setup runs on your machine with the memoryhub CLI; the dashboard never creates or shows secrets."
      />
      <div className="body">
        {error && !data ? (
          <div className="card">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : loading && !data ? (
          <div className="card">
            <SkLines lines={8} />
          </div>
        ) : (
          data && (
            <>
              <section className="card">
                <h3>Supported hosts</h3>
                <p className="sm muted" style={{ margin: '6px 0 12px' }}>
                  From the Release 1 issue audit (upstream main 4218eb5). This table is replaced by the published support manifest when it exists (R1-007).
                </p>
                <div className="tbl-scroll">
                  <table className="hosts">
                    <thead>
                      <tr>
                        <th>Host</th>
                        <th>Status</th>
                        {CAPS.map((c) => (
                          <th key={c.id} title={c.hint}>
                            {c.label}
                          </th>
                        ))}
                        <th>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {HOSTS.map((x) => (
                        <tr key={x.id}>
                          <td>
                            <b>{x.name}</b>
                            <span className="hint" style={{ display: 'block' }}>{x.family}</span>
                          </td>
                          <td className="cap">
                            <span className={`lbl ${x.statusCls}`}>{x.status}</span>
                          </td>
                          {CAPS.map((c) => (
                            <td key={c.id} className={`cap sm ${LEVEL[x.caps[c.id]].cls}`}>
                              {LEVEL[x.caps[c.id]].text}
                            </td>
                          ))}
                          <td className="sm">
                            {x.notes} <span className="muted">{x.issues.join(', ')}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <div className="row-wrap">
                <section className="card col-main">
                  <h3>Set up</h3>
                  <div className="fg" style={{ marginTop: 12 }}>
                    <div className="f">
                      <label htmlFor="ch">Host</label>
                      <select id="ch" className="in" value={host} onChange={(e) => setHost(e.target.value)}>
                        {HOSTS.map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.name}
                            {x.status === 'Not available yet' ? ' (untested)' : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="f">
                      <label htmlFor="cp">Project</label>
                      <select id="cp" className="in" value={project} onChange={(e) => setProject(e.target.value)}>
                        <option value="">No project — user memories only</option>
                        {data.projects.map((p) => (
                          <option key={p} value={p}>
                            {p}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  {h.status === 'Not available yet' && (
                    <div className="alert warn-a" style={{ marginTop: 14 }}>
                      <Icon.Warn size={18} />
                      <span className="sm">
                        There is no {h.name} integration yet. The commands below register MemoryHub with generic instructions; recall and capture are not guaranteed.
                      </span>
                    </div>
                  )}
                  <pre className="dark" style={{ marginTop: 14 }}>{commands}</pre>
                  <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                    <button type="button" className="btn bs" onClick={copy}>
                      Copy commands
                    </button>
                    <a className="btn bp" href={buildHash('/verify')}>
                      Then run the connection check <Icon.Arrow size={14} />
                    </a>
                  </div>
                </section>
                <aside className="col-side">
                  <section className="card">
                    <h3>This MemoryHub</h3>
                    <dl className="dl" style={{ marginTop: 14 }}>
                      <dt>MCP URL</dt>
                      <dd className="mono">{data.mcp_url}</dd>
                      <dt>Auth URL</dt>
                      <dd className="mono">{data.auth_url}</dd>
                      <dt>Tenant</dt>
                      <dd className="mono">{data.tenant}</dd>
                    </dl>
                  </section>
                  <section className="card">
                    <h3>Agent identity</h3>
                    <p className="sm" style={{ margin: '8px 0' }}>
                      {data.agents.length ? (
                        <>
                          Linked to you: <span className="mono">{data.agents.join(', ')}</span>. Use one of these client IDs so the agent's memories count as yours.
                        </>
                      ) : (
                        <>No agent is linked to you yet. Get a client ID and secret, then link it so its memories count as yours.</>
                      )}
                    </p>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      <a className="btn bs sm" href={buildHash('/clients')}>
                        Agent credentials
                      </a>
                      <a className="btn bg sm" href={buildHash('/identities')}>
                        My agents
                      </a>
                    </div>
                  </section>
                  <section className="card">
                    <h3>What gets remembered</h3>
                    <p className="sm" style={{ margin: '8px 0 0' }}>
                      Choose a memory-behavior profile in <a href={buildHash('/preferences')}>Preferences</a>.
                    </p>
                  </section>
                </aside>
              </div>
            </>
          )
        )}
      </div>
    </>
  );
};

export default Connect;
