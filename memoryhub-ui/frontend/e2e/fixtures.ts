import type { Page, Route } from '@playwright/test';

const now = '2026-10-19T12:00:00.000Z';
const memoryId = '11111111-1111-4111-8111-111111111111';
const otherMemoryId = '22222222-2222-4222-8222-222222222222';
const entityId = '33333333-3333-4333-8333-333333333333';
// range -> [bucket count, bucket seconds], mirroring ACTIVITY_RANGES in routes_dashboard.py.
const activityBuckets: Record<string, [number, number]> = {
  all: [14, 86400],
  '1h': [12, 300],
  '12h': [24, 1800],
  '1d': [24, 3600],
  '7d': [7, 86400],
  '30d': [30, 86400],
};
const activityFor = (range: string) => {
  const [count, bucket] = activityBuckets[range] ?? activityBuckets['7d'];
  const end = Date.parse(now);
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Math.floor((end - (count - 1 - index) * bucket * 1000) / (bucket * 1000)) * bucket * 1000).toISOString();
    const last = index === count - 1;
    return { date, searches: last ? 2 : 0, writes: last ? 1 : 0 };
  });
};

const node = (id: string, stub: string, depth: number) => ({
  id,
  stub,
  scope: 'project',
  scope_id: 'memoryhub-ui',
  owner_id: 'admin',
  weight: 0.8,
  version: 1,
  is_current: true,
  status: 'active',
  created_at: now,
  updated_at: now,
  depth,
});

const settings = {
  values: {
    retrieval: {
      max_results: 10,
      max_response_tokens: 4000,
      session_focus_weight: 0.4,
      full_content_threshold: 0.8,
      rerank: true,
      cache_optimized_ordering: true,
      realtime_push: true,
    },
    governance: { project_isolation: true, role_isolation: true, contradiction_threshold: 3, enterprise_approvers: 2 },
    audit: { read_detail: 'full', full_retention_days: 30, mcp_profile: 'full' },
  },
  meta: { updated_at: now, updated_by: 'admin', persisted: true },
  models: {
    embedding: { name: 'Embedding', status: 'healthy', detail: 'ready', latency_ms: 12, url: 'http://embedding.test/embed' },
    reranker: { name: 'Reranker', status: 'healthy', detail: 'ready', latency_ms: 18, url: 'http://reranker.test/rerank' },
  },
  mcp: { name: 'MCP', status: 'healthy', detail: 'ready', latency_ms: 4, public_url: 'https://mcp.test', internal_url: 'http://mcp.test' },
  tenant: { tenant_id: 'demo-tenant', auth_url: 'https://auth.test', cluster_domain: 'cluster.test' },
};

const commonMemory = {
  id: memoryId,
  stub: 'Run the MemoryHub UI locally with npm run dev',
  content_preview: 'Run the MemoryHub UI locally with npm run dev.',
  scope: 'project',
  scope_id: 'memoryhub-ui',
  owner_id: 'admin',
  actor_id: 'admin',
  driver_id: 'dashboard',
  domains: ['tooling', 'containers'],
  weight: 0.8,
  version: 1,
  is_current: true,
  status: 'active',
  content_type: 'text',
  branch_count: 0,
  branch_summary: [],
  open_contradictions: 0,
  near_duplicate: null,
  created_at: now,
  updated_at: now,
  deleted_at: null,
  score: null,
};

const overview = {
  tenant_id: 'demo-tenant',
  generated_at: now,
  memories: { current: 1, new_7d: 1, growth_pct: null },
  agents: { total: 1, active_now: 1, source: 'auth' },
  searches: { last_24h: 2, p95_latency_ms: 42 },
  contradictions: { open: 0, over_threshold: 0, threshold: 3 },
  approvals: { enterprise_pending: 0, pending_total: 0 },
  scopes: ['user', 'project', 'campaign', 'role', 'organizational', 'enterprise'].map((scope) => ({ scope, count: scope === 'project' ? 1 : 0, pending: 0 })),
  categories: [{ name: 'tooling', memory_count: 1 }, { name: 'containers', memory_count: 1 }],
  activity: activityFor('7d'),
  activity_range: '7d',
  activity_bucket_seconds: 86400,
  activity_source: 'memory',
  recent: [],
  recent_source: 'memory',
  health: [{ key: 'db', name: 'Database', status: 'healthy', detail: 'Ready', latency_ms: 4 }],
  context_assembly: { avg_tokens: 128, prefix_hit_rate: 0.5 },
};

