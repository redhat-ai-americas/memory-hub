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
  let storedApiKey: string | null = null;

  async function connect(): Promise<void> {
    if (connected) return;

    const url = new URL(serverUrl);
    transport = new StreamableHTTPClientTransport(url);
    client = new Client({
      name: "openclaw-memoryhub",
      version: "0.1.0",
    });
    await client.connect(transport);
    connected = true;
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
    storedApiKey = null;
    connected = false;
  }

  async function registerSession(apiKey: string): Promise<SessionInfo> {
    const c = await ensureConnected();
    storedApiKey = apiKey;
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
