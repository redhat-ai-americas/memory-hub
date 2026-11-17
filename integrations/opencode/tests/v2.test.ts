import { describe, expect, it, vi } from "vitest";

const close = vi.fn(async () => undefined);
const callMemory = vi.fn(async () => ({ memories: [{ content: "recalled" }] }));
const dispose = vi.fn(async () => undefined);
const toolTransform = vi.fn(async (callback: (editor: any) => void) => {
  callback({ add: (tool: any) => tools.push(tool) });
  return { dispose };
});
const sessionHook = vi.fn(async () => ({ dispose }));
const tools: any[] = [];

vi.mock("@opencode/plugin", () => ({
  Plugin: { define: (plugin: unknown) => plugin },
}));

vi.mock("../src/config.js", () => ({
  resolveConfig: () => ({
    needsSetup: false,
    server: { url: "https://example.com/mcp/" },
    auth: { apiKey: "test-key" },
    autoRecall: { enabled: true, maxResults: 10, maxResponseTokens: 4000 },
    defaults: { scope: "user", domains: [] },
  }),
}));

vi.mock("../src/logger.js", () => ({
  createLogger: () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
}));

vi.mock("../src/mcp-client.js", () => ({
  createMcpClient: () => ({ close, callMemory }),
}));

vi.mock("../src/session.js", () => ({
  createSessionManager: () => ({ withSession: (fn: () => Promise<unknown>) => fn() }),
}));

vi.mock("../../common/src/recall.js", () => ({
  searchWithTimeout: vi.fn(async () => [{ content: "recalled" }]),
  formatMemories: vi.fn(() => "<relevant-memories>recalled</relevant-memories>"),
}));

import { V2MemoryHubPlugin } from "../src/v2.js";
import { PROTOCOL_CONTENT } from "../../common/src/protocol.js";
import { DEFAULT_MEMORY_TOOL_NAMES } from "../../common/src/memory-operations.js";

describe("OpenCode V2 plugin", () => {
  it("preserves tools, recall, protocol injection, and cleanup", async () => {
    const cleanup = await V2MemoryHubPlugin.setup({
      options: {},
      tool: { transform: toolTransform },
      session: { hook: sessionHook },
    } as any);

    expect(tools.map((tool) => tool.name)).toEqual([...DEFAULT_MEMORY_TOOL_NAMES]);

    const result = await tools[0].execute({ query: "where is this?" }, {});
    expect(result.content).toContain("MemoryHub search");
    expect(result.content).not.toContain("type");

    const prompt = { prompt: { text: "What did we decide about memory?" } };
    const promptHook = sessionHook.mock.calls.find(([name]) => name === "prompt")?.[1];
    await promptHook(prompt);
    expect(prompt.prompt.text).toContain("<relevant-memories>");

    const context = { system: [] as Array<{ type: string; text: string }> };
    const contextHook = sessionHook.mock.calls.find(([name]) => name === "context")?.[1];
    await contextHook(context);
    expect(context.system).toContainEqual({ type: "text", text: PROTOCOL_CONTENT });

    await cleanup?.();
    expect(dispose).toHaveBeenCalledTimes(3);
    expect(close).toHaveBeenCalledOnce();
  });
});
