import type {
  ApiKeyRotatedResponse,
  AuthStatus,
  BrowseParams,
  BrowseResponse,
  ClientCreatedResponse,
  ClientResponse,
  ContradictionReport,
  ContradictionStats,
  CreateClientPayload,
  CurationRule,
  EntitiesResponse,
  EntityDetail,
  EntityMergePreview,
  EntityType,
  GraphResponse,
  Me,
  MemoryRecord,
  MemoryVersion,
  NavCounts,
  ProjectDetail,
  ProjectsResponse,
  PublicConfig,
  RulePayload,
  RuleVersion,
  SearchMatch,
  SecretRotatedResponse,
  StatsResponse,
  UpdateClientPayload,
  UserRow,
} from '@/types';

const BASE = '/api';

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

/** Fired when the BFF says the dev API-key session is missing or expired. */
export const AUTH_REQUIRED_EVENT = 'memoryhub:auth-required';
export const AUTHORIZATION_CHANGED_EVENT = 'memoryhub:authorization-changed';

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      credentials: 'same-origin',
      // QA 2026-11-10: GETs are the dashboard loading a page. The marker only
      // categorises a denied call in the audit log (dashboard check vs user
      // action); it never grants or hides anything.
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(method === 'GET' ? { 'X-MemoryHub-Request': 'background' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, 'The dashboard backend is not reachable.');
  }
  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      detail = await response.text().catch(() => '');
    }
    if (response.status === 401 && !path.startsWith('/auth/')) {
      window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
    }
    throw new ApiError(response.status, detail || response.statusText);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const get = <T,>(path: string) => request<T>('GET', path);
const post = <T,>(path: string, body: unknown = {}) => request<T>('POST', path, body);
const patch = <T,>(path: string, body: unknown) => request<T>('PATCH', path, body);
const del = <T,>(path: string) => request<T>('DELETE', path);

const qs = (params: Record<string, unknown>): string => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)));
    else search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
};
const enc = encodeURIComponent;

/**
 * Every call the dashboard makes. Each one maps to a route of the dashboard BFF
 * (memoryhub-ui/backend: routes.py and human_adapters.py); nothing here calls
 * an endpoint the BFF does not serve.
 */
