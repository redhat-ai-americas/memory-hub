// API types for the MemoryHub dashboard BFF. Every figure on screen comes
// from these responses; nothing is hard-coded in the UI.

export type Scope = 'user' | 'project' | 'campaign' | 'role' | 'organizational' | 'enterprise' | string;

/** admin: manages the platform, sees memory metadata only.
 *  user: owns memories, reads what RBAC allows.
 *  operator: open development mode (no sign-in configured). */
export type Role = 'admin' | 'user' | 'operator';

export interface Me {
  username: string;
  name: string;
  email: string | null;
  initials: string;
  source: 'oauth-proxy' | 'api-key' | 'account' | 'anonymous';
  /** #667 tier. A super-user is a platform admin who can start incident access to user memories. */
  role: Role | 'superuser';
  /** Admins and super-users: what they cannot read, and the active incident grant. */
  access?: { hidden_scopes: string[]; break_glass: BreakGlassGrant | null } | null;
  /** Test mode: who is really signed in while viewing as someone else. */
  real_username?: string | null;
  real_role?: Role | 'superuser' | null;
  test_mode?: boolean;
  /** MemoryHub Labs features beyond Release 1 are on (MEMORYHUB_UI_LABS). */
  labs?: boolean;
  tenant_id: string;
}

export interface SwitchTarget {
  username: string;
  role: Role | 'superuser';
  label: string;
  note: string | null;
}

export interface SwitchTargets {
  enabled: boolean;
  real?: { username: string; role: Role | 'superuser' };
  current?: { username: string; role: Role | 'superuser' };
  targets: SwitchTarget[];
}

export type SignupMode = 'open' | 'domain' | 'invite' | 'closed';

export interface AuthStatus {
  mode: 'oauth-proxy' | 'api-key' | 'accounts' | 'open';
  authenticated: boolean;
  api_key_login: boolean;
  local_accounts: boolean;
  user: string | null;
  role: Role;
  cluster_domain: string | null;
  setup_required: boolean;
  setup_token_required?: boolean;
  accounts_available?: boolean;
  organization?: string | null;
  signup?: { mode: SignupMode; require_approval: boolean; allowed_domains: string[] };
  password_min_length?: number;
}

export interface SetupPayload {
  setup_token?: string;
  organization: { name: string; contact_email: string };
  admin: { username: string; email: string; display_name: string; password: string };
  signup: { mode: SignupMode; allowed_domains: string[]; require_approval: boolean };
  privacy: {
    admin_readable_scopes: string[];
    break_glass: boolean;
    break_glass_hours: number;
    break_glass_approvers: number;
    notify_owner: boolean;
  };
  security: { session_hours: number; password_min_length: number };
}

export interface RegisterPayload {
  username: string;
  email: string;
  display_name: string;
  password: string;
  job_title?: string;
  requested_projects: string[];
  invite_code?: string;
  accept_privacy: boolean;
}

export interface AccountRow {
  id: string;
  username: string;
  email: string;
  display_name: string;
  role: 'admin' | 'user';
  status: 'active' | 'pending' | 'disabled';
  job_title: string | null;
  requested_projects: string[];
  created_at: string;
  last_login_at: string | null;
  approved_by: string | null;
  invited_by: string | null;
}

export interface InviteRow {
  id: string;
  code: string;
  role: 'admin' | 'user';
  email: string | null;
  note: string | null;
  created_by: string;
  created_at: string;
  expires_at: string;
  used_by: string | null;
  state: 'open' | 'used' | 'expired';
}

export interface AccountsResponse {
  items: AccountRow[];
  counts: { all: number; pending: number; admins: number; disabled: number };
  invites: InviteRow[];
}

export interface InviteCreated {
  code: string;
  role: 'admin' | 'user';
  email: string | null;
  expires_at: string;
  link: string;
}

export interface NavCounts {
  review_queue: number;
  memories: number;
}

export type OverviewRange = 'all' | '1h' | '12h' | '1d' | '7d' | '30d';

export interface HealthItem {
  key: string;
  name: string;
  status: 'healthy' | 'degraded' | 'down' | 'not_configured' | 'idle';
  detail: string | null;
  latency_ms: number | null;
}

