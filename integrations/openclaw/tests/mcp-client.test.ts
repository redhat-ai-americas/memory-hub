import { describe, it, expect, vi, beforeEach } from "vitest";
import { createMcpClient, McpClientError } from "../src/mcp-client.js";

vi.mock("@modelcontextprotocol/sdk/client/index.js", () => {
  return {
    Client: vi.fn().mockImplementation(() => ({
      connect: vi.fn().mockResolvedValue(undefined),
      callTool: vi.fn().mockResolvedValue({
        content: [{ type: "text", text: '{"session_id":"s1"}' }],
      }),
      close: vi.fn().mockResolvedValue(undefined),
    })),
  };
});

vi.mock("@modelcontextprotocol/sdk/client/streamableHttp.js", () => {
  return {
    StreamableHTTPClientTransport: vi.fn().mockImplementation(() => ({
      close: vi.fn().mockResolvedValue(undefined),
    })),
  };
});

describe("McpClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates a client with the server URL", () => {
    const client = createMcpClient("https://hub.example.com/mcp/");
    expect(client).toBeDefined();
    expect(client.isConnected()).toBe(false);
  });

  it("connects and marks as connected", async () => {
    const client = createMcpClient("https://hub.example.com/mcp/");
    await client.connect();
    expect(client.isConnected()).toBe(true);
  });

  it("registerSession calls register_session tool", async () => {
    const { Client } = await import(
      "@modelcontextprotocol/sdk/client/index.js"
    );
    const mockCallTool = vi.fn().mockResolvedValue({
      content: [
        {
          type: "text",
          text: JSON.stringify({
            session_id: "s1",
            user_id: "u1",
            name: "Test User",
            scopes: ["memory:read", "memory:write"],
            project_memberships: ["proj-1"],
          }),
        },
      ],
    });
    (Client as unknown as ReturnType<typeof vi.fn>).mockImplementation(() => ({
      connect: vi.fn().mockResolvedValue(undefined),
      callTool: mockCallTool,
    }));

    const client = createMcpClient("https://hub.example.com/mcp/");
    const session = await client.registerSession("mh-dev-abc");

    expect(mockCallTool).toHaveBeenCalledWith({
      name: "register_session",
      arguments: { api_key: "mh-dev-abc" },
    });
    expect(session.sessionId).toBe("s1");
    expect(session.userId).toBe("u1");
    expect(session.name).toBe("Test User");
    expect(session.scopes).toEqual(["memory:read", "memory:write"]);
    expect(session.projectMemberships).toEqual(["proj-1"]);
  });

  it("callMemory calls memory tool with action and params", async () => {
    const { Client } = await import(
      "@modelcontextprotocol/sdk/client/index.js"
    );
    const mockCallTool = vi.fn().mockResolvedValue({
      content: [
        {
          type: "text",
          text: JSON.stringify({
            results: [{ id: "m1", content: "test" }],
          }),
        },
      ],
    });
    (Client as unknown as ReturnType<typeof vi.fn>).mockImplementation(() => ({
      connect: vi.fn().mockResolvedValue(undefined),
      callTool: mockCallTool,
    }));

    const client = createMcpClient("https://hub.example.com/mcp/");
    const result = await client.callMemory("search", {
      query: "test query",
      options: { max_results: 5 },
    });

    expect(mockCallTool).toHaveBeenCalledWith({
      name: "memory",
      arguments: {
        action: "search",
        query: "test query",
        options: { max_results: 5 },
      },
    });
    expect(result).toEqual({
      results: [{ id: "m1", content: "test" }],
    });
  });

  it("throws McpClientError on isError response", async () => {
    const { Client } = await import(
      "@modelcontextprotocol/sdk/client/index.js"
    );
    const mockCallTool = vi.fn().mockResolvedValue({
      isError: true,
      content: [{ type: "text", text: "Invalid API key" }],
    });
    (Client as unknown as ReturnType<typeof vi.fn>).mockImplementation(() => ({
      connect: vi.fn().mockResolvedValue(undefined),
      callTool: mockCallTool,
    }));

    const client = createMcpClient("https://hub.example.com/mcp/");
    await expect(
      client.callMemory("search", { query: "test" }),
    ).rejects.toThrow(McpClientError);
    await expect(
      client.callMemory("search", { query: "test" }),
    ).rejects.toThrow("Invalid API key");
  });

  it("propagates auth errors from callMemory without retrying", async () => {
    const { Client } = await import(
      "@modelcontextprotocol/sdk/client/index.js"
    );
    const mockCallTool = vi.fn().mockImplementation(({ name }: { name: string }) => {
      if (name === "register_session") {
        return Promise.resolve({
          content: [{ type: "text", text: JSON.stringify({ session_id: "s2", user_id: "u1", name: "User", scopes: [], project_memberships: [] }) }],
        });
      }
      return Promise.resolve({
        isError: true,
        content: [{ type: "text", text: "Authentication required. Provide a JWT or call register_session." }],
      });
    });
    (Client as unknown as ReturnType<typeof vi.fn>).mockImplementation(() => ({
      connect: vi.fn().mockResolvedValue(undefined),
      callTool: mockCallTool,
    }));

    const client = createMcpClient("https://hub.example.com/mcp/");
    await client.registerSession("mh-dev-abc");
    await expect(client.callMemory("list", {})).rejects.toThrow("Authentication required");
    expect(mockCallTool).toHaveBeenCalledTimes(2);
  });

  it("does not retry callMemory if no stored API key", async () => {
    const { Client } = await import(
      "@modelcontextprotocol/sdk/client/index.js"
    );
    const mockCallTool = vi.fn().mockResolvedValue({
      isError: true,
      content: [{ type: "text", text: "Authentication required. Provide a JWT or call register_session." }],
    });
    (Client as unknown as ReturnType<typeof vi.fn>).mockImplementation(() => ({
      connect: vi.fn().mockResolvedValue(undefined),
      callTool: mockCallTool,
    }));

    const client = createMcpClient("https://hub.example.com/mcp/");
    await expect(client.callMemory("list", {})).rejects.toThrow("Authentication required");
  });

  it("close resets connection state", async () => {
    const client = createMcpClient("https://hub.example.com/mcp/");
    await client.connect();
    expect(client.isConnected()).toBe(true);

    await client.close();
    expect(client.isConnected()).toBe(false);
  });
});
