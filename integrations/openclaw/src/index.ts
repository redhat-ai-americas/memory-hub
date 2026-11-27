import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";
import { PROTOCOL_CONTENT } from "../../common/src/protocol.js";
import { createSessionManager } from "../../common/src/session.js";
import { parseConfig } from "./config.js";
import { createMcpClient } from "./mcp-client.js";
import { createTools } from "./tools.js";
import { createBeforePromptBuildHook, createAgentEndHook } from "./hooks.js";

const memoryHubPlugin = definePluginEntry({
  id: "openclaw-memoryhub",
  name: "Memory (MemoryHub)",
  description:
    "MemoryHub memory backend for OpenClaw — governed, versioned, graph-aware agent memory with semantic search, focus-aware retrieval, and multi-scope hierarchy.",
  kind: "memory" as const,

  register(api: OpenClawPluginApi) {
    const config = parseConfig(api.pluginConfig);

    if (config.needsSetup) {
      api.logger.warn(
        "memoryhub: missing server.url or auth.apiKey — plugin disabled. " +
          "Configure in openclaw.json under plugins.entries.openclaw-memoryhub.config",
      );
      api.registerService({
        id: "openclaw-memoryhub",
        start() {
          api.logger.info("memoryhub: plugin not configured, service inactive");
        },
      });
      return;
    }

    const mcpClient = createMcpClient(config.server.url);
    api.logger.info("memoryhub: loaded memory protocol for system context");
    const session = createSessionManager(
      mcpClient,
      config.auth.apiKey,
      api.logger,
    );

    // V1: empty capability — runtime, promptBuilder, publicArtifacts, flushPlanResolver deferred
    api.registerMemoryCapability({});

    const tools = createTools(mcpClient, config, session.withSession);
    for (const tool of tools) {
      api.registerTool(tool, { name: tool.name });
    }

    api.on(
      "before_prompt_build" as never,
      async (...args: unknown[]) => {
        const handler = createBeforePromptBuildHook(
          mcpClient,
          config,
          api.logger,
          PROTOCOL_CONTENT,
          session.withSession,
        );
        return handler(args[0] as never, args[1] as never);
      },
      { timeoutMs: 20_000 },
    );

    api.on(
      "agent_end" as never,
      async (...args: unknown[]) => {
        const handler = createAgentEndHook(mcpClient, config, api.logger);
        return handler(args[0] as never, args[1] as never);
      },
    );

    api.registerService({
      id: "openclaw-memoryhub",
      start() {
        api.logger.info(
          `memoryhub: initialized (server: ${config.server.url})`,
        );
      },
      async stop() {
        await mcpClient.close();
        api.logger.info("memoryhub: stopped");
      },
    });
  },
});

export default memoryHubPlugin;
export { parseConfig } from "./config.js";
export { createMcpClient } from "./mcp-client.js";
export type { MemoryHubConfig } from "./config.js";
export type { MemoryHubMcpClient, SessionInfo } from "./mcp-client.js";
