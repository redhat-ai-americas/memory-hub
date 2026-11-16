import React, { useState } from 'react';
import { platform, type Runbook } from '@/api/platform';
import { PageHeader, Tabs } from '@/components/Shell';
import { Empty, ErrorState, Icon, SkTable } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import { dateShort } from './common';

const TABS: { value: Runbook['kind']; label: string; noun: string }[] = [
  { value: 'runbook', label: 'Runbooks', noun: 'runbooks' },
  { value: 'procedure', label: 'Incident procedures', noun: 'procedures' },
  { value: 'decision', label: 'Decisions', noun: 'decisions' },
  { value: 'draft', label: 'Drafts', noun: 'drafts' },
];

const Runbooks: React.FC<{ route: HashRoute }> = ({ route }) => {
  const tab = TABS.find((t) => t.value === route.params.get('tab')) ?? TABS[0];
  const { data, error, loading, reload } = useApi(() => platform.runbooks(), []);
  const [q, setQ] = useState('');
  const [component, setComponent] = useState('');
  const [reviewed, setReviewed] = useState('');
  const all = data?.items ?? [];
  const rows = all.filter(
    (r) =>
      r.kind === tab.value &&
      (!component || r.component === component) &&
      (!reviewed || (reviewed === 'stale' ? !r.reviewed_at || Date.now() - Date.parse(r.reviewed_at) > 90 * 86400000 : !!r.reviewed_at && Date.now() - Date.parse(r.reviewed_at) <= 90 * 86400000)) &&
      (!q || r.title.toLowerCase().includes(q.toLowerCase())),
  );
  const components = [...new Set(all.map((r) => r.component))].sort();

  return (
    <>
      <PageHeader
        title="Operations knowledge"
        crumbs={[{ label: 'Operations knowledge' }]}
        description="Curated runbooks, incident procedures and operator decisions for the authorized operations team. Written and reviewed on purpose — never assembled from what admins see, and never a copy of user memories."
        actions={
          <>
            <span className="lbl g" style={{ padding: '6px 14px' }}>
              Optional module
            </span>
            <button type="button" className="btn bp" disabled={data?.source === 'single-tenant'} title={data?.source === 'single-tenant' ? 'Runbooks are stored by the platform service' : undefined}>
              <Icon.Plus /> New runbook
            </button>
          </>
        }
        tabs={
          <Tabs
            label="Knowledge type"
            value={tab.value}
            onChange={(t) => navigate('/runbooks', t === 'runbook' ? undefined : { tab: t }, { replace: true })}
            tabs={TABS.map((t) => ({ value: t.value, label: t.label, count: data ? all.filter((r) => r.kind === t.value).length : null }))}
          />
        }
      />
      <div className="body">
        <div className="filters">
          <span className="in-icon">
            <Icon.Search size={15} />
            <label htmlFor="rb-q" className="vh">
              Search
            </label>
            <input id="rb-q" className="in" placeholder={`Search ${tab.noun}`} value={q} onChange={(e) => setQ(e.target.value)} />
          </span>
          <label htmlFor="rb-c" className="vh">
            Component
          </label>
          <select id="rb-c" className="in auto" value={component} onChange={(e) => setComponent(e.target.value)}>
            <option value="">Component: any</option>
            {components.map((c) => (
              <option key={c} value={c}>
                Component: {c}
              </option>
            ))}
          </select>
          <label htmlFor="rb-r" className="vh">
            Reviewed
          </label>
          <select id="rb-r" className="in auto" value={reviewed} onChange={(e) => setReviewed(e.target.value)}>
            <option value="">Reviewed: any</option>
            <option value="fresh">Reviewed: last 90 days</option>
            <option value="stale">Reviewed: over 90 days ago</option>
          </select>
        </div>
        <section className="card" style={{ padding: '6px 12px' }}>
          {error && !data ? (
            <ErrorState error={error} onRetry={reload} />
          ) : loading && !data ? (
            <SkTable rows={4} cols={6} />
          ) : rows.length === 0 ? (
            <Empty compact title={all.length ? 'Nothing matches' : 'No operations knowledge yet'}>
              {all.length
                ? 'Clear a filter to see more.'
                : data?.source === 'single-tenant'
                  ? 'This optional module is stored by the platform service, which this deployment does not run yet.'
                  : 'Write the first runbook for the operations team.'}
            </Empty>
          ) : (
            <table className="tbl mid">
              <thead>
                <tr>
                  <th>{tab.label.replace(/s$/, '')}</th>
                  <th>Component</th>
                  <th>Owner</th>
                  <th>Version</th>
                  <th>Last reviewed</th>
                  <th>Audience</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a> : <span style={{ color: 'var(--mh-primary)' }}>{r.title}</span>}</td>
                    <td>{r.component}</td>
                    <td>{r.owner}</td>
                    <td>{r.version}</td>
                    <td>{dateShort(r.reviewed_at)}</td>
                    <td>{r.audience}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <div className="acc-cards two">
          <section className="card">
            <h2 data-h="3">How this differs from memory</h2>
            <ul className="rule-list">
              <li>Not personal memory of an admin, and not an “admin memory” collecting what admins saw.</li>
              <li>Every item has an owner, a version, a reviewer and an audience.</li>
              <li>Agents can read it only when an operator links a runbook to a session.</li>
            </ul>
          </section>
          <section className="card">
            <h2 data-h="3">Where other knowledge lives</h2>
            <dl className="detail-kv nums">
              <dt>Admin’s own notes &amp; preferences</dt>
              <dd>My workspace</dd>
              <dt>Who changed what</dt>
              <dd>
                <a href="#/global-audit">Global audit</a>
              </dd>
              <dt>Team / org knowledge</dt>
              <dd>Shared knowledge</dd>
            </dl>
          </section>
        </div>
      </div>
    </>
  );
};

export default Runbooks;