const identity = {
  id: 'admin',
  name: 'Admin',
  type: 'user',
  scopes: ['memory:admin'],
  client: false,
  active: true,
  public: false,
  created_at: now,
  bound_to: null,
  roles: ['admin'],
  memory_count: 1,
  last_active: now,
  active_now: true,
};

const client = {
  client_id: 'demo-agent',
  client_name: 'Demo agent',
  identity_type: 'service',
  tenant_id: 'demo-tenant',
  default_scopes: ['memory:read', 'memory:write:user'],
  active: true,
  public: false,
  grant: 'client_credentials',
  last_used: now,
  status: 'active',
  created_at: now,
  updated_at: now,
};

const entities = {
  items: [{ id: entityId, name: 'MemoryHub UI', entity_type: 'object', aliases: ['memoryhub-ui'], memory_count: 1, projects: ['memoryhub-ui'], created_at: now, last_seen: now }],
  total: 1,
  page: 1,
  per_page: 20,
  has_more: false,
  counts: { all: 1, person: 0, organization: 0, location: 0, object: 1, event: 0 },
};

const respond = async (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

/**
 * Deterministic API fixture for UI smoke tests. It deliberately exercises the
 * real React screens while keeping tests independent from tenant data and auth.
 */
const verifyResult = {
  id: 'v1',
  created_at: now,
  schema: 'memoryhub.verify/v1',
  source: 'dashboard',
  produced_by: { tool: 'memoryhub-ui', check: 'dashboard', profile_version: null },
  started_at: now,
  finished_at: now,
  context: { endpoint: 'https://mcp.test/mcp/', tenant: 'demo-tenant', identity: 'admin', projects: [] },
  checks: [
    { id: 'endpoint', title: 'MCP endpoint', status: 'pass', category: null, category_label: null, code: 'endpoint.ok', explanation: 'The MCP server answers (12 ms).', next_action: null, source: 'dashboard', duration_ms: 12 },
    { id: 'tool_discovery', title: 'Tool discovery', status: 'not_run', category: null, category_label: null, code: null, explanation: 'Only on the agent host.', next_action: 'Run the connection check on the agent host.', source: 'host', duration_ms: null },
    { id: 'project', title: 'Project', status: 'warn', category: 'wrong_project', category_label: 'Wrong project', code: 'project.none', explanation: 'You are not a member of any project.', next_action: 'Join a project in Projects & teams.', source: 'dashboard', duration_ms: null },
    { id: 'round_trip', title: 'Write and read back', status: 'fail', category: 'service_unavailable', category_label: 'Service unavailable', code: 'round_trip.embeddings_unavailable', explanation: 'Writing a test memory failed.', next_action: 'Tell your platform operator.', source: 'dashboard', duration_ms: 30 },
  ],
  summary: { pass: 1, warn: 1, fail: 1, not_run: 1, state: 'fail' },
};

const behavior = (template: string, extra: Record<string, unknown> = {}) => ({
  schema: 'memoryhub.profile/v1', revision: 1, template, include: ['preferences', 'project_decisions', 'procedures', 'facts'], exclude: ['credentials', 'personal_data'],
  custom_exclude: [], confirmation: 'sensitive', cadence: 'session_end', update: 'supersede', updated_at: null, ...extra,
});

const prefs = {
  prefs: { write: { default_scope: 'user', default_weight: 0.7 }, privacy: { allow_promotion_by_others: false, show_in_team_directory: true }, dreaming_fade_days: 60, behavior: behavior('balanced'), behavior_history: [] },
  profile: {
    schema: 'memoryhub.profile/v1',
    templates: {
      balanced: behavior('balanced'),
      conservative: behavior('conservative', { include: ['preferences', 'project_decisions'], exclude: ['credentials', 'personal_data', 'health', 'customer_data'], confirmation: 'always', cadence: 'explicit', update: 'ask' }),
      proactive: behavior('proactive', { exclude: ['credentials'], confirmation: 'never', cadence: 'every_turn' }),
    },
    categories: ['preferences', 'project_decisions', 'procedures', 'facts'],
    excludes: ['credentials', 'personal_data', 'health', 'customer_data'],
    choices: { confirmation: ['always', 'sensitive', 'never'], cadence: ['every_turn', 'session_end', 'explicit'], update: ['supersede', 'branch', 'ask'] },
    applied_by: [],
  },
  account: { username: 'admin', name: 'Admin User', email: null, role: 'operator', source: 'api-key', agents: [], projects: ['memoryhub-ui'], roles: [], own_memories: 1 },
};

export interface MockOptions {
  labs?: boolean;
  role?: 'operator' | 'user' | 'admin' | 'superuser';
  grant?: boolean;
}

export async function mockDashboardApi(page: Page, opts: MockOptions = {}) {
  const { labs = true, role, grant = false } = opts;
  const activeGrant = { id: 'g1', username: 'admin', incident_ref: 'INC-1234', justification: 'Spill of a customer contract into a user memory', created_at: now, expires_at: '2026-12-31T12:00:00.000Z', ended_at: null, active: true, reads: 3, owners: 1 };
  const access = role === 'admin' || role === 'superuser' ? { hidden_scopes: grant ? [] : ['user'], break_glass: grant ? activeGrant : null } : null;
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.replace(/^\/api/, '');

    if (path === '/auth/status') return respond(route, { mode: 'api-key', authenticated: true, api_key_login: true, user: 'admin', cluster_domain: 'cluster.test' });
    if (path === '/me') return respond(route, { username: 'admin', name: 'Admin User', email: 'admin@example.test', initials: 'AU', source: 'api-key', tenant_id: 'demo-tenant', labs, access, ...(role ? { role } : {}) });
    if (path === '/break-glass' && request.method() === 'GET') return respond(route, { policy: { enabled: true, hours: 24, pattern: '^[A-Za-z][A-Za-z0-9]{1,15}-[0-9]{1,10}$', notify_owner: true }, active: grant ? activeGrant : null, grants: grant ? [activeGrant] : [] });
    if (path === '/break-glass' && request.method() === 'POST') return respond(route, activeGrant, 201);
    if (path === '/break-glass/end') return respond(route, { ended: 'g1' });
    if (path === '/break-glass/report') return respond(route, { month: '2026-10', grants: [activeGrant], accesses: [{ actor: 'admin', incident_ref: 'INC-1234', owner: 'ann', reads: 3, first: now, last: now }], totals: { grants: 1, reads: 3, owners: 1 } });
    if (path === '/me/prefs' && request.method() === 'GET') return respond(route, prefs);
    if (path === '/me/prefs' && request.method() === 'PUT') {
      const body = JSON.parse(request.postData() || '{}');
      return respond(route, { prefs: { ...prefs.prefs, ...body, behavior: { ...prefs.prefs.behavior, ...(body.behavior ?? {}), revision: 2 } } });
    }
    if (path === '/verify') return respond(route, { schema: 'memoryhub.verify/v1', checks: [], categories: [{ id: 'wrong_project', label: 'Wrong project' }, { id: 'service_unavailable', label: 'Service unavailable' }], host_command: null, results: [] });
    if (path === '/verify/run') return respond(route, verifyResult, 201);
    if (path === '/verify/results') return respond(route, { ...verifyResult, id: 'v2', source: 'host', produced_by: { tool: 'memoryhub', version: '0.9', host: 'claude-code' } }, 201);
    if (path === '/connect') return respond(route, { mcp_url: 'https://mcp.test/mcp/', auth_url: 'https://auth.test', tenant: 'demo-tenant', agents: [], projects: ['memoryhub-ui'] });
    if (path === '/nav-counts') return respond(route, { review_queue: 0, memories: 1 });
    if (path === '/overview') {
      const range = url.searchParams.get('range') ?? '7d';
      const bucket = (activityBuckets[range] ?? activityBuckets['7d'])[1];
      return respond(route, { ...overview, activity: activityFor(range), activity_range: range, activity_bucket_seconds: bucket });
    }
    if (path === '/entities') return respond(route, entities);
    if (path === '/settings') return respond(route, settings);
    if (path === '/public-config') return respond(route, { mcp_url: 'https://mcp.test', auth_url: 'https://auth.test' });
    if (path === '/identities') return respond(route, { items: [identity], auth_available: true, roles: [{ name: 'admin', members: 1 }], counts: { all: 1, users: 1, user_agents: 0, service_agents: 0, roles: 1 } });
    if (path.startsWith('/identities/')) return respond(route, { ...identity, grant: 'password', scope_matrix: [], activity_24h: { searches: 1, writes: 1, denied: 0, total: 2 }, hourly: [], agents: [] });
    if (path === '/memories/browse') return respond(route, { items: [commonMemory], total: 1, page: 1, per_page: 20, search_mode: 'none', tab_counts: { current: 1, all: 1, quarantined: 0, deleted: 0 }, facets: { scopes: ['user', 'project', 'campaign', 'role', 'organizational', 'enterprise'].map((value) => ({ value, count: value === 'project' ? 1 : 0 })), writers: [{ value: 'admin', count: 1 }], projects: [{ value: 'memoryhub-ui', count: 1 }], domains: [{ value: 'tooling', count: 1 }], flags: { contradicted: 0, has_branches: 0, near_duplicate: null } } });
    if (path === '/graph/all') return respond(route, { nodes: [{ ...node(memoryId, 'Run the MemoryHub UI locally with npm run dev', 0), degree: 1 }, { ...node(otherMemoryId, 'The UI is served on port 3000', 0), degree: 1 }], edges: [{ id: 'rel-1', source: memoryId, target: otherMemoryId, type: 'related_to' }], total: 2, truncated: false, orphan_count: 0, hidden_links: 0, metadata_only: false });
    if (path === '/memories/timeline')
      return respond(route, {
        items: [
          { ...node(memoryId, 'Run the MemoryHub UI locally with npm run dev', 0), domains: ['tooling'], at: now },
          { ...node(otherMemoryId, 'The UI is served on port 3000', 0), domains: [], created_at: '2026-10-01T12:00:00.000Z', at: '2026-10-01T12:00:00.000Z' },
        ],
        total: 2,
        truncated: false,
        by: 'created',
        days: 90,
        first: '2026-10-01T12:00:00.000Z',
        now,
        metadata_only: false,
      });
    if (path === '/knowledge') return respond(route, { items: [{ kind: 'me', id: 'admin', title: 'What memory knows about Admin User', source_count: 2, generated_at: now, fresh: true, summary: { facts: 2, folded: 0, sections: 1, entities: 1, open_questions: 0, stale: 0 }, sections: ['tooling'] }] });
    if (path.startsWith('/knowledge/me'))
      return respond(route, {
        subject: { kind: 'me', id: 'admin', title: 'What memory knows about Admin User' },
        generated_at: now,
        rebuilt: false,
        truncated: false,
        source_count: 2,
        last_source_change: now,
        summary: { facts: 2, folded: 0, sections: 1, entities: 1, open_questions: 0, stale: 0 },
        highlights: [{ text: 'Run the MemoryHub UI locally with npm run dev', memory_id: memoryId, memory_ids: [memoryId], similar: 0, scope: 'user', weight: 0.8, updated_at: now, stale: false, contradicted: 0 }],
        sections: [{ title: 'tooling', facts: [{ text: 'Run the MemoryHub UI locally with npm run dev', memory_id: memoryId, memory_ids: [memoryId, otherMemoryId], similar: 1, scope: 'user', weight: 0.8, updated_at: now, stale: false, contradicted: 0 }] }],
        entities: [{ id: entityId, name: 'MemoryHub UI', type: 'object', count: 2 }],
        recent: [],
        questions: [],
        stale: [],
        changes: null,
        scopes: { user: 2 },
      });
    if (path === `/entities/${entityId}`)
      return respond(route, {
        id: entityId,
        name: 'MemoryHub UI',
        entity_type: 'object',
        aliases: ['ui'],
        created_at: now,
        memory_count: 1,
        hidden_mentions: 0,
        first_seen: now,
        last_seen: now,
        scopes: { project: 1 },
        writers: [{ value: 'admin', count: 1 }],
        projects: [{ value: 'memoryhub-ui', count: 1 }],
        months: [{ month: '2026-10', count: 1 }],
        co_mentions: [],
        memories: [{ ...node(memoryId, 'Run the MemoryHub UI locally with npm run dev', 0) }],
      });
    if (path === '/nav-features') return respond(route, { knowledge: 2, documents: 1, packs: 1, checks: 1, check_runs: 1, search_runs: 3, jobs: 2 });
    if (path === '/checks')
      return respond(route, {
        checks: [{ id: 'q1', owner: 'admin', name: 'Local dev', request: { query: 'run locally', max_results: 5 }, expected: [memoryId, otherMemoryId], visibility: 'private', project: null, created_at: now, updated_at: now, last_result: null, mine: true, is_check: true }],
        queries: [],
        last: {
          id: 'r1', started_at: now, duration_ms: 20, trigger: 'manual',
          summary: { checks: 1, hit_rate: 1, recall: 0.5, precision: 0.5, mrr: 1, p50_ms: 5, failing: 1 },
          results: [{ query_id: 'q1', name: 'Local dev', query: 'run locally', returned: [memoryId], metrics: { expected: 2, found: 1, hit: true, recall: 0.5, precision: 0.5, mrr: 1, first_rank: 1 }, missing: [{ id: otherMemoryId, found: true, stub: 'The UI is served on port 3000', stage: 'weight', detail: 'Weight 0.30 is below the threshold 0.50.' }], total_ms: 5, funnel: [] }],
        },
        runs: [{ id: 'r1', started_at: now, duration_ms: 20, trigger: 'manual', summary: { checks: 1, recall: 0.5 } }],
      });
    if (path === '/search/health') return respond(route, { days: 7, scope: 'tenant', runs: 3, latency: { p50: 8, p95: 20 }, avg: { matched: 20, returned: 5, tokens: 300 }, cut: { filters: 0, rbac: 0.1, weight: 0.2, limit: 0.4, budget: 0 }, stages: [{ name: 'embed', p50: 2 }], sources: { playground: 3 }, rerank: { on: 3 }, vector_share: 1, empty_share: 0, by_day: [] });
    if (path === '/context-packs') return respond(route, { items: [{ id: 'p1', owner: 'admin', name: 'Local dev pack', description: null, pinned: [memoryId], queries: [{ query: 'containers', max_results: 5, weight_threshold: 0 }], token_budget: 2000, visibility: 'private', project: null, read_only: true, agents: [], created_at: now, updated_at: now, last_render: null, mine: true, can_edit: true }] });
    if (path === '/context-packs/p1')
      return respond(route, {
        id: 'p1', owner: 'admin', name: 'Local dev pack', description: null, pinned: [memoryId], queries: [{ query: 'containers', max_results: 5, weight_threshold: 0 }], token_budget: 2000, visibility: 'private', project: null, read_only: true, agents: [], created_at: now, updated_at: now, last_render: null, mine: true, can_edit: true,
        render: { items: [{ id: memoryId, stub: 'Run the MemoryHub UI locally', scope: 'project', text: 'Run the MemoryHub UI locally with npm run dev', source: 'pinned', tokens: 12, weight: 0.8 }], tokens: 12, budget: 2000, over_budget: [], hidden: 0, missing: 0, markdown: '# Local dev pack', rendered_at: now, as: 'admin' },
        my_agents: ['claude-code'],
      });
    if (path === '/documents') return respond(route, { items: [{ id: 'd1', owner: 'admin', title: 'Dev handbook', mime: 'text/markdown', size: 120, version: 1, project: null, created_at: now, updated_at: now, memories: 1, changed: 0, mine: true }] });
    if (path === '/documents/d1')
      return respond(route, {
        id: 'd1', owner: 'admin', title: 'Dev handbook', mime: 'text/markdown', body: 'Run the UI with npm run dev.\n\nServe it on port 3000.', version: 1, project: null, created_at: now, updated_at: now,
        passages: [{ i: 0, start: 0, end: 28, text: 'Run the UI with npm run dev.', memories: [memoryId] }, { i: 1, start: 30, end: 52, text: 'Serve it on port 3000.', memories: [] }],
        links: [{ memory_id: memoryId, start: 0, end: 28, status: 'ok', doc_version: 1, stub: 'Run the MemoryHub UI locally', scope: 'project', is_current: true }],
        mine: true,
      });
    if (path === '/operations') return respond(route, { items: [{ id: 'j1', owner: 'admin', kind: 'dream', label: 'Dream', status: 'failed', trigger: 'scheduled', started_at: now, finished_at: now, duration_ms: 1200, attempts: 1, correlation_id: 'c1c1c1c1-0000-4000-8000-000000000000', retry_of: null, error: 'database timeout', retryable: true, stale: false, detail: {} }], kinds: [{ kind: 'dream', label: 'Dream', ok: 0, failed: 1, running: 0 }], days: 7, scope: 'tenant' });
    if (path === '/notifications') return respond(route, { items: [{ id: 'rd:1', kind: 'reads', severity: 'info', title: 'Other agents used your memories 2 times today', body: 'See who and which memories.', at: now, href: '/reads', unread: true }], unread: 1, seen_at: null });
    if (path === '/me/onboarding') return respond(route, { steps: [{ id: 'agent', title: 'Link an agent', body: 'Link agents.', href: '/identities', done: true }, { id: 'dream', title: 'Run your first dream', body: 'Dream.', href: '/dreaming', done: false }], done: 1, total: 2, dismissed: false });
    if (path === '/graph/neighbourhood') return respond(route, { focus: { ...node(memoryId, 'Run the MemoryHub UI locally with npm run dev', 0), content: commonMemory.content_preview, degree: 1, hidden_degree: 0 }, nodes: [node(memoryId, commonMemory.stub, 0), node(otherMemoryId, 'The UI is served on port 3000', 1)], edges: [{ id: 'rel-1', source: memoryId, target: otherMemoryId, type: 'related_to' }], hidden_count: 0, provenance: [], conflicts: [] });
    if (path === '/credentials') return respond(route, { auth_available: true, issuer: 'https://auth.test', clients: [client], api_keys: [], issuers: [{ name: 'OpenShift', kind: 'oauth-proxy', description: 'Cluster issuer', status: 'active' }] });
    if (path === '/projects') return respond(route, { items: [{ name: 'memoryhub-ui', description: 'UI project', invite_only: false, created_at: now, created_by: 'admin', memories: 1, last_write: now, members: 1, campaigns: [] }], total: 1, campaign_total: 0, viewer: 'admin' });
    if (path === '/campaigns') return respond(route, { items: [] });
    if (path.startsWith('/projects/')) return respond(route, { name: 'memoryhub-ui', description: 'UI project', invite_only: false, created_at: now, created_by: 'admin', memories: 1, last_write: now, members: 1, campaigns: [], agents_today: 1, members_list: [], focus_history: [], focus_available: true, loading_policy: 'default' });
    if (path === '/rules') return respond(route, []);
    if (path === '/rules/matches') return respond(route, { days: 7, available: true, counts: {} });
    if (path === '/review') return respond(route, { tab: 'approvals', counts: { approvals: 0, promotions: 0, contradictions: 0, quarantine: 0 }, items: [], also_waiting: [], approvers_required: 2, viewer: 'admin' });
    if (path === '/audit') return respond(route, { items: [], total: 0, page: 1, per_page: 50, event_types: [], operations: {}, denied_total: 0, retention_days: 30 });
    if (path === '/audit/forensics') return respond(route, { actor: 'admin', at: now, window_minutes: 60, events: 0, last_search_at: null, context: [], tokens: 0, findings: [] });

    if (request.method() === 'POST' && path === '/memories') return respond(route, { id: otherMemoryId }, 201);
    if (request.method() === 'POST' && path === '/clients') {
      const body = JSON.parse(request.postData() || '{}') as { client_id?: string; client_name?: string };
      return respond(route, { ...client, client_id: body.client_id || client.client_id, client_name: body.client_name || 'Created agent', client_secret: 'secret-for-test', api_key: 'key-for-test' }, 201);
    }
    if (request.method() === 'POST' && path === '/auth/logout') return respond(route, { ok: true });
    if (request.method() === 'POST' && path === '/search') return respond(route, { run_as: 'admin', retrieval: 'text', rerank: 'off', stages: [], total_ms: 1, candidates: 0, omitted_count: 0, weight_filtered: 0, returned: 0, full_count: 0, stub_count: 0, tokens: 0, results: [], assembled_context: '' });
    if (request.method() === 'POST' && path.startsWith('/rules/')) return respond(route, { matched: false, action: 'none', scanned: 1, rules: 0, matches: {} });
    if (request.method() === 'POST' && path.startsWith('/review/')) return respond(route, { id: 'review-1', status: 'approved' });
    if (request.method() === 'POST' && path === '/relationships') return respond(route, { id: 'rel-2' }, 201);
    if (request.method() === 'PUT' && path === '/settings') return respond(route, settings);
    if (request.method() === 'PATCH' || request.method() === 'DELETE') return respond(route, request.method() === 'DELETE' ? null : client);

    return respond(route, {});
  });
}

export { memoryId };
