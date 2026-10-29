import type { MemoryHubMcpClient } from "./mcp-client.js";
import type { MemoryHubConfig } from "./config.js";
import type { Logger } from "./logger.js";

/**
 * Opt-in trajectory recording (#554).
 *
 * Appends user messages and every tool call/result of an opencode session
 * to one MemoryHub conversation thread, so the dreaming pipeline can detect
 * and refine procedural graphs from real tool-call trajectories. Recording
 * never blocks or fails the host: errors are logged and dropped.
 */

/** MemoryHub's own tools are not part of the user's procedure. */
const SKIPPED_TOOL_PREFIX = "memoryhub_";

/**
 * Common secret shapes, redacted before anything leaves the machine. This is
 * a best-effort first line; the server's curation pipeline still scans
 * everything it derives from threads.
 */
const SECRET_PATTERNS: RegExp[] = [
  /AKIA[0-9A-Z]{16}/g,
  /gh[pousr]_[A-Za-z0-9]{36,}/g,
  /xox[abpr]-[A-Za-z0-9-]{10,}/g,
  /sk-[A-Za-z0-9_-]{20,}/g,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
  /(authorization:\s*bearer\s+)[A-Za-z0-9._~+/=-]{16,}/gi,
  /((?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)["']?[^\s"']{6,}/gi,
];

export function redactSecrets(text: string): string {
  let out = text;
  for (const pattern of SECRET_PATTERNS) {
    out = out.replace(pattern, (match, prefix?: unknown) =>
      typeof prefix === "string" && match.startsWith(prefix)
        ? `${prefix}[REDACTED]`
        : "[REDACTED]",
    );
  }
  return out;
}

export function clip(text: string, max: number): string {
  if (text.length <= max) return text;
  const head = Math.floor(max * 0.75);
  const tail = max - head;
  return `${text.slice(0, head)}\n[... ${text.length - max} chars omitted ...]\n${text.slice(-tail)}`;
}

export interface TrajectoryRecorder {
  onUserMessage(sessionID: string, text: string): Promise<void>;
  onToolExecuted(
    input: { tool: string; sessionID: string; callID: string; args: unknown },
    output: { title?: string; output?: string; metadata?: unknown },
  ): Promise<void>;
  /** Test/introspection helper. */
  threadFor(sessionID: string): Promise<string | undefined>;
}

export function createTrajectoryRecorder(
  mcpClient: MemoryHubMcpClient,
  config: MemoryHubConfig,
  logger: Logger,
  withSession: <T>(fn: () => Promise<T>) => Promise<T>,
): TrajectoryRecorder {
  const threads = new Map<string, Promise<string | undefined>>();
  // Appends for one session are chained so sequence numbers follow the
  // order events happened in, even when hooks fire concurrently.
  const queues = new Map<string, Promise<void>>();

  function ensureThread(sessionID: string): Promise<string | undefined> {
    let pending = threads.get(sessionID);
    if (!pending) {
      pending = withSession(async () => {
        const projectId = config.defaults.projectId;
        const options: Record<string, unknown> = {
          title: `opencode session ${sessionID.slice(0, 12)}`,
          metadata: { host: "opencode", host_session_id: sessionID },
        };
        if (projectId) options.scope_id = projectId;
        const created = (await mcpClient.callThread("create", {
          scope: projectId ? "project" : "user",
          options,
        })) as { id?: string };
        return created.id;
      }).catch((e: unknown) => {
        threads.delete(sessionID);
        logger.warn(
          `trajectory: could not create thread: ${e instanceof Error ? e.message : "unknown error"}`,
        );
        return undefined;
      });
      threads.set(sessionID, pending);
    }
    return pending;
  }

  function enqueue(
    sessionID: string,
    messages: Array<{ role: string; content: string; toolCallId?: string; metadata?: Record<string, unknown> }>,
  ): Promise<void> {
    const previous = queues.get(sessionID) ?? Promise.resolve();
    const next = previous.then(async () => {
      const threadId = await ensureThread(sessionID);
      if (!threadId) return;
      for (const m of messages) {
        const options: Record<string, unknown> = {};
        if (m.toolCallId) options.tool_call_id = m.toolCallId;
        if (m.metadata) options.metadata = m.metadata;
        try {
          await withSession(() =>
            mcpClient.callThread("append", {
              thread_id: threadId,
              role: m.role,
              content: m.content,
              options,
            }),
          );
        } catch (e) {
          logger.warn(
            `trajectory: append failed: ${e instanceof Error ? e.message : "unknown error"}`,
          );
          return;
        }
      }
    }).catch((e: unknown) => {
      logger.warn(
        `trajectory: recording failed: ${e instanceof Error ? e.message : "unknown error"}`,
      );
    });
    queues.set(sessionID, next);
    return next;
  }

  return {
    async onUserMessage(sessionID, text) {
      if (!config.recordTrajectory.enabled || !text.trim()) return;
      await enqueue(sessionID, [{ role: "user", content: redactSecrets(text) }]);
    },

    async onToolExecuted(input, output) {
      if (!config.recordTrajectory.enabled) return;
      if (input.tool.startsWith(SKIPPED_TOOL_PREFIX)) return;
      const max = config.recordTrajectory.maxToolOutputChars;
      let args: string;
      try {
        args = JSON.stringify({ tool: input.tool, args: input.args ?? {} });
      } catch {
        args = JSON.stringify({ tool: input.tool });
      }
      await enqueue(input.sessionID, [
        { role: "tool_call", content: clip(redactSecrets(args), max), toolCallId: input.callID },
        {
          role: "tool_result",
          content: clip(redactSecrets(output.output ?? output.title ?? ""), max) || "(no output)",
          toolCallId: input.callID,
        },
      ]);
    },

    threadFor: (sessionID) => threads.get(sessionID) ?? Promise.resolve(undefined),
  };
}
