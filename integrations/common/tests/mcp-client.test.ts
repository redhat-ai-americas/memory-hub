import { describe, expect, it, vi } from "vitest";
import { createMcpClient, McpClientError } from "../src/mcp-client.js";
import type { McpRuntime } from "../src/mcp-client.js";

function createRuntime() {
  const callTool = vi.fn().mockResolvedValue({
    content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
  });
  const connect = vi.fn().mockResolvedValue(undefined);
  const close = vi.fn().mockResolvedValue(undefined);
  const runtime: McpRuntime = {
    createTransport: vi.fn(() => ({ close })),
    createClient: vi.fn(() => ({ connect, callTool })),
  };
  return { runtime, callTool, connect, close };
}

describe("shared MCP client", () => {
  it("shares concurrent connection attempts and forwards allow-listed arguments", async () => {
    const { runtime, callTool, connect } = createRuntime();
    const client = createMcpClient("https://hub.example/mcp/", runtime);
    await Promise.all([client.connect(), client.connect()]);
    expect(connect).toHaveBeenCalledOnce();
    await client.callMemory("write", {
      content: "fact", scope: "user", options: { weight: 0.8 }, ignored: true,
    });
    expect(callTool).toHaveBeenCalledWith({
      name: "memory",
      arguments: { action: "write", content: "fact", scope: "user", options: { weight: 0.8 } },
    });
  });

  it("closes failed transports and can connect again", async () => {
    const { runtime, connect, close } = createRuntime();
    connect.mockRejectedValueOnce(new Error("connection failed"));
    const client = createMcpClient("https://hub.example/mcp/", runtime);
    await expect(client.connect()).rejects.toThrow("connection failed");
    expect(close).toHaveBeenCalledOnce();
    await client.connect();
    expect(client.isConnected()).toBe(true);
  });

  it("turns MCP tool errors into bounded client errors", async () => {
    const { runtime, callTool } = createRuntime();
    callTool.mockResolvedValueOnce({
      isError: true,
      content: [{ type: "text", text: "Authentication required" }],
    });
    const client = createMcpClient("https://hub.example/mcp/", runtime);
    await expect(client.callMemory("search", { query: "q" }))
      .rejects.toBeInstanceOf(McpClientError);
  });
});
