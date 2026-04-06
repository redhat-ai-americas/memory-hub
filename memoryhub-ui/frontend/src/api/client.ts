import type {
  GraphResponse,
  SearchMatch,
  StatsResponse,
  MemoryDetail,
  VersionEntry,
} from '@/types';

const BASE = '/api';

async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API error ${response.status}: ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchGraph(scope?: string, owner?: string): Promise<GraphResponse> {
  const params = new URLSearchParams();
  if (scope) params.set('scope', scope);
  if (owner) params.set('owner', owner);
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
