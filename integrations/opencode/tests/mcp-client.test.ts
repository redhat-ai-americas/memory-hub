import { describe, it, expect, vi, beforeEach } from "vitest";

const mockCallTool = vi.fn();
const mockConnect = vi.fn();
const mockTransportClose = vi.fn().mockResolvedValue(undefined);

vi.mock("@modelcontextprotocol/sdk/client/index.js", () => ({
  Client: vi.fn().mockImplementation(() => ({
    connect: mockConnect,
    callTool: mockCallTool,
  })),
}));

vi.mock("@modelcontextprotocol/sdk/client/streamableHttp.js", () => ({
  StreamableHTTPClientTransport: vi.fn().mockImplementation(() => ({
    close: mockTransportClose,
  })),
}));

import { createMcpClient, McpClientError } from "../src/mcp-client.js";

function textResult(data: unknown) {
  return { content: [{ type: "text", text: JSON.stringify(data) }] };
}

beforeEach(() => {
  mockCallTool.mockReset();
  mockConnect.mockReset().mockResolvedValue(undefined);
  mockTransportClose.mockClear();
});

describe("createMcpClient", () => {
  it("connects lazily and only once", async () => {
    const client = createMcpClient("https://example.com/mcp/");
    expect(client.isConnected()).toBe(false);
    mockCallTool.mockResolvedValue(textResult({}));
    await client.callMemory("search", { query: "x" });
    await client.callMemory("search", { query: "y" });
    expect(mockConnect).toHaveBeenCalledTimes(1);
    expect(client.isConnected()).toBe(true);
  });

  it("registerSession maps snake_case response fields", async () => {
    mockCallTool.mockResolvedValue(
      textResult({
        session_id: "s1",
        user_id: "u1",
        name: "Test",
        scopes: ["memory:read"],
        project_memberships: ["p1"],
      }),
    );
    const client = createMcpClient("https://example.com/mcp/");
    const session = await client.registerSession("mh-dev-abc");
    expect(mockCallTool).toHaveBeenCalledWith({
      name: "register_session",
      arguments: { api_key: "mh-dev-abc" },
    });
    expect(session).toEqual({
      sessionId: "s1",
      userId: "u1",
      name: "Test",
      scopes: ["memory:read"],
      projectMemberships: ["p1"],
    });
  });

  it("callMemory forwards only allow-listed keys", async () => {
    mockCallTool.mockResolvedValue(textResult({ ok: true }));
    const client = createMcpClient("https://example.com/mcp/");
    await client.callMemory("write", {
      content: "fact",
      scope: "user",
      options: { weight: 0.9 },
      bogus: "dropped",
    });
    expect(mockCallTool).toHaveBeenCalledWith({
      name: "memory",
      arguments: {
        action: "write",
        content: "fact",
        scope: "user",
        options: { weight: 0.9 },
      },
    });
  });

  it("parses single-text-part JSON results", async () => {
    mockCallTool.mockResolvedValue(textResult({ results: [{ id: "m1" }] }));
    const client = createMcpClient("https://example.com/mcp/");
    const result = await client.callMemory("search", { query: "x" });
    expect(result).toEqual({ results: [{ id: "m1" }] });
  });

  it("returns raw text when the payload is not JSON", async () => {
    mockCallTool.mockResolvedValue({
      content: [{ type: "text", text: "plain text" }],
    });
    const client = createMcpClient("https://example.com/mcp/");
    const result = await client.callMemory("read", { memory_id: "m1" });
    expect(result).toBe("plain text");
  });

  it("throws McpClientError on isError results", async () => {
    mockCallTool.mockResolvedValue({
      isError: true,
      content: [{ type: "text", text: "Session expired" }],
    });
    const client = createMcpClient("https://example.com/mcp/");
    await expect(client.callMemory("search", { query: "x" })).rejects.toThrow(
      McpClientError,
    );
  });

  it("resetSession closes the stale transport and reconnects on next call", async () => {
    mockCallTool.mockResolvedValue(textResult({}));
    const client = createMcpClient("https://example.com/mcp/");
    await client.callMemory("search", { query: "x" });
    client.resetSession();
    expect(client.isConnected()).toBe(false);
    expect(mockTransportClose).toHaveBeenCalledTimes(1);
    await client.callMemory("search", { query: "y" });
    expect(mockConnect).toHaveBeenCalledTimes(2);
  });

  it("close shuts the transport down", async () => {
    mockCallTool.mockResolvedValue(textResult({}));
    const client = createMcpClient("https://example.com/mcp/");
    await client.callMemory("search", { query: "x" });
    await client.close();
    expect(mockTransportClose).toHaveBeenCalledTimes(1);
    expect(client.isConnected()).toBe(false);
  });
});
