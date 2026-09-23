import type { MemoryHubMcpClient } from "./mcp-client.js";
import type { Logger } from "./logger.js";

const AUTH_ERROR_FRAGMENTS = [
  "authentication required",
  "session not found",
  "session expired",
];

export function isAuthError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message.toLowerCase() : "";
  return AUTH_ERROR_FRAGMENTS.some((f) => msg.includes(f));
}

export interface SessionManager {
  ensureSession(): Promise<void>;
  /**
   * Run `fn` with a registered MemoryHub session. On a session-expiry error
   * the session is re-registered once and `fn` retried; other errors
   * propagate to the caller.
   */
  withSession<T>(fn: () => Promise<T>): Promise<T>;
}

export function createSessionManager(
  mcpClient: MemoryHubMcpClient,
  apiKey: string | undefined,
  logger: Logger,
): SessionManager {
  let registered = false;
  let inflight: Promise<void> | null = null;
  // Incremented each time a caller claims the reset for a failed session.
  // Concurrent callers that failed on the same (old) generation skip the
  // reset — otherwise the second failure would tear down the fresh
  // transport the first caller's retry is already using.
  let generation = 0;

  function ensureSession(): Promise<void> {
    if (registered) return Promise.resolve();
    inflight ??= (async () => {
      if (!mcpClient.isConnected()) {
        await mcpClient.connect();
      }
      if (apiKey) {
        const session = await mcpClient.registerSession(apiKey);
        logger.info(
          `session registered for ${session.name} (${session.userId})`,
        );
      }
      registered = true;
    })().finally(() => {
      inflight = null;
    });
    return inflight;
  }

  async function withSession<T>(fn: () => Promise<T>): Promise<T> {
    await ensureSession();
    const gen = generation;
    try {
      return await fn();
    } catch (error) {
      if (!isAuthError(error)) throw error;
      if (gen === generation) {
        generation++;
        logger.info("session expired, re-registering");
        registered = false;
        mcpClient.resetSession();
      }
      await ensureSession();
      return await fn();
    }
  }

  return { ensureSession, withSession };
}