export interface AuditEvent {
  id: number | string;
  timestamp: string;
  event_type: string;
  operation: string;
  actor_id: string;
  driver_id: string | null;
  actor_type: string | null;
  scope: string;
  owner_id: string;
  memory_id: string | null;
  memory_stub: string | null;
  memory_version: number | null;
  decision: 'allowed' | 'denied';
  metadata: Record<string, unknown>;
  change?: {
    before: { version: number; content: string; weight: number };
    after: { version: number; content: string; weight: number };
  };
}

export interface Overview {
  tenant_id: string;
  generated_at: string;
  memories: { current: number; new_7d: number; growth_pct: number | null };
  agents: { total: number; active_now: number; source: 'auth' | 'memory' };
  searches: { last_24h: number; p95_latency_ms: number | null };
  contradictions: { open: number; over_threshold: number; threshold: number };
  approvals: { enterprise_pending: number; pending_total: number };
  scopes: { scope: Scope; count: number; pending: number }[];
  categories: { name: string; memory_count: number }[];
  /** Bucket start (ISO, UTC) with counts for that bucket. */
  activity: { date: string; searches: number; writes: number }[];
  activity_range: OverviewRange;
  activity_bucket_seconds: number;
  activity_source: 'audit' | 'memory';
  recent: AuditEvent[];
  recent_source: 'audit' | 'memory';
  health: HealthItem[];
  context_assembly: { avg_tokens: number | null; prefix_hit_rate: number | null };
}

export type EntityType = 'person' | 'organization' | 'location' | 'object' | 'event';

export interface EntityRow {
  id: string;
  name: string;
  entity_type: EntityType | string;
  aliases: string[];
  memory_count: number;
  projects: string[];
  created_at: string | null;
  last_seen: string | null;
}

export interface EntitiesResponse {
  items: EntityRow[];
  total: number;
  page: number;
  per_page: number;
  has_more: boolean;
  counts: { all: number; person: number; organization: number; location: number; object: number; event: number };
}

export interface MemoryRow {
  id: string;
  stub: string;
  content_preview: string;
  scope: Scope;
  scope_id: string | null;
  owner_id: string;
  actor_id: string | null;
  driver_id: string | null;
  domains: string[];
  weight: number;
  version: number;
  is_current: boolean;
  status: string;
  content_type: string;
  branch_count: number;
  branch_summary: { type: string; count: number }[];
  open_contradictions: number;
  near_duplicate: number | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  score: number | null;
  entities: EntityRef[];
  /** Admins only: content, domains and entity names were withheld. */
  redacted?: boolean;
  entity_count?: number;
}

export interface EntityRef {
  id: string;
  name: string;
  type: string;
}

export interface Facet {
  value: string;
  count: number;
}

export interface BrowseResponse {
  items: MemoryRow[];
  total: number;
  page: number;
  per_page: number;
  search_mode: 'none' | 'semantic' | 'text' | 'metadata';
  metadata_only?: boolean;
  /** #667: scopes whose content this viewer cannot read (admins: user). */
  hidden_scopes?: string[];
  break_glass?: BreakGlassGrant | null;
  tab_counts: { current: number; all: number; quarantined: number; deleted: number };
  facets: {
    scopes: Facet[];
    writers: Facet[];
    projects: Facet[];
    domains: Facet[];
    flags: { contradicted: number; has_branches: number; near_duplicate: number | null };
  };
}

export interface BrowseParams {
  tab?: string;
  q?: string;
  mode?: string;
  scope?: string[];
  actor?: string[];
  project?: string;
  domain?: string[];
  min_weight?: number;
  flag?: string[];
  sort?: string;
  order?: string;
  page?: number;
  per_page?: number;
  entity?: string;
}

export interface NodeBrief {
  id: string;
  stub: string;
  scope: Scope;
  scope_id: string | null;
  owner_id: string;
  weight: number;
  version: number;
  is_current: boolean;
  status: string;
  created_at: string;
  updated_at: string;
  redacted?: boolean;
}

