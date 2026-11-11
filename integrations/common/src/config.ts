import type { SharedPluginConfig } from "./types.js";

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function string(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function boolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function number(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function normalizeSharedConfig(
  rawConfig: Record<string, unknown> | undefined,
  resolved: { url?: string; apiKey?: string },
): SharedPluginConfig {
  const raw = rawConfig ?? {};
  const autoRecall = record(raw.autoRecall);
  const defaults = record(raw.defaults);
  const url = resolved.url ?? "";
  const apiKey = resolved.apiKey;

  return {
    server: { url },
    auth: { apiKey },
    autoRecall: {
      enabled: boolean(autoRecall?.enabled, true),
      maxResults: number(autoRecall?.maxResults, 10),
      maxResponseTokens: number(autoRecall?.maxResponseTokens, 4000),
    },
    defaults: {
      scope: string(defaults?.scope) ?? "user",
      projectId: string(defaults?.projectId),
      domains: stringArray(defaults?.domains),
    },
    needsSetup: !url || !apiKey,
  };
}
