import type { Page, Route } from '@playwright/test';

/**
 * Mocks the dashboard BFF (memoryhub-ui/backend: routes.py + human_adapters.py)
 * with responses shaped like its schemas. Every route the BFF serves is listed
 * in BFF_ROUTES; a request to anything else is recorded in `unknown` and
 * answered 404, so tests can assert the UI never calls an endpoint the
 * backend does not have.
 */
export const BFF_ROUTES: [string, RegExp][] = [
  ['POST', /^\/api\/auth\/logout$/],
  ['GET', /^\/api\/auth\/status$/],
  ['GET', /^\/api\/clients$/],
  ['POST', /^\/api\/clients$/],
  ['PATCH', /^\/api\/clients\/[^/]+$/],
  ['POST', /^\/api\/clients\/[^/]+\/rotate-api-key$/],
  ['POST', /^\/api\/clients\/[^/]+\/rotate-secret$/],
  ['GET', /^\/api\/contradictions$/],
  ['GET', /^\/api\/contradictions\/stats$/],
  ['PATCH', /^\/api\/contradictions\/[^/]+$/],
  ['GET', /^\/api\/entities$/],
  ['GET', /^\/api\/entities\/[^/]+$/],
  ['PATCH', /^\/api\/entities\/[^/]+$/],
  ['POST', /^\/api\/entities\/[^/]+\/merge$/],
  ['GET', /^\/api\/graph$/],
  ['GET', /^\/api\/graph\/all$/],
  ['GET', /^\/api\/graph\/neighbourhood$/],
  ['GET', /^\/api\/graph\/search$/],
  ['POST', /^\/api\/search$/],
  ['GET', /^\/api\/search\/health$/],
  ['GET', /^\/api\/memories\/export$/],
  ['GET', /^\/api\/memory\/[^/]+\/context$/],
  ['GET', /^\/api\/me$/],
  ['POST', /^\/api\/memories$/],
  ['GET', /^\/api\/memories\/browse$/],
  ['POST', /^\/api\/memories\/bulk$/],
  ['DELETE', /^\/api\/memory\/[^/]+$/],
  ['GET', /^\/api\/memory\/[^/]+$/],
  ['POST', /^\/api\/memory\/[^/]+\/branches$/],
  ['POST', /^\/api\/memory\/[^/]+\/contradictions$/],
  ['GET', /^\/api\/memory\/[^/]+\/history$/],
  ['POST', /^\/api\/memory\/[^/]+\/versions$/],
  ['GET', /^\/api\/nav-counts$/],
  ['GET', /^\/api\/nav-features$/],
  ['GET', /^\/api\/projects$/],
  ['POST', /^\/api\/projects$/],
  ['GET', /^\/api\/projects\/[^/]+$/],
  ['POST', /^\/api\/projects\/[^/]+\/members$/],
  ['DELETE', /^\/api\/projects\/[^/]+\/members\/[^/]+$/],
  ['GET', /^\/api\/public-config$/],
  ['POST', /^\/api\/relationships$/],
  ['GET', /^\/api\/rules$/],
  ['POST', /^\/api\/rules$/],
  ['DELETE', /^\/api\/rules\/[^/]+$/],
  ['GET', /^\/api\/rules\/[^/]+$/],
  ['PATCH', /^\/api\/rules\/[^/]+$/],
  // GET /api/rules/{id}/history exists but answers only a local technical caller
  // with the service key (403 for every person), so the dashboard must not call it.
  ['GET', /^\/api\/stats$/],
  ['GET', /^\/api\/users$/],
];

const now = '2026-11-18T12:00:00.000Z';
export const memoryId = '11111111-1111-4111-8111-111111111111';
export const otherMemoryId = '22222222-2222-4222-8222-222222222222';
export const branchId = '44444444-4444-4444-8444-444444444444';
export const entityId = '33333333-3333-4333-8333-333333333333';
export const reportId = '55555555-5555-4555-8555-555555555555';

export type Role = 'user' | 'admin';