export interface MemoryContext {
  memory: NodeBrief & {
    content: string;
    logical_id: string | null;
    parent_id: string | null;
    branch_type: string | null;
    actor_id: string | null;
    driver_id: string | null;
    tenant_id: string;
    domains: string[];
    content_type: string;
    source: string | null;
    metadata: Record<string, unknown> | null;
    created_at: string;
    updated_at: string;
    deleted_at: string | null;
    expires_at: string | null;
    embedding_dims: number | null;
    injection: 'full' | 'stub';
    full_content_threshold: number;
  };
  versions: {
    id: string;
    version: number;
    is_current: boolean;
    content: string;
    weight: number;
    actor_id: string | null;
    driver_id: string | null;
    owner_id: string;
    created_at: string;
    deleted_at: string | null;
  }[];
  branches: { id: string; branch_type: string | null; content: string; actor_id: string; created_at: string }[];
  relationships: {
    id: string;
    type: string;
    direction: 'in' | 'out';
    created_by: string;
    created_at: string;
    other: NodeBrief;
  }[];
  relationships_omitted: number;
  contradictions: {
    id: string;
    observed_behavior: string;
    confidence: number;
    reporter: string;
    created_at: string;
    resolved: boolean;
  }[];
  contradiction_threshold: number;
  similar: (NodeBrief & { score: number })[];
  access_count: number;
}

export interface GraphAll {
  nodes: (NodeBrief & { depth: number; degree: number; redacted?: boolean })[];
  edges: { id: string; source: string; target: string; type: string }[];
  total: number;
  truncated: boolean;
  left_out: number;
  max_nodes: number;
  limit_ceiling: number;
  prefer: GraphPrefer;
  orphan_count: number;
  hidden_links: number;
  metadata_only: boolean;
}

export type GraphPrefer = 'connected' | 'recent' | 'weight';

export interface GraphNeighbourhood {
  focus: (NodeBrief & { content: string; degree: number; hidden_degree: number }) | null;
  nodes: (NodeBrief & { depth: number })[];
  edges: { id: string; source: string; target: string; type: string }[];
  hidden_count: number;
  cut_count: number;
  max_nodes: number;
  provenance: NodeBrief[];
  conflicts: NodeBrief[];
}

export interface SearchRequest {
  explain?: string[];
  query: string;
  focus?: string;
  identity?: string;
  project?: string;
  mode: 'full' | 'index' | 'full_only';
  max_results: number;
  session_focus_weight: number;
  weight_threshold: number;
  max_response_tokens: number;
  current_only: boolean;
  include_branches: boolean;
  rerank: boolean;
}

export interface SearchResult {
  rank: number;
  downgraded?: boolean;
  id: string;
  scope: Scope;
  scope_id: string | null;
  owner_id: string;
  stub: string;
  content: string | null;
  delivery: 'full' | 'stub';
  weight: number;
  version: number;
  scores: {
    vector: number | null;
    text: number | null;
    focus: number | null;
    rrf: number;
    rerank: number | null;
    weight: number;
  };
  tokens: number;
}

export interface SearchResponse {
  run_as: string;
  retrieval: 'vector' | 'text';
  rerank: 'on' | 'off' | 'unavailable' | 'not_configured';
  stages: { name: string; ms: number; detail?: string }[];
  total_ms: number;
  candidates: number;
  omitted_count: number;
  weight_filtered: number;
  returned: number;
  full_count: number;
  stub_count: number;
  tokens: number;
  results: SearchResult[];
  assembled_context: string;
  funnel?: FunnelStage[];
  dropped?: DroppedMemory[];
  hidden_dropped?: Record<string, number>;
  explain?: ExplainResult[];
}

export type FunnelKey = 'matched' | 'filters' | 'rbac' | 'weight' | 'limit' | 'budget';
export interface FunnelStage {
  key: FunnelKey;
  label: string;
  count: number;
  dropped?: number;
  downgraded?: number;
}
export interface DroppedMemory {
  id: string;
  stub: string;
  scope: Scope;
  scope_id: string | null;
  owner_id: string;
  weight: number;
  version: number;
  stage: FunnelKey;
  reason: string;
  detail: string;
  score?: number;
  rank?: number;
}
export interface ExplainResult {
  id: string;
  found: boolean;
  stub?: string;
  scope?: Scope;
  weight?: number;
  stage: FunnelKey | 'returned' | 'missing' | 'deleted';
  detail: string;
  rank?: number;
  similarity?: number;
}

export interface ProjectRow {
  name: string;
  description: string | null;
  invite_only: boolean;
  created_at: string;
  created_by: string;
  memories: number;
  last_write: string | null;
  members: number;
  campaigns: { id: string; name: string; status: string }[];
}

