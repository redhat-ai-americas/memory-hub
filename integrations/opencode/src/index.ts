import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import type { Plugin, Hooks } from "@opencode-ai/plugin";
import { resolveConfig } from "./config.js";
import { createMcpClient } from "./mcp-client.js";
import { createTools } from "./tools.js";
import { createRecallEngine, createSystemTransform } from "./hooks.js";
import { createSessionManager } from "./session.js";
import { createLogger } from "./logger.js";

function loadProtocolContent(): string | undefined {
  try {
    const selfDir = dirname(fileURLToPath(import.meta.url));
    const protocolPath = resolve(selfDir, "..", "memoryhub-rules.md");
    return readFileSync(protocolPath, "utf-8");
  } catch {
    return undefined;
  }
}

/**
 * MemoryHub plugin for opencode.
 *
 * Configure via opencode.json:
 *   "plugin": [["@memory-hub/opencode-mh-plugin", { "server": { "url": "..." } }]]
 * or via MEMORYHUB_URL / MEMORYHUB_API_KEY env vars, or
 * ~/.config/memoryhub/credentials. The API key never enters the model's
 * context — the plugin calls register_session host-side.
 */
export const MemoryHubPlugin: Plugin = async (_input, options) => {
  const logger = createLogger();
  const config = resolveConfig(options);

  if (config.needsSetup) {
    logger.warn(
      "missing server URL or API key — plugin disabled. " +
        "Set MEMORYHUB_URL and MEMORYHUB_API_KEY, populate " +
        "~/.config/memoryhub/credentials, or pass options in opencode.json " +
        'under "plugin": [["@memory-hub/opencode-mh-plugin", {...}]]',
    );
    return {};
  }

  const mcpClient = createMcpClient(config.server.url);
  const protocolContent = loadProtocolContent();
  if (!protocolContent) {
    logger.warn(
      "memoryhub-rules.md not found, skipping system context injection",
    );
  }

  const { withSession } = createSessionManager(
    mcpClient,
    config.auth.apiKey,
    logger,
  );
  const recall = createRecallEngine(mcpClient, config, logger, withSession);

  logger.info(`initialized (server: ${config.server.url})`);

  const hooks: Hooks = {
    tool: createTools(mcpClient, config, withSession),

    "chat.message": async (_input, output) => {
      await recall.onChatMessage(output);
    },

    "experimental.chat.messages.transform": async (_input, output) => {
      recall.onMessagesTransform(output);
    },

    dispose: async () => {
      await mcpClient.close();
      logger.info("stopped");
    },
  };

  if (protocolContent) {
    const systemTransform = createSystemTransform(protocolContent);
    hooks["experimental.chat.system.transform"] = async (_input, output) => {
      systemTransform(output);
    };
  }

  return hooks;
};

export { resolveConfig } from "./config.js";
export { createMcpClient, McpClientError } from "./mcp-client.js";
export { createSessionManager, isAuthError } from "./session.js";
export type { MemoryHubConfig } from "./config.js";
export type { MemoryHubMcpClient, SessionInfo } from "./mcp-client.js";
