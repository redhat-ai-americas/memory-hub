import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs } from '@/components/Shell';
import { Empty, ErrorState, Icon, Pager, SkTable } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { EntitiesResponse, EntityType } from '@/types';
import { fmtInt, fmtRelative, shortId } from '@/utils/format';

const ENTITY_TYPES: { value: EntityType | 'all'; label: string; cls: string }[] = [
  { value: 'all', label: 'All', cls: 'g' },
  { value: 'person', label: 'People', cls: 'blue' },
  { value: 'organization', label: 'Organizations', cls: 'pur' },
  { value: 'location', label: 'Locations', cls: 's-project' },
  { value: 'object', label: 'Objects', cls: 'org' },
  { value: 'event', label: 'Events', cls: 'ylw' },
];

const Entities: React.FC<{ route: HashRoute }> = ({ route }) => {
  const tab = (route.params.get('type') || 'all') as EntityType | 'all';
  const query = route.params.get('q') || '';
  const project = route.params.get('project') || '';
  const page = Number(route.params.get('page') || 1);
  const perPage = Number(route.params.get('per') || 20);
  const [filter, setFilter] = useState(query);
  const [projectFilter, setProjectFilter] = useState(project);

  useEffect(() => setFilter(query), [query]);
  useEffect(() => setProjectFilter(project), [project]);

  const params = {
    q: query || undefined,
    type: tab,
    project: project || undefined,
    page,
    per_page: perPage,
  };
  const key = JSON.stringify(params);
  const { data, error, loading, reload } = useApi<EntitiesResponse>(() => api.entities(params), [key]);

  const setParams = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(route.params);
    Object.entries(changes).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)));
    if (!('page' in changes)) next.delete('page');
    navigate('/entities', next, { replace: true });
  };

  const applyFilters = (event: React.FormEvent) => {
    event.preventDefault();
    setParams({ q: filter.trim() || undefined, project: projectFilter.trim() || undefined });
  };

  const clearFilters = () => {
    setFilter('');
    setProjectFilter('');
    setParams({ q: undefined, project: undefined });
  };

  const selectedTab = ENTITY_TYPES.find((item) => item.value === tab)?.value ?? 'all';
  const items = data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Entities"
        description="People, organizations, places, objects and events extracted from memory. Each entity shows the memories and projects that mention it."
        actions={
          <>
            <button type="button" className="btn bg" onClick={reload} disabled={loading}>
              <Icon.Refresh size={15} />
              Refresh
            </button>
            <a className="btn bs" href={buildHash('/memories', { view: 'graph' })}>
              Open graph
            </a>
          </>
        }
        tabs={
          <Tabs
            label="Entity type"
            value={selectedTab}
            onChange={(value) => setParams({ type: value === 'all' ? undefined : value, page: undefined })}
            tabs={ENTITY_TYPES.map((item) => ({ value: item.value, label: item.label, count: data?.counts[item.value] ?? null }))}
          />
        }
      />
      <div className="body">
        <section className="card" style={{ padding: '16px 20px' }}>
          <form onSubmit={applyFilters} style={{ display: 'flex', gap: 10, alignItems: 'end', flexWrap: 'wrap' }}>
            <div className="f grow">
              <label htmlFor="entity-filter">Search entities</label>
              <input id="entity-filter" className="in" placeholder="Name or alias" value={filter} onChange={(event) => setFilter(event.target.value)} />
            </div>
            <div className="f grow">
              <label htmlFor="entity-project">Project</label>
              <input id="entity-project" className="in" placeholder="Project ID" value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)} />
            </div>
            <button type="submit" className="btn bp">
              Apply filters
            </button>
            <button type="button" className="btn bl" disabled={!query && !project} onClick={clearFilters}>
              Clear
            </button>
          </form>
        </section>

        <section className="card" style={{ padding: 0 }}>
          {error && !data ? (
            <ErrorState error={error} onRetry={reload} />
          ) : loading && !data ? (
            <SkTable rows={7} cols={5} />
          ) : items.length === 0 ? (
            <Empty compact title={query || project ? 'No entities match these filters' : 'No entities yet'}>
              {query || project ? 'Try a broader search or clear the project filter.' : 'Entities appear as the memory service extracts people, organizations, places, objects and events from memories.'}
            </Empty>
          ) : (
            <>
              <div className="scroll">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Entity</th>
                      <th>Type</th>
                      <th>Memories</th>
                      <th>Projects</th>
                      <th>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((entity) => {
                      const type = ENTITY_TYPES.find((item) => item.value === entity.entity_type);
                      return (
                        <tr key={entity.id}>
                          <td>
                            <a href={buildHash(`/entity/${entity.id}`)} className="link-plain" style={{ fontWeight: 600 }}>
                              {entity.name}
                            </a>
                            <div className="sm muted mono">{shortId(entity.id, 'ent')}</div>
                            {entity.aliases.length > 0 && <div className="sm muted">Also known as {entity.aliases.join(', ')}</div>}
                          </td>
                          <td>
                            <span className={`lbl ${type?.cls ?? 'g'}`}>{type?.label ?? entity.entity_type}</span>
                          </td>
                          <td>
                            <a href={buildHash('/memories', { entity: entity.id, entityName: entity.name })}>{fmtInt(entity.memory_count)}</a>
                          </td>
                          <td>
                            {entity.projects.length > 0 ? (
                              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                                {entity.projects.map((name) => (
                                  <a key={name} className="tag link-plain" href={buildHash('/memories', { project: name })}>
                                    {name}
                                  </a>
                                ))}
                              </div>
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                          <td className="sm muted">{fmtRelative(entity.last_seen || entity.created_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Pager
                page={data?.page ?? page}
                perPage={data?.per_page ?? perPage}
                total={data?.total ?? 0}
                noun="entities"
                onPage={(next) => setParams({ page: String(next) })}
                onPerPage={(next) => setParams({ per: String(next), page: undefined })}
              />
            </>
          )}
        </section>
      </div>
    </>
  );
};

export default Entities;
