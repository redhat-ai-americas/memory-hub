import { vi } from "vitest";
import type { MemoryHubMcpClient, SessionInfo } from "../src/mcp-client.js";
import type { PluginLogger } from "../src/openclaw-plugin-sdk.js";

export function createMockMcpClient(
  overrides?: Partial<MemoryHubMcpClient>,
): MemoryHubMcpClient {
  return {
    connect: vi.fn().mockResolvedValue(undefined),
    registerSession: vi.fn().mockResolvedValue({
      sessionId: "test-session-id",
      userId: "test-user",
      name: "Test User",
      scopes: ["memory:read", "memory:write"],
      projectMemberships: [],
    } satisfies SessionInfo),
    callMemory: vi.fn().mockResolvedValue({}),
    close: vi.fn().mockResolvedValue(undefined),
    isConnected: vi.fn().mockReturnValue(true),
    ...overrides,
  };
}

export function createMockLogger(): PluginLogger {
  return {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };
}
