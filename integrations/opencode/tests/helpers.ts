import { vi } from "vitest";
import type { MemoryHubMcpClient, SessionInfo } from "../src/mcp-client.js";
import type { Logger } from "../src/logger.js";
import type { MemoryHubConfig } from "../src/config.js";

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
    resetSession: vi.fn(),
    ...overrides,
  };
}

export function createMockLogger(): Logger {
  return {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };
}

export function testConfig(
  overrides?: Partial<MemoryHubConfig>,
): MemoryHubConfig {
  return {
    server: { url: "https://memoryhub.example.com/mcp/" },
    auth: { apiKey: "mh-dev-0123456789abcdef" },
    autoRecall: { enabled: true, maxResults: 10, maxResponseTokens: 4000 },
    defaults: { scope: "user", projectId: undefined, domains: [] },
    needsSetup: false,
    ...overrides,
  };
}

/** withSession passthrough for tests that don't exercise session retry. */
export const passthroughSession = <T>(fn: () => Promise<T>): Promise<T> =>
  fn();
