import type { MemoryHubMcpClient, SessionInfo } from "./types.js";

export interface McpTransport {
  close(): Promise<void>;
}

export interface McpRuntimeClient {
  connect(transport: McpTransport): Promise<void>;
  callTool(request: { name: string; arguments: Record<string, unknown> }): Promise<unknown>;
}

export interface McpRuntime {
  createTransport(url: URL): McpTransport;
  createClient(name: string, version: string): McpRuntimeClient;
}

export class McpClientError extends Error {
  constructor(
    message: string,
    public readonly isToolError = false,
  ) {
    super(message);
    this.name = "McpClientError";
  }
}

const MAX_CONNECT_ATTEMPTS = 3;

export function createMcpClient(
  serverUrl: string,
  runtime: McpRuntime,
  clientName = "memoryhub-plugin",
): MemoryHubMcpClient {
  let client: McpRuntimeClient | null = null;
  let transport: McpTransport | null = null;
  let connected = false;
  let connecting: Promise<void> | null = null;
  let generation = 0;

  function connect(): Promise<void> {
    if (connected) return Promise.resolve();
    if (connecting) return connecting;

    const attemptGeneration = generation;
    const attempt = (async () => {
      const nextTransport = runtime.createTransport(new URL(serverUrl));
      try {
        const nextClient = runtime.createClient(clientName, "0.1.0");
        await nextClient.connect(nextTransport);
        if (attemptGeneration !== generation) {
          await nextTransport.close();
          return;
        }
        transport = nextTransport;
        client = nextClient;
        connected = true;
      } catch (error) {
        await nextTransport.close().catch(() => undefined);
        throw error;
      }
    })();

    let wrappedAttempt: Promise<void>;
    wrappedAttempt = attempt.finally(() => {
      if (connecting === wrappedAttempt) connecting = null;
    });
    connecting = wrappedAttempt;
    return wrappedAttempt;
  }

  async function ensureConnected(): Promise<McpRuntimeClient> {
    for (let attempt = 0; attempt < MAX_CONNECT_ATTEMPTS; attempt++) {
      await connect();
      if (connected && client) return client;
    }
    throw new Error(
      `MCP connection was reset during all ${MAX_CONNECT_ATTEMPTS} connection attempts`,
    );
  }

  function extractTextContent(result: unknown): unknown {
    if (typeof result !== "object" || result === null || !("content" in result)) {
      return result;
    }
    const response = result as {
      content?: Array<{ type: string; text?: string }>;
      isError?: boolean;
    };
    const textParts = response.content?.filter((item) => item.type === "text") ?? [];
    if (response.isError) {
      throw new McpClientError(
        textParts.map((item) => item.text).join("\n") || "Unknown MCP error",
        true,
      );
    }
    if (textParts.length === 1 && textParts[0].text) {
      try {
        return JSON.parse(textParts[0].text);
      } catch {
        return textParts[0].text;
      }
    }
    return textParts.map((item) => item.text).join("\n");
  }

  async function registerSession(apiKey: string): Promise<SessionInfo> {
    const activeClient = await ensureConnected();
    const result = await activeClient.callTool({
      name: "register_session",
      arguments: { api_key: apiKey },
    });
    const data = extractTextContent(result) as Record<string, unknown>;
    return {
      sessionId: String(data.session_id ?? ""),
      userId: String(data.user_id ?? ""),
      name: String(data.name ?? ""),
      scopes: Array.isArray(data.scopes) ? data.scopes.map(String) : [],
      projectMemberships: Array.isArray(data.project_memberships)
        ? data.project_memberships.map(String)
        : [],
    };
  }

  async function callMemory(
    action: string,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    const activeClient = await ensureConnected();
    const args: Record<string, unknown> = { action };
    for (const key of ["memory_id", "query", "content", "scope", "project_id", "options"]) {
      if (params[key] !== undefined) args[key] = params[key];
    }
    return extractTextContent(
      await activeClient.callTool({ name: "memory", arguments: args }),
    );
  }

  function resetSession(): void {
    generation++;
    connecting = null;
    connected = false;
    client = null;
    const staleTransport = transport;
    transport = null;
    if (staleTransport) void staleTransport.close().catch(() => undefined);
  }

  async function close(): Promise<void> {
    generation++;
    connecting = null;
    connected = false;
    client = null;
    const staleTransport = transport;
    transport = null;
    if (staleTransport) await staleTransport.close();
  }

  return {
    connect,
    registerSession,
    callMemory,
    close,
    isConnected: () => connected,
    resetSession,
  };
}