const me = (role: Role) => ({
  username: role === 'admin' ? 'dosei' : 'mchen',
  name: role === 'admin' ? 'dosei' : 'mchen',
  email: null,
  initials: role === 'admin' ? 'DO' : 'MC',
  source: 'oauth-proxy',
  role,
  tenant_id: 'lumen-eng',
  write:
    role === 'admin'
      ? { scopes: ['project', 'organizational'], project_ids: ['atlas-planner'], campaign_ids: [], owner_id: 'dosei' }
      : { scopes: ['user', 'project'], project_ids: ['atlas-planner'], campaign_ids: [], owner_id: 'mchen' },
  access: role === 'admin' ? { hidden_scopes: ['enterprise', 'user'], break_glass: null } : null,
  labs: false,
});

const record = (id: string, stub: string, extra: Record<string, unknown> = {}) => ({
  id,
  content: `${stub}. Full text.`,
  stub,
  scope: 'project',
  weight: 0.8,
  branch_type: null,
  owner_id: 'atlas-planner',
  version: 2,
  is_current: true,
  parent_id: null,
  metadata: null,
  created_at: now,
  updated_at: now,
  expires_at: null,
  children_count: 1,
  relationships: [{ id: 'rel-1', source: memoryId, target: otherMemoryId, type: 'related_to' }],
  ...extra,
});

const row = (id: string, stub: string) => ({
  id,
  stub,
  content_preview: `${stub}. Full text.`,
  scope: 'project',
  scope_id: 'atlas-planner',
  owner_id: 'atlas-planner',
  actor_id: 'claude-code-mchen',
  driver_id: 'mchen',
  domains: ['robotics'],
  weight: 0.8,
  version: 2,
  is_current: true,
  status: 'active',
  content_type: 'text',
  branch_count: 1,
  branch_summary: [{ type: 'rationale', count: 1 }],
  open_contradictions: id === memoryId ? 1 : 0,
  near_duplicate: null,
  created_at: now,
  updated_at: now,
  deleted_at: null,
  relevant_until: '2027-02-16T12:00:00.000Z',
  score: null,
  entities: [],
  redacted: false,
  capabilities: { write: true, moderate: true },
  can_delete: true,
});

const graphNode = (id: string, stub: string, extra: Record<string, unknown> = {}) => ({
  id,
  content: `${stub}. Full text.`,
  stub,
  scope: 'project',
  weight: 0.8,
  branch_type: null,
  owner_id: 'atlas-planner',
  version: 2,
  created_at: now,
  updated_at: now,
  metadata: null,
  parent_id: null,
  ...extra,
});

const client = (id: string, type: 'user' | 'service', active = true, owned = false) => ({
  client_id: id,
  client_name: id,
  identity_type: type,
  tenant_id: 'lumen-eng',
  default_scopes: type === 'user' ? ['memory:read', 'memory:write:user'] : ['memory:read:project'],
  active,
  created_at: now,
  updated_at: now,
  owned,
});

const rule = (id: string, layer: string, owner: string | null) => ({
  id,
  name: `${layer} rule`,
  description: 'Blocks API tokens',
  trigger: 'on_write',
  tier: 'regex',
  config: { pattern: 'ghp_[A-Za-z0-9]{20,}' },
  action: 'quarantine',
  scope_filter: null,
  layer,
  owner_id: owner,
  override: false,
  enabled: true,
  priority: 10,
  version: 2,
  is_current: true,
  previous_version_id: null,
  edited_by: owner ?? 'dosei',
  created_at: now,
  updated_at: now,
});

const projectRow = {
  name: 'atlas-planner',
  description: 'Motion planning for the Atlas arm',
  invite_only: true,
  created_at: now,
  created_by: 'dosei',
  memories: 640,
  last_write: now,
  members: 3,
  campaigns: [],
  my_role: 'admin',
  owner: 'dosei',
};

const brief = (id: string, stub: string) => ({
  id,
  stub,
  scope: 'project',
  scope_id: 'atlas-planner',
  owner_id: 'atlas-planner',
  weight: 0.8,
  version: 2,
  is_current: true,
  status: 'active',
  created_at: now,
  updated_at: now,
});

