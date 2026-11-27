import type { MemoryHubMcpClient, SessionInfo } from "./types.js";

const AUTH_ERROR_FRAGMENTS = [
  "authentication required",
  "session expired",
  "session not found",
];

export interface SessionLogger {
  info(message: string): void;
}

export interface SessionManager {
  ensureSession(): Promise<void>;
  withSession<T>(operation: () => Promise<T>): Promise<T>;
}

export function isSessionError(error: unknown): boolean {
  const message = error instanceof Error ? error.message.toLowerCase() : "";
  return AUTH_ERROR_FRAGMENTS.some((fragment) => message.includes(fragment));
}

export function createSessionManager(
  client: MemoryHubMcpClient,
  apiKey: string | undefined,
  logger: SessionLogger,
): SessionManager {
  let registered = false;
  let registering: Promise<void> | null = null;
  let generation = 0;

  function ensureSession(): Promise<void> {
    if (registered) return Promise.resolve();
    registering ??= (async () => {
      if (!client.isConnected()) await client.connect();
      if (apiKey) {
        const session: SessionInfo = await client.registerSession(apiKey);
        logger.info(`session registered for ${session.name} (${session.userId})`);
      }
      registered = true;
    })().finally(() => {
      registering = null;
    });
    return registering;
  }

  async function withSession<T>(operation: () => Promise<T>): Promise<T> {
    await ensureSession();
    const operationGeneration = generation;
    try {
      return await operation();
    } catch (error) {
      if (!isSessionError(error)) throw error;
      if (operationGeneration === generation) {
        generation++;
        registered = false;
        logger.info("session expired, re-registering");
        client.resetSession();
      }
      await ensureSession();
      return operation();
    }
  }

  return { ensureSession, withSession };
}
