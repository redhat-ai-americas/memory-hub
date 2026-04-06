import type {
  ClientCreatedResponse,
  ClientResponse,
  ContradictionReport,
  ContradictionStats,
  CreateClientPayload,
  CreateRulePayload,
  CurationRule,
  GraphResponse,
  MemoryDetail,
  SearchMatch,
  SecretRotatedResponse,
  StatsResponse,
  UpdateClientPayload,
  UpdateRulePayload,
  UserEntry,
  VersionEntry,
} from '@/types';

const BASE = '/api';

async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API error ${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchGraph(scope?: string, owner?: string): Promise<GraphResponse> {
  const params = new URLSearchParams();
  if (scope) params.set('scope', scope);
  if (owner) params.set('owner_id', owner);
  const query = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<GraphResponse>(`/graph${query}`);
}

export async function searchGraph(query: string): Promise<SearchMatch[]> {
  const params = new URLSearchParams({ q: query });
  return apiFetch<SearchMatch[]>(`/graph/search?${params.toString()}`);
}

export async function fetchStats(): Promise<StatsResponse> {
  return apiFetch<StatsResponse>('/stats');
}

export async function fetchMemoryDetail(id: string): Promise<MemoryDetail> {
  return apiFetch<MemoryDetail>(`/memory/${encodeURIComponent(id)}`);
}

export async function fetchMemoryHistory(id: string): Promise<VersionEntry[]> {
  return apiFetch<VersionEntry[]>(`/memory/${encodeURIComponent(id)}/history`);
}

export async function deleteMemory(id: string): Promise<void> {
  const response = await fetch(`${BASE}/memory/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API error ${response.status}: ${detail}`);
  }
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API error ${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API error ${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchClients(): Promise<ClientResponse[]> {
  return apiFetch<ClientResponse[]>('/clients');
}

export async function createClient(payload: CreateClientPayload): Promise<ClientCreatedResponse> {
  return apiPost<ClientCreatedResponse>('/clients', payload);
}

export async function updateClient(clientId: string, payload: UpdateClientPayload): Promise<ClientResponse> {
  return apiPatch<ClientResponse>(`/clients/${encodeURIComponent(clientId)}`, payload);
}

export async function rotateClientSecret(clientId: string): Promise<SecretRotatedResponse> {
  return apiPost<SecretRotatedResponse>(`/clients/${encodeURIComponent(clientId)}/rotate-secret`, {});
}

export async function fetchUsers(): Promise<UserEntry[]> {
  return apiFetch<UserEntry[]>('/users');
}

// --- Curation Rules ---

export async function fetchRules(params?: { tier?: string; enabled?: boolean; layer?: string }): Promise<CurationRule[]> {
  const qs = new URLSearchParams();
  if (params?.tier) qs.set('tier', params.tier);
  if (params?.enabled !== undefined) qs.set('enabled', String(params.enabled));
  if (params?.layer) qs.set('layer', params.layer);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<CurationRule[]>(`/rules${query}`);
}

export async function createRule(payload: CreateRulePayload): Promise<CurationRule> {
  return apiPost<CurationRule>('/rules', payload);
}

export async function updateRule(ruleId: string, payload: UpdateRulePayload): Promise<CurationRule> {
  return apiPatch<CurationRule>(`/rules/${encodeURIComponent(ruleId)}`, payload);
}

export async function deleteRule(ruleId: string): Promise<void> {
  const response = await fetch(`${BASE}/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API error ${response.status}: ${detail}`);
  }
}

// --- Contradiction Reports ---

export async function fetchContradictions(params?: { resolved?: boolean; min_confidence?: number; max_confidence?: number }): Promise<ContradictionReport[]> {
  const qs = new URLSearchParams();
  if (params?.resolved !== undefined) qs.set('resolved', String(params.resolved));
  if (params?.min_confidence !== undefined) qs.set('min_confidence', String(params.min_confidence));
  if (params?.max_confidence !== undefined) qs.set('max_confidence', String(params.max_confidence));
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<ContradictionReport[]>(`/contradictions${query}`);
}

export async function updateContradiction(reportId: string, resolved: boolean): Promise<ContradictionReport> {
  return apiPatch<ContradictionReport>(`/contradictions/${encodeURIComponent(reportId)}`, { resolved });
}

export async function fetchContradictionStats(): Promise<ContradictionStats> {
  return apiFetch<ContradictionStats>('/contradictions/stats');
}
