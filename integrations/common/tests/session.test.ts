import { describe, expect, it, vi } from "vitest";
import { createSessionManager, isSessionError } from "../src/session.js";
import type { MemoryHubMcpClient } from "../src/types.js";

function makeClient(): MemoryHubMcpClient {
  return {
    connect: vi.fn().mockResolvedValue(undefined),
    registerSession: vi.fn().mockResolvedValue({
      sessionId: "s1", userId: "u1", name: "Test", scopes: [], projectMemberships: [],
    }),
    callMemory: vi.fn(),
    close: vi.fn().mockResolvedValue(undefined),
    isConnected: vi.fn().mockReturnValue(true),
    resetSession: vi.fn(),
  };
}

describe("shared session recovery", () => {
  it("matches errors returned by the current server", () => {
    expect(isSessionError(new Error("Authentication required"))).toBe(true);
    expect(isSessionError(new Error("Session expired"))).toBe(true);
    expect(isSessionError(new Error("session not found"))).toBe(true);
  });

  it("registers lazily and retries one operation once after expiry", async () => {
    const client = makeClient();
    const logger = { info: vi.fn() };
    const manager = createSessionManager(client, "test-key", logger);
    const operation = vi.fn()
      .mockRejectedValueOnce(new Error("Session expired"))
      .mockResolvedValueOnce("ok");

    expect(client.registerSession).not.toHaveBeenCalled();
    await expect(manager.withSession(operation)).resolves.toBe("ok");
    expect(client.registerSession).toHaveBeenCalledTimes(2);
    expect(client.resetSession).toHaveBeenCalledOnce();
    expect(operation).toHaveBeenCalledTimes(2);
  });

  it("recovers when the MCP transport reports a missing session", async () => {
    const client = makeClient();
    const manager = createSessionManager(client, "test-key", { info: vi.fn() });
    const operation = vi.fn()
      .mockRejectedValueOnce(new Error("Session not found"))
      .mockResolvedValueOnce("ok");

    await expect(manager.withSession(operation)).resolves.toBe("ok");
    expect(client.registerSession).toHaveBeenCalledTimes(2);
    expect(client.resetSession).toHaveBeenCalledOnce();
    expect(operation).toHaveBeenCalledTimes(2);
  });
});