export interface ProjectDetail extends ProjectRow {
  agents_today: number;
  members_list: { user_id: string; role: string; joined_at: string; joined_by: string; via_team?: string | null }[];
  teams?: { id: string; name: string; members: number }[];
  focus_history: { focus: string; count: number }[] | null;
  focus_available: boolean;
  loading_policy: string;
}

export interface BehaviorProfile {
  schema: string;
  revision: number;
  template: 'balanced' | 'conservative' | 'proactive' | 'custom';
  include: string[];
  exclude: string[];
  custom_exclude: string[];
  confirmation: 'always' | 'sensitive' | 'never';
  cadence: 'every_turn' | 'session_end' | 'explicit';
  update: 'supersede' | 'branch' | 'ask';
  updated_at: string | null;
}

export interface MyPrefs {
  write: { default_scope: string; default_weight: number };
  privacy: { allow_promotion_by_others: boolean; show_in_team_directory: boolean };
  dreaming_fade_days: number;
  onboarding_dismissed?: boolean;
  behavior: BehaviorProfile;
  behavior_history?: BehaviorProfile[];
}

export interface MyPrefsResponse {
  prefs: MyPrefs;
  profile: {
    schema: string;
    templates: Record<string, BehaviorProfile>;
    categories: string[];
    excludes: string[];
    choices: Record<'confirmation' | 'cadence' | 'update', string[]>;
    applied_by: string[];
  };
  account: {
    username: string;
    name: string;
    email: string | null;
    role: Role;
    source: string;
    agents: string[];
    projects: string[];
    roles: string[];
    own_memories: number;
  };
}

export interface MyReads {
  days: number;
  who: 'others' | 'all';
  identities: string[];
  total: number;
  readers: { actor_id: string; driver_id: string | null; count: number; last: string; kinds: string[]; denied: number; yours: boolean; via_dashboard: boolean }[];
  top_memories: { id: string; stub: string; scope: string; count: number }[];
  events: {
    id: number | string;
    timestamp: string;
    event_type: string;
    actor_id: string;
    driver_id: string | null;
    decision: string;
    memory_id: string;
    memory_stub: string;
    yours: boolean;
    break_glass: boolean;
  }[];
}

export interface TeamRow {
  id: string;
  name: string;
  description: string | null;
  created_by: string;
  created_at: string;
  members: { user_id: string; role: 'lead' | 'member'; added_at: string }[];
  projects: string[];
}

export interface TeamsResponse {
  items: TeamRow[];
  counts: { teams: number; people: number };
}

export type DreamKind = 'duplicates' | 'connections' | 'fading' | 'contradictions' | 'themes';

export interface DreamInsight {
  id: string;
  kind: DreamKind;
  title: string;
  detail: string;
  memories: { id: string; stub: string; scope: string; owner_id: string; weight: number; version: number; updated_at: string | null }[];
  action: { type: 'merge' | 'link' | 'fade' | 'review' | 'consolidate'; [k: string]: unknown };
  confidence: number | null;
  status: 'proposed' | 'accepted' | 'dismissed';
  result?: string;
  auto?: boolean;
}

export interface DreamSettings {
  schedule: 'nightly' | 'weekly' | 'off';
  window: string;
  auto: { connections: boolean; fading: boolean };
  kinds: Record<DreamKind, boolean>;
}

export interface DreamReport {
  id: string;
  started_at: string;
  duration_ms: number;
  trigger: string;
  reviewed: number;
  insights: DreamInsight[];
  counts: Partial<Record<DreamKind, number>>;
}

export interface DreamsResponse {
  settings: DreamSettings;
  last: DreamReport | null;
  history: {
    id: string;
    started_at: string;
    duration_ms: number;
    trigger: string;
    reviewed: number;
    counts: Partial<Record<DreamKind, number>>;
    accepted: number;
    dismissed: number;
    total: number;
  }[];
}

export interface CampaignRow {
  id: string;
  name: string;
  description: string | null;
  status: string;
  default_ttl_days: number | null;
  projects: string[];
  memories: number;
  created_at: string;
  updated_at: string;
}

export interface IdentityRow {
  id: string;
  name: string;
  type: 'user' | 'user agent' | 'service';
  scopes: string[];
  client: boolean;
  active: boolean;
  public: boolean;
  created_at: string | null;
  bound_to: string | null;
  /** The person this agent belongs to (explicit owner or driver binding). */
  owner?: string | null;
  roles: string[];
  memory_count: number;
  last_active: string | null;
  active_now: boolean;
}

