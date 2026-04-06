import type {
  ClientCreatedResponse,
  ClientResponse,
  CreateClientPayload,
  GraphResponse,
  MemoryDetail,
  SearchMatch,
  SecretRotatedResponse,
  StatsResponse,
  UpdateClientPayload,
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
