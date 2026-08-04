import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";
import { parseConfig } from "./config.js";
import { createMcpClient } from "./mcp-client.js";
import { createTools } from "./tools.js";
import { createBeforePromptBuildHook, createAgentEndHook } from "./hooks.js";

function loadProtocolContent(): string | undefined {
  try {
    const selfDir = dirname(fileURLToPath(import.meta.url));
    const protocolPath = resolve(selfDir, "..", "memoryhub-rules.md");
    return readFileSync(protocolPath, "utf-8");
  } catch {
    return undefined;
  }
}

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
    const protocolContent = loadProtocolContent();
    if (protocolContent) {
      api.logger.info("memoryhub: loaded memory protocol for system context");
    } else {
      api.logger.warn("memoryhub: memoryhub-rules.md not found, skipping system context injection");
    }
    let sessionRegistered = false;

    async function ensureSession(): Promise<void> {
      if (sessionRegistered) return;
      if (!mcpClient.isConnected()) {
        await mcpClient.connect();
      }
      if (config.auth.apiKey) {
        const session = await mcpClient.registerSession(config.auth.apiKey);
        api.logger.info(
          `memoryhub: session registered for ${session.name} (${session.userId})`,
        );
      }
      sessionRegistered = true;
    }

    function handleSessionError(): void {
      sessionRegistered = false;
      mcpClient.resetSession();
    }

    // V1: empty capability — runtime, promptBuilder, publicArtifacts, flushPlanResolver deferred
    api.registerMemoryCapability({});

    const tools = createTools(mcpClient, config);
    for (const tool of tools) {
      const originalExecute = tool.execute.bind(tool);
      tool.execute = async (toolCallId, params, signal) => {
        await ensureSession();
        try {
          return await originalExecute(toolCallId, params, signal);
        } catch (error) {
          const msg = error instanceof Error ? error.message.toLowerCase() : "";
          if (msg.includes("authentication required") ||
              msg.includes("session not found") ||
              msg.includes("session expired")) {
            api.logger.info("memoryhub: session expired, re-registering");
            handleSessionError();
            await ensureSession();
            return originalExecute(toolCallId, params, signal);
          }
          throw error;
        }
      };
      api.registerTool(tool, { name: tool.name });
    }

    api.on(
      "before_prompt_build" as never,
      async (...args: unknown[]) => {
        await ensureSession();
        const handler = createBeforePromptBuildHook(
          mcpClient,
          config,
          api.logger,
          protocolContent,
        );
        try {
          return await handler(args[0] as never, args[1] as never);
        } catch (error) {
          const msg = error instanceof Error ? error.message.toLowerCase() : "";
          if (msg.includes("authentication required") ||
              msg.includes("session not found") ||
              msg.includes("session expired")) {
            api.logger.info("memoryhub: session expired during auto-recall, re-registering");
            handleSessionError();
            await ensureSession();
            return handler(args[0] as never, args[1] as never);
          }
          throw error;
        }
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