export interface IdentitiesResponse {
  items: IdentityRow[];
  auth_available: boolean;
  roles: { name: string; members: number }[];
  counts: { all: number; users: number; user_agents: number; service_agents: number; roles: number };
}

export interface IdentityDetail extends IdentityRow {
  grant: string | null;
  scope_matrix: { tier: string; read: boolean; write: string }[] | null;
  activity_24h: { searches: number; writes: number; denied: number; total: number };
  hourly: { hour: string; count: number }[];
  agents: { id: string; name: string }[];
}

export interface ClientResponse {
  client_id: string;
  client_name: string;
  identity_type: 'user' | 'service';
  tenant_id: string;
  default_scopes: string[];
  active: boolean;
  public?: boolean;
  created_at: string;
  updated_at: string;
}

export interface CredentialRow extends ClientResponse {
  grant: string;
  last_used: string | null;
  status: 'new' | 'active' | 'stale' | 'revoked';
}

export interface CredentialsResponse {
  auth_available: boolean;
  issuer: string | null;
  clients: CredentialRow[];
  api_keys: CredentialRow[];
  issuers: { name: string; kind?: string; description?: string; status?: string }[];
}

export interface ClientCreatedResponse extends ClientResponse {
  client_secret: string;
  api_key: string | null;
}

export interface SecretRotatedResponse {
  client_id: string;
  client_secret: string;
  api_key: string | null;
}

export interface ApiKeyRotatedResponse {
  client_id: string;
  api_key: string;
}

export interface PublicConfig {
  mcp_url: string;
  auth_url: string;
}

export interface CreateClientPayload {
  client_id: string;
  client_name: string;
  identity_type: 'user' | 'service';
  tenant_id: string;
  default_scopes: string[];
}

export interface UpdateClientPayload {
  client_name?: string;
  active?: boolean;
  default_scopes?: string[];
}

