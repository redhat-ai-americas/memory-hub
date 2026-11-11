import { vi } from "vitest";
import { defineAdapterConformance } from "../../common/tests/conformance.js";
import type { AdapterConformanceHarness } from "../../common/tests/conformance.js";
import type { MemoryHubMcpClient } from "../../common/src/types.js";
import type { MemoryHubConfig } from "../src/config.js";
import { parseConfig } from "../src/config.js";
import { createBeforePromptBuildHook } from "../src/hooks.js";
import { createSessionManager } from "../../common/src/session.js";
import { createTools } from "../src/tools.js";

const logger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
};

const harness: AdapterConformanceHarness = {
  name: "OpenClaw",
  resolveConfig(options) {
    return parseConfig(options);
  },
  createSession(client, apiKey, sessionLogger) {
    return createSessionManager(client, apiKey, sessionLogger);
  },
  async runTool(client, config, withSession, name, args) {
    const tools = createTools(
      client as MemoryHubMcpClient,
      config as MemoryHubConfig,
      withSession,
    );
    const tool = tools.find((candidate) => candidate.name === name);
    if (!tool) throw new Error(`Missing OpenClaw tool: ${name}`);
    return tool.execute("conformance-call", args);
  },
  async runRecall(client, config, withSession, query) {
    const hook = createBeforePromptBuildHook(
      client as MemoryHubMcpClient,
      config as MemoryHubConfig,
      logger,
      undefined,
      withSession,
    );
    const result = await hook(
      { messages: [{ role: "user", content: query }] } as never,
      {} as never,
    );
    return result?.prependContext;
  },
};

defineAdapterConformance(harness);
