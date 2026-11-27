import type { BrowseParams } from '@/types';

/** GET /api/memories/browse parameters from the Memory browser URL (the graph view reuses scope, writer and weight). */
export function browseParams(p: URLSearchParams): BrowseParams {
  const list = (key: string) => (p.get(key) || '').split(',').filter(Boolean);
  const q = p.get('q') || undefined;
  return {
    tab: p.get('tab') || 'current',
    q,
    // The BFF matches text (or ID / owner with mode=metadata); it has no semantic browse.
    mode: p.get('mode') || 'text',
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
    // Browse has no relevance ranking in the BFF; old 'relevance' links sort by last update.
    sort: p.get('sort') && p.get('sort') !== 'relevance' ? p.get('sort')! : 'updated',
    order: 'desc',
    page: Number(p.get('page') || 1),
    per_page: Number(p.get('per') || 20),
  };
}
