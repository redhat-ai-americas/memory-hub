/**
 * Type declarations for the OpenClaw Plugin SDK.
 *
 * These are the minimal types needed by the MemoryHub plugin.
 * The real types come from the `openclaw` peer dependency at runtime.
 */

import type { TSchema, Static } from "@sinclair/typebox";

// -- Logger --

export interface PluginLogger {
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
  debug(message: string, ...args: unknown[]): void;
}

// -- Memory Capability --

export interface MemoryPluginCapability {
  promptBuilder?: unknown;
  flushPlanResolver?: unknown;
  runtime?: unknown;
  publicArtifacts?: unknown;
}

// -- Service --

export interface OpenClawPluginService {
  id: string;
  start: (...args: unknown[]) => void | Promise<void>;
  stop?: (...args: unknown[]) => void | Promise<void>;
}

// -- Tools --

export interface AgentToolResult<TDetails = unknown> {
  content: Array<{ type: "text"; text: string }>;
  details?: TDetails;
}

export interface AnyAgentTool {
  name: string;
  label: string;
  description: string;
  parameters: TSchema;
  execute(
    toolCallId: string,
    params: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<AgentToolResult>;
}

// -- Hooks --

export interface PluginHookBeforePromptBuildEvent {
  prompt: string;
  messages: unknown[];
}

export interface PluginHookBeforePromptBuildResult {
  systemPrompt?: string;
  prependContext?: string;
  appendContext?: string;
  prependSystemContext?: string;
  appendSystemContext?: string;
}

export interface PluginHookAgentEndEvent {
  runId?: string;
  messages: unknown[];
  success: boolean;
  error?: string;
  durationMs?: number;
}

export interface PluginHookAgentContext {
  runId?: string;
  agentId?: string;
  sessionKey?: string;
  sessionId?: string;
  workspaceDir?: string;
}