const context = (role: Role) => ({
  memory: {
    ...brief(memoryId, 'Gripper torque limit is 11.5 N·m'),
    redacted: false,
    capabilities: { write: true, moderate: role === 'admin' },
    can_delete: true,
    content: 'Gripper torque limit is 11.5 N·m. Full text.',
    logical_id: null,
    parent_id: null,
    branch_type: null,
    actor_id: 'claude-code-mchen',
    driver_id: 'mchen',
    tenant_id: 'lumen-eng',
    domains: ['robotics'],
    content_type: 'text',
    source: null,
    metadata: null,
    upstream_trust_level: null,
    relevant_until: null,
    deleted_at: null,
    expires_at: null,
    embedding_dims: 384,
    injection: 'full',
    full_content_threshold: 0.8,
  },
  versions: [
    { id: memoryId, version: 2, is_current: true, content: 'Gripper torque limit is 11.5 N·m.', weight: 0.8, actor_id: 'claude-code-mchen', driver_id: 'mchen', owner_id: 'atlas-planner', created_at: now, deleted_at: null },
    { id: 'v1', version: 1, is_current: false, content: 'Gripper torque limit is 10 N·m.', weight: 0.7, actor_id: 'claude-code-mchen', driver_id: 'mchen', owner_id: 'atlas-planner', created_at: now, deleted_at: null },
  ],
  branches: [{ id: branchId, branch_type: 'rationale', content: 'Measured in the soak test', actor_id: 'mchen', created_at: now }],
  relationships: [{ id: 'rel-1', type: 'related_to', direction: 'out', created_by: 'mchen', created_at: now, other: brief(otherMemoryId, 'Path planner budget is 40 ms') }],
  relationships_omitted: 0,
  contradictions: [{ id: reportId, observed_behavior: 'Torque limit is now 12 N·m', confidence: 0.9, reporter: 'curator-agent', created_at: now, resolved: false }],
  contradiction_threshold: 5,
  similar: [{ ...brief(otherMemoryId, 'Path planner budget is 40 ms'), score: 0.71 }],
  access_count: 0,
});

const graphAll = {
  nodes: [
    { ...brief(memoryId, 'Gripper torque limit is 11.5 N·m'), depth: 0, degree: 1 },
    { ...brief(otherMemoryId, 'Path planner budget is 40 ms'), depth: 0, degree: 1 },
  ],
  edges: [{ id: 'rel-1', source: memoryId, target: otherMemoryId, type: 'related_to' }],
  total: 2,
  truncated: false,
  left_out: 0,
  max_nodes: 300,
  limit_ceiling: 1500,
  prefer: 'connected',
  orphan_count: 0,
  hidden_links: 0,
  metadata_only: false,
};

const searchResponse = (role: Role) => ({
  run_as: me(role).username,
  retrieval: 'vector',
  rerank: 'not_configured',
  stages: [{ name: 'Core search', ms: 12.5, detail: 'Human scope applied before retrieval and verified per result' }],
  total_ms: 12.5,
  candidates: 2,
  omitted_count: 0,
  weight_filtered: 0,
  returned: 2,
  full_count: 1,
  stub_count: 1,
  tokens: 40,
  results: [
    { rank: 1, id: memoryId, scope: 'project', scope_id: 'atlas-planner', owner_id: 'atlas-planner', stub: 'Gripper torque limit is 11.5 N·m', content: 'Gripper torque limit is 11.5 N·m. Full text.', delivery: 'full', weight: 0.9, version: 2, relevant_until: null, temporal_status: 'current', historical: false, scores: { vector: null, text: null, focus: null, rrf: 0.82, rerank: null, weight: 0.9 }, tokens: 30 },
    { rank: 2, id: otherMemoryId, scope: 'project', scope_id: 'atlas-planner', owner_id: 'atlas-planner', stub: 'Path planner budget is 40 ms', content: null, delivery: 'stub', weight: 0.6, version: 1, relevant_until: null, temporal_status: 'current', historical: false, scores: { vector: null, text: null, focus: null, rrf: 0.61, rerank: null, weight: 0.6 }, tokens: 10 },
  ],
  assembled_context: 'Gripper torque limit is 11.5 N·m. Full text.\n\nPath planner budget is 40 ms',
  explain: [],
});

