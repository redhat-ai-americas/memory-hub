import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

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

export class McpClientError extends Error {
  constructor(
    message: string,
    public readonly isToolError: boolean = false,
  ) {
    super(message);
    this.name = "McpClientError";
  }
}

export function createMcpClient(serverUrl: string): MemoryHubMcpClient {
  let client: Client | null = null;
  let transport: StreamableHTTPClientTransport | null = null;
  let connected = false;
  let connecting: Promise<void> | null = null;

  function connect(): Promise<void> {
    if (connected) return Promise.resolve();
    // Single-flight: overlapping callers share one connection attempt, and
    // transport/client are only published on success so a failed or
    // superseded attempt can't leak an open socket.
    connecting ??= (async () => {
      const url = new URL(serverUrl);
      const t = new StreamableHTTPClientTransport(url);
      const c = new Client({
        name: "opencode-memoryhub",
        version: "0.1.0",
      });
      try {
        await c.connect(t);
      } catch (e) {
        void t.close().catch(() => {});
        throw e;
      }
      transport = t;
      client = c;
      connected = true;
    })().finally(() => {
      connecting = null;
    });
    return connecting;
  }

  async function ensureConnected(): Promise<Client> {
    if (!connected || !client) {
      await connect();
    }
    return client!;
  }

  function extractTextContent(result: unknown): unknown {
    if (
      typeof result === "object" &&
      result !== null &&
      "content" in result
    ) {
      const r = result as {
        content?: Array<{ type: string; text?: string }>;
        isError?: boolean;
      };
      if (r.isError) {
        const errorText =
          r.content
            ?.filter((c) => c.type === "text")
            .map((c) => c.text)
            .join("\n") ?? "Unknown MCP error";
        throw new McpClientError(errorText, true);
      }
      const textParts = r.content?.filter((c) => c.type === "text") ?? [];
      if (textParts.length === 1 && textParts[0].text) {
        try {
          return JSON.parse(textParts[0].text);
        } catch {
          return textParts[0].text;
        }
      }
      return textParts.map((c) => c.text).join("\n");
    }
    return result;
  }

  function resetSession(): void {
    // Close the stale transport in the background so the next
    // ensureConnected() builds a fresh one instead of leaking sockets.
    const stale = transport;
    transport = null;
    client = null;
    connected = false;
    if (stale) {
      void stale.close().catch(() => {});
    }
  }

  async function registerSession(apiKey: string): Promise<SessionInfo> {
    const c = await ensureConnected();
    const result = await c.callTool({
      name: "register_session",
      arguments: { api_key: apiKey },
    });

    const data = extractTextContent(result) as Record<string, unknown>;
    return {
      sessionId: String(data.session_id ?? ""),
      userId: String(data.user_id ?? ""),
      name: String(data.name ?? ""),
      scopes: Array.isArray(data.scopes)
        ? data.scopes.map(String)
        : [],
      projectMemberships: Array.isArray(data.project_memberships)
        ? data.project_memberships.map(String)
        : [],
    };
  }

  async function callMemory(
    action: string,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    const c = await ensureConnected();
    const args: Record<string, unknown> = { action };

    if (params.memory_id !== undefined) args.memory_id = params.memory_id;
    if (params.query !== undefined) args.query = params.query;
    if (params.content !== undefined) args.content = params.content;
    if (params.scope !== undefined) args.scope = params.scope;
    if (params.project_id !== undefined) args.project_id = params.project_id;
    if (params.options !== undefined) args.options = params.options;

    const result = await c.callTool({
      name: "memory",
      arguments: args,
    });
    return extractTextContent(result);
  }

  async function close(): Promise<void> {
    if (transport) {
      await transport.close();
    }
    client = null;
    transport = null;
    connected = false;
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
