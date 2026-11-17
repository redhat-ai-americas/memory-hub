import type { MemoryHubMcpClient } from "./mcp-client.js";
import type { MemoryHubConfig } from "./config.js";
import type { Logger } from "./logger.js";
import {
  formatMemories as formatMemoriesXml,
  searchWithTimeout,
} from "../../common/src/recall.js";

const MIN_QUERY_LENGTH = 5;

/** Host-required part identity fields carried onto injected parts. */
const PART_IDENTITY_FIELDS = ["id", "sessionID", "messageID"] as const;

/** Marker used both as the injected block opener and for dedup checks. */
export const MEMORY_BLOCK_MARKER = "<relevant-memories>";

export { formatMemoriesXml };

/**
 * Loosely-typed message part. The real opencode `Part` union is wider; we
 * only read text parts and only ever copy identity fields off any other.
 */
export interface LoosePart {
  type?: string;
  text?: string;
  synthetic?: boolean;
  [key: string]: unknown;
}

export interface LooseMessage {
  info?: { role?: string; [key: string]: unknown };
  parts: LoosePart[];
}

export function extractTextFromParts(parts: LoosePart[]): string {
  return parts
    .filter(
      (p) =>
        p.type === "text" &&
        typeof p.text === "string" &&
        !p.synthetic &&
        !p.text.startsWith(MEMORY_BLOCK_MARKER),
    )
    .map((p) => p.text as string)
    .join("\n");
}

export interface RecallEngine {
  /** Wire to the `chat.message` hook: searches MemoryHub for the new user message. */
  onChatMessage(output: { parts: LoosePart[] }): Promise<void>;
  /**
   * Wire to `experimental.chat.messages.transform`: injects the pending
   * memory block into the latest user message. Idempotent — re-injection is
   * skipped when the target message already carries the marker, and the
   * block is re-applied on every request of the turn otherwise (the
   * transform output is per-request, not persisted to the session).
   */
  onMessagesTransform(output: { messages: LooseMessage[] }): void;
  /** Test/introspection helper. */
  pendingBlock(): string | null;
}

export function createRecallEngine(
  mcpClient: MemoryHubMcpClient,
  config: MemoryHubConfig,
  logger: Logger,
  withSession: <T>(fn: () => Promise<T>) => Promise<T>,
): RecallEngine {
  let pending: string | null = null;

  async function onChatMessage(output: { parts: LoosePart[] }): Promise<void> {
    if (!config.autoRecall.enabled) return;

    const userText = extractTextFromParts(output.parts ?? []);
    if (userText.length < MIN_QUERY_LENGTH) {
      pending = null;
      return;
    }

    try {
      const results = await searchWithTimeout(
        mcpClient,
        userText,
        config,
        withSession,
      );
      pending = results.length > 0 ? formatMemoriesXml(results) : null;
    } catch (e) {
      pending = null;
      logger.warn(
        `auto-recall failed: ${e instanceof Error ? e.message : "unknown error"}`,
      );
    }
  }

  function onMessagesTransform(output: { messages: LooseMessage[] }): void {
    if (!pending) return;

    const messages = output.messages ?? [];
    let target: LooseMessage | undefined;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i]?.info?.role === "user") {
        target = messages[i];
        break;
      }
    }
    if (!target || target.parts.length === 0) return;

    if (
      target.parts.some(
        (p) => p.type === "text" && p.text?.includes(MEMORY_BLOCK_MARKER),
      )
    ) {
      return;
    }

    // Build a fresh text part; copy only the host-required identity fields
    // from a sibling (preferring a text part) so no type-specific fields of
    // an image/file part leak onto it.
    const ref = target.parts.find((p) => p.type === "text") ?? target.parts[0];
    const injected: LoosePart = { type: "text", text: pending, synthetic: true };
    for (const field of PART_IDENTITY_FIELDS) {
      if (ref[field] !== undefined) injected[field] = ref[field];
    }
    target.parts.unshift(injected);
  }

  return {
    onChatMessage,
    onMessagesTransform,
    pendingBlock: () => pending,
  };
}

/**
 * Wire to `experimental.chat.system.transform`: appends the MemoryHub
 * bundled protocol to the system prompt. Idempotent.
 */
export function createSystemTransform(protocolContent: string) {
  return (output: { system: string[] }): void => {
    if (!output.system.includes(protocolContent)) {
      output.system.push(protocolContent);
    }
  };
}