export const api = {
  // Session (oauth-proxy principal)
  me: () => get<Me>('/me'),
  authStatus: () => get<AuthStatus>('/auth/status'),
  logout: () => post<{ ok: boolean; redirect?: string; method?: 'GET' | 'POST' }>('/auth/logout'),
  navCounts: () => get<NavCounts>('/nav-counts'),
  publicConfig: () => get<PublicConfig>('/public-config'),

  // Overview
  stats: () => get<StatsResponse>('/stats'),

  // Memories
  browse: (params: BrowseParams) => get<BrowseResponse>(`/memories/browse${qs(params as Record<string, unknown>)}`),
  memory: (id: string) => get<MemoryRecord>(`/memory/${enc(id)}`),
  memoryHistory: (id: string) => get<MemoryVersion[]>(`/memory/${enc(id)}/history`),
  writeMemory: (body: {
    content: string;
    scope: 'user' | 'project' | 'organizational';
    weight?: number;
    owner_id?: string;
    scope_id?: string;
    domains?: string[];
  }) => post<{ id: string }>('/memories', body),
  newVersion: (id: string, body: { content?: string; weight?: number; domains?: string[]; metadata?: Record<string, unknown> }) =>
    post<{ id: string; version: number }>(`/memory/${enc(id)}/versions`, body),
  addBranch: (id: string, body: { branch_type: 'rationale' | 'provenance' | 'evidence' | 'description'; content: string }) =>
    post<{ id: string }>(`/memory/${enc(id)}/branches`, body),
  reportContradiction: (id: string, body: { observed_behavior: string; confidence: number }) =>
    post<{ unresolved: number }>(`/memory/${enc(id)}/contradictions`, body),
  createRelationship: (body: { source_id: string; target_id: string; relationship_type: 'related_to' | 'derived_from' | 'supersedes' | 'conflicts_with' }) =>
    post<{ id: string }>('/relationships', body),
  deleteMemory: (id: string) => del<void>(`/memory/${enc(id)}`),
  /** Admins: quarantine or restore up to 100 memories. */
  moderate: (body: { action: 'quarantine' | 'restore'; ids: string[]; reason?: string }) =>
    post<{ done: string[]; errors: { id: string; detail: string }[] }>('/memories/bulk', body),

  // Graph & search
  graph: (params: { scope?: string; owner_id?: string } = {}) => get<GraphResponse>(`/graph${qs(params)}`),
  search: (q: string) => get<SearchMatch[]>(`/graph/search${qs({ q })}`),

  // Entities (users only)
  entities: (params: { q?: string; type?: EntityType | 'all'; project?: string; page?: number; per_page?: number } = {}) =>
    get<EntitiesResponse>(`/entities${qs(params)}`),
  entity: (id: string) => get<EntityDetail>(`/entities/${enc(id)}`),
  /** Only the name can change; type and aliases are fixed by extraction. */
  renameEntity: (id: string, name: string) =>
    patch<{ id: string; name: string; entity_type: string; aliases: string[] }>(`/entities/${enc(id)}`, { name }),
  mergeEntity: (id: string, into: string, dryRun: boolean) =>
    post<EntityMergePreview>(`/entities/${enc(id)}/merge`, { into, dry_run: dryRun }),

  // Projects
  projects: (mine = false) => get<ProjectsResponse>(`/projects${qs({ mine: mine || undefined })}`),
  project: (name: string) => get<ProjectDetail>(`/projects/${enc(name)}`),
  createProject: (body: { name: string; description?: string; invite_only: boolean; members?: { user_id: string; role: 'member' | 'admin' }[] }) =>
    post<{ name: string }>('/projects', body),
  addMember: (name: string, body: { user_id: string; role: 'member' | 'admin' }) =>
    post<{ ok: boolean }>(`/projects/${enc(name)}/members`, body),
  removeMember: (name: string, userId: string) => del<void>(`/projects/${enc(name)}/members/${enc(userId)}`),

  // Identities & OAuth clients
  users: () => get<UserRow[]>('/users'),
  clients: () => get<ClientResponse[]>('/clients'),
  createClient: (payload: CreateClientPayload) => post<ClientCreatedResponse>('/clients', payload),
  updateClient: (clientId: string, payload: UpdateClientPayload) =>
    patch<ClientResponse>(`/clients/${enc(clientId)}`, payload),
  rotateSecret: (clientId: string) => post<SecretRotatedResponse>(`/clients/${enc(clientId)}/rotate-secret`),
  rotateApiKey: (clientId: string) => post<ApiKeyRotatedResponse>(`/clients/${enc(clientId)}/rotate-api-key`),

  // Curation rules
  rules: () => get<CurationRule[]>('/rules'),
  ruleHistory: (id: string) => get<RuleVersion[]>(`/rules/${enc(id)}/history`),
  createRule: (payload: RulePayload) => post<CurationRule>('/rules', payload),
  updateRule: (id: string, payload: RulePayload) => patch<CurationRule>(`/rules/${enc(id)}`, payload),
  deleteRule: (id: string) => del<void>(`/rules/${enc(id)}`),

  // Contradictions (admins resolve)
  contradictions: (params: { resolved?: boolean; min_confidence?: number; max_confidence?: number } = {}) =>
    get<ContradictionReport[]>(`/contradictions${qs(params)}`),
  contradictionStats: () => get<ContradictionStats>('/contradictions/stats'),
  setContradictionResolved: (id: string, resolved: boolean) =>
    patch<ContradictionReport>(`/contradictions/${enc(id)}`, { resolved }),
};
