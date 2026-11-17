import { vi } from "vitest";
import { defineAdapterConformance } from "../../common/tests/conformance.js";
import type { AdapterConformanceHarness } from "../../common/tests/conformance.js";
import type { MemoryHubMcpClient, SharedPluginConfig } from "../../common/src/types.js";
import { createSessionManager } from "../src/session.js";
import { createRecallEngine } from "../src/hooks.js";
import { resolveConfig } from "../src/config.js";
import { createTools } from "../src/tools.js";

const logger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
};

const harness: AdapterConformanceHarness = {
  name: "OpenCode",
  resolveConfig(options) {
    return resolveConfig(options, {
      env: {},
      home: "/tmp/memoryhub-conformance-home",
    });
  },
  createSession(client, apiKey, sessionLogger) {
    return createSessionManager(client, apiKey, sessionLogger);
  },
  async runTool(client, config, withSession, name, args) {
    const tools = createTools(
      client as MemoryHubMcpClient,
      config as SharedPluginConfig,
      withSession,
    );
    const tool = tools[name];
    if (!tool) throw new Error(`Missing OpenCode tool: ${name}`);
    return tool.execute(args as never, {} as never);
  },
  async runRecall(client, config, withSession, query) {
    const recall = createRecallEngine(
      client as MemoryHubMcpClient,
      config as SharedPluginConfig,
      logger,
      withSession,
    );
    await recall.onChatMessage({ parts: [{ type: "text", text: query }] });
    return recall.pendingBlock() ?? undefined;
  },
};

defineAdapterConformance(harness);
