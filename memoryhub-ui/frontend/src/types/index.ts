export interface GraphNode {
  id: string;
  content: string;
  stub: string;
  scope: 'user' | 'project' | 'organizational' | 'enterprise';
  weight: number;
  branch_type: string | null;
  owner_id: string;
  version: number;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown> | null;
  parent_id: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string; // "parent_child" | "derived_from" | "supersedes" | "conflicts_with" | "related_to"
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ScopeCount {
  scope: string;
  count: number;
}

export interface RecentActivity {
  id: string;
  stub: string;
  scope: string;
  owner_id: string;
  updated_at: string;
  action: string;
}

export interface StatsResponse {
  total_memories: number;
  scope_counts: ScopeCount[];
  recent_activity: RecentActivity[];
  mcp_health: boolean;
}

export interface MemoryDetail {
  id: string;
  content: string;
  stub: string;
  scope: string;
  weight: number;
  branch_type: string | null;
  owner_id: string;
  version: number;
  is_current: boolean;
  parent_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  children_count: number;
  relationships: GraphEdge[];
}

export interface VersionEntry {
  id: string;
  version: number;
  is_current: boolean;
  stub: string;
  content: string;
  created_at: string;
}

export interface SearchMatch {
  id: string;
  score: number;
}
