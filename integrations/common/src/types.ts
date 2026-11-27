export interface SessionInfo {
  sessionId: string;
  userId: string;
  name: string;
  scopes: string[];
  projectMemberships: string[];
}

export interface MemoryHubMcpClient {
  connect(): Promise<void>;
  registerSession(apiKey: string): Promise<SessionInfo>;
  callMemory(
    action: string,
    params: Record<string, unknown>,
  ): Promise<unknown>;
  close(): Promise<void>;
  isConnected(): boolean;
  resetSession(): void;
}

export interface SharedPluginConfig {
  server: { url: string };
  auth: { apiKey?: string };
  autoRecall: {
    enabled: boolean;
    maxResults: number;
    maxResponseTokens: number;
  };
  defaults: {
    scope: string;
    projectId?: string;
    domains: string[];
  };
  needsSetup: boolean;
}

export interface SearchResultItem {
  id?: string;
  content?: string;
  stub?: string;
  weight?: number;
  scope?: string;
  relevance_score?: number;
}
