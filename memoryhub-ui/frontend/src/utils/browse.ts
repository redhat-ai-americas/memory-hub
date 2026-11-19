import type { BrowseParams } from '@/types';

/** One URL filter contract for the Memory browser: the table, graph, timeline and export send the same filters. */
export function browseParams(p: URLSearchParams): BrowseParams {
  const list = (key: string) => (p.get(key) || '').split(',').filter(Boolean);
  const q = p.get('q') || undefined;
  return {
    tab: p.get('tab') || 'current',
    q,
    // Semantic by default; the BFF falls back to text (and says so) without an embedding service.
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
    // Relevance only means something with a search; without one it falls back to last update.
    sort: p.get('sort') && (p.get('sort') !== 'relevance' || q) ? p.get('sort')! : q ? 'relevance' : 'updated',
    order: 'desc',
    page: Number(p.get('page') || 1),
    per_page: Number(p.get('per') || 20),
  };
}
