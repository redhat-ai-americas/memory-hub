import type { MemoryHubMcpClient } from "./mcp-client.js";
import type { MemoryHubConfig } from "./config.js";
import {
  formatMemories,
  searchWithTimeout,
} from "../../common/src/recall.js";
import type { PluginLogger } from "./openclaw-plugin-sdk.js";
import type {
  PluginHookBeforePromptBuildEvent,
  PluginHookBeforePromptBuildResult,
  PluginHookAgentEndEvent,
  PluginHookAgentContext,
} from "./openclaw-plugin-sdk.js";

const MIN_QUERY_LENGTH = 5;

function extractLatestUserText(messages: unknown[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i] as Record<string, unknown> | undefined;
    if (!msg) continue;
    const role = msg.role ?? msg.type;
    if (role !== "user" && role !== "human") continue;
    if (typeof msg.content === "string") return msg.content;
    if (Array.isArray(msg.content)) {
      const textParts = (msg.content as Array<Record<string, unknown>>)
        .filter((p) => p.type === "text" && typeof p.text === "string")
        .map((p) => p.text as string);
      if (textParts.length > 0) return textParts.join("\n");
    }
  }
  return "";
}

function extractRecallQuery(event: PluginHookBeforePromptBuildEvent): string {
  const latestUserText = extractLatestUserText(event.messages).trim();
  if (latestUserText) return latestUserText;

  // OpenClaw may provide the current input in `prompt` without a user entry
  // in `messages`. Use it as a fallback so auto-recall still runs in that case.
  return typeof event.prompt === "string" ? event.prompt.trim() : "";
}

export function createBeforePromptBuildHook(
  mcpClient: MemoryHubMcpClient,
  config: MemoryHubConfig,
  logger: PluginLogger,
  protocolContent?: string,
  withSession: <T>(operation: () => Promise<T>) => Promise<T> = (operation) =>
    operation(),
) {
  return async (
    event: PluginHookBeforePromptBuildEvent,
    _ctx: PluginHookAgentContext,
  ): Promise<PluginHookBeforePromptBuildResult | void> => {
    const result: PluginHookBeforePromptBuildResult = {};

    if (protocolContent) {
      result.prependSystemContext = protocolContent;
    }

    if (!config.autoRecall.enabled) {
      return protocolContent ? result : undefined;
    }

    const userText = extractRecallQuery(event);
    if (!userText) {
      logger.debug(
        "memoryhub: auto-recall skipped because the prompt event had no query text",
      );
      return protocolContent ? result : undefined;
    }
    if (userText.length < MIN_QUERY_LENGTH) {
      return protocolContent ? result : undefined;
    }

    try {
      const results = await searchWithTimeout(
        mcpClient,
        userText,
        config,
        withSession,
      );
      if (results.length === 0) {
        return protocolContent ? result : undefined;
      }

      const xml = formatMemories(results);
      result.prependContext = xml;
      return result;
    } catch (e) {
      logger.warn(
        `memoryhub: auto-recall failed: ${e instanceof Error ? e.message : "unknown error"}`,
      );
      return protocolContent ? result : undefined;
    }
  };
}

export function createAgentEndHook(
  _mcpClient: MemoryHubMcpClient,
  config: MemoryHubConfig,
  logger: PluginLogger,
) {
  return async (
    _event: PluginHookAgentEndEvent,
    _ctx: PluginHookAgentContext,
  ): Promise<void> => {
    if (!config.autoCapture.enabled) return;
    logger.info("memoryhub: auto-capture not yet implemented");
  };
}