export interface CurationRule {
  id: string;
  name: string;
  description: string | null;
  trigger: string;
  tier: 'regex' | 'embedding' | string;
  config: Record<string, unknown>;
  action: string;
  scope_filter: string | null;
  layer: 'system' | 'organizational' | 'user' | string;
  owner_id: string | null;
  override: boolean;
  enabled: boolean;
  priority: number;
  version: number;
  is_current: boolean;
  previous_version_id: string | null;
  edited_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface RulePayload {
  name?: string;
  description?: string | null;
  trigger?: string;
  tier?: string;
  config?: Record<string, unknown>;
  action?: string;
  scope_filter?: string | null;
  layer?: string;
  owner_id?: string | null;
  override?: boolean;
  enabled?: boolean;
  priority?: number;
  edited_by?: string;
}

export interface RuleTestResult {
  matched: boolean;
  action: string;
  matches?: { text?: string; col?: number; line?: number; name?: string; detail?: string }[];
  score?: number;
  threshold?: number;
}

export interface ReviewSummary {
  kind: 'approval' | 'promotion' | 'contradiction' | 'quarantine' | 'history';
  id: string;
  stub: string;
  content: string;
  scope: Scope;
  owner_id: string;
  actor_id: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
  sources?: number;
  reports?: number;
}

export interface ReviewQueue {
  tab: string;
  counts: { approvals: number; promotions: number; contradictions: number; quarantine: number };
  items: (ReviewSummary | (AuditEvent & { kind: 'history' }))[];
  also_waiting: ReviewSummary[];
  approvers_required: number;
  viewer: string;
}

export interface ReviewItem {
  kind: string;
  id: string;
  content: string;
  stub: string;
  scope: Scope;
  scope_id: string | null;
  owner_id: string;
  status: string;
  weight: number;
  version: number;
  requested_by: string;
  requested_at: string;
  reason: string | null;
  injection: 'full' | 'stub';
  branches: { id: string; branch_type: string | null; content: string }[];
  sources: { id: string; stub: string; scope: Scope; owner_id: string }[];
  checks: {
    scan_clean: boolean;
    scan_findings: string[];
    similar: { id: string; stub: string; score: number } | null;
    enterprise_this_month: number;
    has_provenance: boolean;
  };
  contradictions: { id: string; observed_behavior: string; confidence: number; reporter: string; created_at: string }[];
  contradiction_threshold: number;
  history: { event_type: string; actor_id: string; timestamp: string; comment: string | null }[];
  reach_agents: number;
  approvers_required: number;
}

export interface AuditResponse {
  items: AuditEvent[];
  total: number;
  page: number;
  per_page: number;
  event_types: string[];
  operations: Record<string, string>;
  denied_total: number;
  /** #667: operations on user memories an admin may not see (super-users see all). */
  hidden_user_operations?: number;
  retention_days: number;
}

export interface ForensicsResponse {
  actor: string;
  at: string;
  window_minutes: number;
  events: number;
  last_search_at: string | null;
  context: {
    id: string;
    current_id: string;
    stub: string;
    content: string;
    scope: Scope;
    version_then: number;
    version_now: number;
    changed_after: boolean;
    changed_at: string | null;
    changed_by: string | null;
    deleted: boolean;
    served_at: string;
    delivery: 'full' | 'stub';
    tokens: number;
  }[];
  tokens: number;
  findings: (ForensicsResponse['context'][number] & { other_actors_exposed: number })[];
}

export interface TenantSettingsValues {
  retrieval: {
    max_results: number;
    max_response_tokens: number;
    session_focus_weight: number;
    full_content_threshold: number;
    rerank: boolean;
    cache_optimized_ordering: boolean;
    realtime_push: boolean;
  };
  governance: {
    project_isolation: boolean;
    role_isolation: boolean;
    contradiction_threshold: number;
    enterprise_approvers: number;
  };
  audit: {
    read_detail: 'full' | 'summary' | 'sample';
    full_retention_days: number;
    mcp_profile: 'compact' | 'full';
  };
  organization: { name: string; contact_email: string };
  signup: { mode: SignupMode; allowed_domains: string[]; require_approval: boolean };
  privacy: SetupPayload['privacy'];
  security: SetupPayload['security'];
}

export interface SettingsResponse {
  values: TenantSettingsValues;
  meta: { updated_at: string | null; updated_by: string | null; persisted: boolean };
  models: {
    embedding: Partial<HealthItem> & { url: string | null };
    reranker: Partial<HealthItem> & { url: string | null };
  };
  mcp: Partial<HealthItem> & { public_url: string; internal_url: string };
  tenant: { tenant_id: string; auth_url: string; cluster_domain: string | null };
}

/* ---------------- Memory workspace: timeline, entities, usage ---------------- */

export interface TimelineItem {
  id: string;
  stub: string;
  scope: Scope;
  scope_id: string | null;
  owner_id: string;
  weight: number;
  version: number;
  domains: string[];
  created_at: string;
  updated_at: string;
  at: string;
  redacted?: boolean;
}

export interface TimelineResponse {
  items: TimelineItem[];
  total: number;
  truncated: boolean;
  by: 'created' | 'updated';
  days: number;
  first: string | null;
  now: string;
  metadata_only: boolean;
}

export interface EntityMemory {
  id: string;
  stub: string;
  scope: Scope;
  scope_id: string | null;
  owner_id: string;
  weight: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface EntityDetail {
  id: string;
  name: string;
  entity_type: string;
  aliases: string[];
  created_at: string;
  memory_count: number;
  hidden_mentions: number;
  first_seen: string | null;
  last_seen: string | null;
  scopes: Record<string, number>;
  writers: { value: string; count: number }[];
  projects: { value: string; count: number }[];
  months: { month: string; count: number }[];
  co_mentions: { id: string; name: string; type: string; count: number }[];
  memories: EntityMemory[];
}

export interface EntityMergePreview {
  source: { id: string; name: string; entity_type: string; aliases: string[] };
  target: { id: string; name: string; entity_type: string; aliases: string[] };
  moving: number;
  both: number;
  staying: number;
  aliases_after: string[];
  source_removed: boolean;
  memories: { id: string; stub: string; scope: Scope }[];
  dry_run: boolean;
}

export interface MemoryUsage {
  days: number;
  full_text?: boolean;
  served: number;
  used: number;
  skipped: number;
  full: number;
  reads?: number;
  last?: string | null;
  use_rate: number | null;
}

export interface UsageSummary extends MemoryUsage {
  memories_served: number;
  skipped_most: { id: string; stub: string; scope: Scope; weight: number; served: number; used: number; skipped: number; use_rate: number | null; redacted?: boolean }[];
}

/* ---------------- Knowledge pages ---------------- */

export interface KnowledgeFact {
  text: string;
  memory_id: string;
  memory_ids: string[];
  similar: number;
  scope: Scope;
  weight: number;
  updated_at: string;
  stale: boolean;
  contradicted: number;
}

export interface KnowledgePage {
  subject: { kind: 'me' | 'project'; id: string; title: string };
  generated_at: string;
  rebuilt: boolean;
  truncated: boolean;
  source_count: number;
  last_source_change: string | null;
  summary: { facts: number; folded: number; sections: number; entities: number; open_questions: number; stale: number };
  highlights: KnowledgeFact[];
  sections: { title: string; facts: KnowledgeFact[] }[];
  entities: { id: string; name: string; type: string; count: number }[];
  recent: { memory_id: string; text: string; updated_at: string; change: 'new' | 'updated'; version: number }[];
  questions: { kind: 'contradiction'; memory_id: string; text: string; count: number }[];
  stale: KnowledgeFact[];
  changes: { since: string | null; added: { memory_id: string; text: string }[]; removed: { memory_id: string; text: string }[] } | null;
  scopes: Record<string, number>;
}

export interface KnowledgeIndexItem {
  kind: 'me' | 'project';
  id: string;
  title: string;
  source_count: number;
  generated_at: string | null;
  fresh: boolean;
  summary: KnowledgePage['summary'] | null;
  sections: string[];
}

/* ---------------- Notifications & onboarding ---------------- */

export interface NotificationItem {
  id: string;
  kind: 'break_glass' | 'contradiction' | 'reads' | 'dream' | 'review';
  severity: 'danger' | 'warning' | 'info';
  title: string;
  body: string;
  at: string | null;
  href: string;
  unread: boolean;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  unread: number;
  seen_at: string | null;
}

export interface OnboardingStep {
  id: string;
  title: string;
  body: string;
  href: string;
  done: boolean;
}

export interface Onboarding {
  steps: OnboardingStep[];
  done: number;
  total: number;
  dismissed: boolean;
}

/* ---------------- Saved queries & retrieval checks ---------------- */

export interface CheckMetrics {
  expected: number;
  found: number;
  hit: boolean;
  recall: number | null;
  precision: number;
  mrr: number;
  first_rank: number | null;
}

export interface SavedQuery {
  id: string;
  owner: string;
  name: string;
  request: Omit<SearchRequest, 'explain'>;
  expected: string[];
  visibility: 'private' | 'project';
  project: string | null;
  created_at: string;
  updated_at: string;
  last_result: (CheckMetrics & { at: string }) | null;
  mine: boolean;
  is_check: boolean;
}

export interface CheckResult {
  query_id: string;
  name: string;
  query: string;
  returned: string[];
  metrics: CheckMetrics;
  missing: ExplainResult[];
  total_ms: number;
  funnel: FunnelStage[];
}

export interface CheckSummary {
  checks: number;
  hit_rate?: number;
  recall?: number;
  precision?: number;
  mrr?: number;
  p50_ms?: number;
  failing?: number;
}

export interface CheckRun {
  id: string;
  started_at: string;
  duration_ms: number;
  trigger: string;
  summary: CheckSummary;
  results?: CheckResult[];
}

export interface ChecksOverview {
  checks: SavedQuery[];
  queries: SavedQuery[];
  last: CheckRun | null;
  runs: CheckRun[];
}

export interface SearchHealth {
  days: number;
  scope: 'own' | 'tenant';
  runs: number;
  sources?: Record<string, number>;
  vector_share?: number;
  rerank?: Record<string, number>;
  latency?: { p50: number; p95: number };
  stages?: { name: string; p50: number }[];
  avg?: { matched: number; returned: number; tokens: number };
  cut?: Record<'filters' | 'rbac' | 'weight' | 'limit' | 'budget', number>;
  empty_share?: number;
  by_day: { date: string; runs: number }[];
}

/* ---------------- Context packs ---------------- */

export interface PackQuery {
  query: string;
  max_results: number;
  weight_threshold: number;
  project?: string | null;
}

export interface ContextPack {
  id: string;
  owner: string;
  name: string;
  description: string | null;
  pinned: string[];
  queries: PackQuery[];
  token_budget: number;
  visibility: 'private' | 'project';
  project: string | null;
  read_only: boolean;
  agents: string[];
  created_at: string;
  updated_at: string;
  last_render: { at: string; tokens: number; items: number } | null;
  mine: boolean;
  can_edit: boolean;
}

export interface PackRender {
  items: { id: string; stub: string; scope: Scope; text: string; source: string; tokens: number; weight: number }[];
  tokens: number;
  budget: number;
  over_budget: { id: string; stub: string; source: string; tokens: number }[];
  hidden: number;
  missing: number;
  markdown: string;
  rendered_at: string;
  as: string;
}

export interface ContextPackDetail extends ContextPack {
  render: PackRender;
  my_agents: string[];
}

/* ---------------- Documents ---------------- */

export interface DocumentRow {
  id: string;
  owner: string;
  title: string;
  mime: string;
  size: number;
  version: number;
  project: string | null;
  created_at: string;
  updated_at: string;
  memories: number;
  changed: number;
  mine: boolean;
}

export interface DocumentDetail {
  id: string;
  owner: string;
  title: string;
  mime: string;
  body: string;
  version: number;
  project: string | null;
  created_at: string;
  updated_at: string;
  passages: { i: number; start: number; end: number; text: string; memories: string[] }[];
  links: { memory_id: string; start: number; end: number; status: 'ok' | 'moved' | 'changed' | 'deleted'; doc_version: number; stub: string; scope: Scope; is_current: boolean }[];
  mine: boolean;
}

export interface MemorySource {
  linked: boolean;
  redacted?: boolean;
  document_deleted?: boolean;
  document_id?: string | null;
  title?: string | null;
  status?: 'ok' | 'moved' | 'changed';
  version?: number;
  linked_version?: number;
  before?: string;
  passage?: string;
  snippet?: string;
  after?: string;
}

/* ---------------- Operations ---------------- */

export interface JobRow {
  id: string;
  owner: string;
  kind: string;
  label: string;
  status: 'ok' | 'failed' | 'running';
  trigger: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  attempts: number;
  correlation_id: string;
  retry_of: string | null;
  error: string | null;
  retryable: boolean;
  stale: boolean;
  detail: Record<string, unknown>;
}

export interface OperationsResponse {
  items: JobRow[];
  kinds: { kind: string; label: string; ok: number; failed: number; running: number; avg_ms?: number; p95_ms?: number }[];
  days: number;
  scope: 'own' | 'tenant';
}

export interface NavFeatures {
  knowledge?: number;
  documents?: number;
  packs?: number;
  checks?: number;
  check_runs?: number;
  search_runs?: number;
  jobs?: number;
}

export type VerifyStatus = 'pass' | 'warn' | 'fail' | 'not_run';

export interface VerifyCheck {
  id: string;
  title: string;
  status: VerifyStatus;
  category: string | null;
  category_label: string | null;
  code: string | null;
  explanation: string;
  next_action: string | null;
  source: 'dashboard' | 'host';
  duration_ms: number | null;
}

export interface VerifyResult {
  id: string;
  created_at: string;
  schema: string;
  source: 'dashboard' | 'host';
  produced_by: Record<string, string | null>;
  started_at: string | null;
  finished_at: string | null;
  context: Record<string, unknown>;
  checks: VerifyCheck[];
  summary: { pass: number; warn: number; fail: number; not_run: number; state: 'pass' | 'warn' | 'fail' | 'partial' };
}

export interface VerifyList {
  schema: string;
  checks: { id: string; title: string }[];
  categories: { id: string; label: string }[];
  host_command: string | null;
  results: VerifyResult[];
}

export interface BreakGlassGrant {
  id: string;
  username: string;
  incident_ref: string;
  justification: string;
  created_at: string;
  expires_at: string;
  ended_at: string | null;
  active: boolean;
  reads?: number;
  owners?: number;
}

export interface BreakGlassState {
  policy: { enabled: boolean; hours: number; pattern: string; notify_owner: boolean };
  active: BreakGlassGrant | null;
  grants: BreakGlassGrant[];
}

export interface BreakGlassReport {
  month: string;
  grants: BreakGlassGrant[];
  accesses: { actor: string; incident_ref: string | null; owner: string; reads: number; first: string; last: string }[];
  totals: { grants: number; reads: number; owners: number };
}