function respond(role: Role, method: string, path: string, url: URL, body: unknown): unknown {
  const user = role === 'user';
  if (/\/api\/memory\/[^/]+\/context$/.test(path)) return context(role);
  if (path === '/api/me') return me(role);
  if (path === '/api/auth/status')
    return { mode: 'oauth-proxy', authenticated: true, api_key_login: false, local_accounts: false, user: me(role).username, role, cluster_domain: null, setup_required: false };
  if (path === '/api/auth/logout') return { ok: true, redirect: '/oauth/sign_out', method: 'GET' };
  if (path === '/api/nav-counts') return { memories: 40, review_queue: user ? 0 : 1 };
  if (path === '/api/nav-features') return {};
  if (path === '/api/public-config') return { mcp_url: 'https://mcp.test/mcp/', auth_url: 'https://auth.test' };
  if (path === '/api/stats')
    return {
      total_memories: 40,
      scope_counts: [{ scope: 'project', count: 28 }, { scope: 'organizational', count: 5 }, ...(user ? [{ scope: 'user', count: 7 }] : [])],
      recent_activity: [{ id: memoryId, stub: 'Gripper torque limit is 11.5 N·m', scope: 'project', owner_id: 'atlas-planner', updated_at: now, action: 'updated' }],
      mcp_health: true,
    };
  if (path === '/api/contradictions/stats') return { total: 2, unresolved: 1, high_confidence: 1, medium_confidence: 1, low_confidence: 0 };
  if (path === '/api/contradictions')
    return [
      {
        id: reportId,
        memory_id: memoryId,
        observed_behavior: 'Torque limit is now 12 N·m',
        confidence: 0.9,
        reporter: 'curator-agent',
        created_at: now,
        resolved: url.searchParams.get('resolved') === 'true',
        resolved_at: null,
      },
    ];
  if (path.startsWith('/api/contradictions/'))
    return { id: reportId, memory_id: memoryId, observed_behavior: 'Torque limit is now 12 N·m', confidence: 0.9, reporter: 'curator-agent', created_at: now, resolved: true, resolved_at: now };
  if (path === '/api/memories/browse')
    return {
      items: [row(memoryId, 'Gripper torque limit is 11.5 N·m'), row(otherMemoryId, 'Path planner budget is 40 ms')],
      total: 2,
      page: 1,
      per_page: 20,
      search_mode: url.searchParams.get('q') ? 'text' : 'none',
      metadata_only: !user,
      hidden_scopes: user ? [] : ['user', 'enterprise'],
      tab_counts: { current: 2, all: 3, quarantined: user ? 0 : 1, deleted: 0 },
      facets: {
        scopes: [{ value: 'project', count: 2 }],
        writers: [{ value: 'atlas-planner', count: 2 }],
        projects: [{ value: 'atlas-planner', count: 2 }],
        domains: [],
        flags: { contradicted: null, has_branches: null, near_duplicate: null },
      },
    };
  if (path === '/api/memories' && method === 'POST') return { id: memoryId };
  if (path === '/api/memories/bulk') return { done: (body as { ids: string[] }).ids, errors: [] };
  if (path === '/api/relationships') return { id: 'rel-2' };
  if (/\/api\/memory\/[^/]+\/history$/.test(path))
    return [
      { id: memoryId, version: 2, is_current: true, stub: 'Gripper torque limit is 11.5 N·m', content: 'Gripper torque limit is 11.5 N·m. Full text.', created_at: now },
      { id: 'v1', version: 1, is_current: false, stub: 'Gripper torque limit is 10 N·m', content: 'Gripper torque limit is 10 N·m.', created_at: now },
    ];
  if (/\/api\/memory\/[^/]+\/versions$/.test(path)) return { id: memoryId, version: 3 };
  if (/\/api\/memory\/[^/]+\/branches$/.test(path)) return { id: branchId };
  if (/\/api\/memory\/[^/]+\/contradictions$/.test(path)) return { unresolved: 2 };
  if (path.startsWith('/api/memory/')) {
    if (method === 'DELETE') return null;
    const id = path.split('/')[3];
    return id === otherMemoryId ? record(otherMemoryId, 'Path planner budget is 40 ms', { relationships: [] }) : record(memoryId, 'Gripper torque limit is 11.5 N·m');
  }
  if (path === '/api/graph')
    return {
      nodes: [
        graphNode(memoryId, 'Gripper torque limit is 11.5 N·m'),
        graphNode(otherMemoryId, 'Path planner budget is 40 ms'),
        graphNode(branchId, 'Measured in the soak test', { branch_type: 'rationale', parent_id: memoryId }),
      ],
      edges: [
        { id: 'rel-1', source: memoryId, target: otherMemoryId, type: 'related_to' },
        { id: `pc-${memoryId}-${branchId}`, source: memoryId, target: branchId, type: 'parent_child' },
      ],
    };
  if (path === '/api/graph/all') return graphAll;
  if (path === '/api/graph/neighbourhood')
    return {
      focus: { ...brief(memoryId, 'Gripper torque limit is 11.5 N·m'), content: 'Gripper torque limit is 11.5 N·m. Full text.', degree: 1, hidden_degree: 0 },
      nodes: graphAll.nodes.map((n, i) => ({ ...n, depth: i })),
      edges: graphAll.edges,
      hidden_count: 0,
      cut_count: 0,
      max_nodes: 300,
      provenance: [],
      conflicts: [],
    };
  if (path === '/api/search') return { ...searchResponse(role), notes: (body as { domains?: string[]; focus?: string })?.domains?.length && !(body as { focus?: string }).focus ? ['Domain and graph boosts apply only with a session focus, as in search_memory.'] : [] };
  if (path === '/api/search/health')
    return { embedding: { status: 'ok', dimensions: 384, ms: 4 }, reranker: { status: 'not_configured' }, search_mode: 'vector', fallback: null };
  if (path === '/api/memories/export') return 'export';
  if (path === '/api/graph/search') return [{ id: memoryId, score: 0.82 }, { id: otherMemoryId, score: 0.61 }];
  if (path === '/api/entities')
    return {
      items: [{ id: entityId, name: 'Atlas gripper', entity_type: 'object', aliases: ['Atlas end effector'], memory_count: 2, projects: ['atlas-planner'], created_at: now, last_seen: now }],
      total: 1,
      page: 1,
      per_page: 20,
      has_more: false,
      counts: { all: 1, person: 0, organization: 0, location: 0, object: 1, event: 0 },
    };
  if (path.endsWith('/merge'))
    return {
      source: { id: entityId, name: 'Atlas gripper', entity_type: 'object', aliases: [] },
      target: { id: 'e2', name: 'Gripper', entity_type: 'object', aliases: [] },
      moving: 1,
      both: 0,
      staying: 0,
      aliases_after: [],
      source_removed: false,
      memories: [],
      dry_run: true,
    };
  if (path.startsWith('/api/entities/')) {
    if (method === 'PATCH') return { id: entityId, name: 'Atlas gripper v2', entity_type: 'object', aliases: [] };
    return {
      id: entityId,
      name: 'Atlas gripper',
      entity_type: 'object',
      aliases: ['Atlas end effector'],
      created_at: now,
      memory_count: 1,
      hidden_mentions: 0,
      first_seen: now,
      last_seen: now,
      scopes: { project: 1 },
      writers: [{ value: 'atlas-planner', count: 1 }],
      projects: [{ value: 'atlas-planner', count: 1 }],
      months: [{ month: '2026-11', count: 1 }],
      co_mentions: [],
      can_edit: true,
      memories: [{ id: memoryId, stub: 'Gripper torque limit is 11.5 N·m', scope: 'project', scope_id: 'atlas-planner', owner_id: 'atlas-planner', weight: 0.8, version: 2, created_at: now, updated_at: now }],
    };
  }
  if (path === '/api/projects' && method === 'GET') return { items: [projectRow], total: 1, viewer: me(role).username, can_create: !user, can_delete: false };
  if (path === '/api/projects' && method === 'POST') return { name: (body as { name: string }).name };
  if (/\/api\/projects\/[^/]+\/members/.test(path)) return method === 'DELETE' ? null : { ok: true };
  if (path.startsWith('/api/projects/'))
    return {
      ...projectRow,
      my_role: user ? 'member' : 'admin',
      can_manage: !user,
      can_delete: false,
      members_list: [
        { user_id: 'dosei', role: 'admin', joined_at: now },
        { user_id: 'mchen', role: 'member', joined_at: now },
        { user_id: 'claude-code-mchen', role: 'member', joined_at: now },
      ],
      focus_history: [{ focus: 'release', count: 3 }],
      focus_available: true,
    };
  if (path === '/api/users')
    return [
      { name: 'claude-code (Maya)', owner_id: 'claude-code-mchen', identity_type: 'user', memory_count: 12, last_active: now },
      ...(user ? [] : [{ name: 'curator-agent', owner_id: 'curator-agent', identity_type: 'service', memory_count: 88, last_active: now }]),
      { name: 'mchen', owner_id: 'mchen', identity_type: 'unknown', memory_count: 7, last_active: now },
    ];
  if (path === '/api/clients' && method === 'GET')
    // A user lists only their own agents; an admin every client, owning only curator-agent.
    return user
      ? [client('claude-code-mchen', 'user', true, true)]
      : [client('claude-code-mchen', 'user'), client('curator-agent', 'service', true, true), client('other-svc', 'service'), client('old-bot', 'service', false)];
  if (path === '/api/clients' && method === 'POST')
    return { ...client((body as { client_id: string }).client_id, user ? 'user' : 'service', true, true), client_secret: 'sec_123', api_key: 'mh_123' };
  if (path.endsWith('/rotate-secret')) return { client_id: 'claude-code-mchen', client_secret: 'sec_456', api_key: 'mh_456' };
  if (path.endsWith('/rotate-api-key')) return { client_id: 'claude-code-mchen', api_key: 'mh_789' };
  if (path.startsWith('/api/clients/')) return client(path.split('/')[3], 'user', (body as { active?: boolean } | undefined)?.active ?? true);
  if (path === '/api/rules' && method === 'GET') return [rule('rule-sys', 'system', null), rule('rule-org', 'organizational', null), rule('rule-mine', 'user', 'mchen')];
  if (path.startsWith('/api/rules')) return method === 'DELETE' ? null : rule('rule-new', 'user', 'mchen');
  return {};
}

export interface MockedBff {
  /** "METHOD /path" for every call to an endpoint the BFF does not serve. */
  unknown: string[];
  /** "METHOD /path" for every call. */
  calls: string[];
}

/** Optional per-test change to a canned answer, keyed by "METHOD /path". */
export type Tweak = (key: string, payload: unknown) => unknown;

export async function mockBff(page: Page, role: Role, tweak?: Tweak): Promise<MockedBff> {
  const state: MockedBff = { unknown: [], calls: [] };
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    // Source modules such as /src/api/client.ts match the glob too: only the BFF lives under /api/.
    if (!url.pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }
    const method = request.method();
    const key = `${method} ${url.pathname}`;
    state.calls.push(key);
    if (!BFF_ROUTES.some(([m, re]) => m === method && re.test(url.pathname))) {
      state.unknown.push(key);
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not Found' }) });
      return;
    }
    let body: unknown;
    try {
      body = request.postDataJSON();
    } catch {
      body = undefined;
    }
    const answer = respond(role, method, url.pathname, url, body);
    const payload = tweak ? tweak(key, answer) : answer;
    if (payload === null) {
      await route.fulfill({ status: 204 });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  return state;
}
