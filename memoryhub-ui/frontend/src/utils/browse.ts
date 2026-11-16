import type { BrowseParams } from '@/types';

/** The table, graph, timeline and export use the same URL filter contract. */
export function browseParams(p: URLSearchParams): BrowseParams {
  const list = (key: string) => (p.get(key) || '').split(',').filter(Boolean);
  const q = p.get('q') || undefined;
  return {
    tab: p.get('tab') || 'current',
    q,
    mode: p.get('mode') || 'semantic',
    scope: list('scope'),
    actor: list('actor'),
    project: p.get('project') || undefined,
    domain: list('domain'),
    min_weight: p.get('minw') ? Number(p.get('minw')) : undefined,
    max_weight: p.get('maxw') ? Number(p.get('maxw')) : undefined,
    created_from: p.get('from') || undefined,
    created_to: p.get('to') || undefined,
    branch_type: p.get('branch') || undefined,
    flag: list('flag'),
    entity: p.get('entity') || undefined,
    sort: p.get('sort') || (q ? 'relevance' : 'updated'),
    order: 'desc',
    page: Number(p.get('page') || 1),
    per_page: Number(p.get('per') || 20),
  };
}
