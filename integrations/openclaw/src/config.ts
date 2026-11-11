import { normalizeSharedConfig } from "../../common/src/config.js";
import type { SharedPluginConfig } from "../../common/src/types.js";

export interface MemoryHubConfig extends SharedPluginConfig {
  server: SharedPluginConfig["server"] & {
    transport: "streamable-http" | "http-sse";
  };
  auth: SharedPluginConfig["auth"] & { mode: "api_key" | "oauth" };
  autoRecall: SharedPluginConfig["autoRecall"] & { useFocus: boolean };
  autoCapture: {
    enabled: boolean;
    defaultScope: string;
    defaultWeight: number;
  };
}

function getString(
  obj: Record<string, unknown> | undefined,
  key: string,
): string | undefined {
  const val = obj?.[key];
  return typeof val === "string" ? val : undefined;
}

function getBool(
  obj: Record<string, unknown> | undefined,
  key: string,
  fallback: boolean,
): boolean {
  const val = obj?.[key];
  return typeof val === "boolean" ? val : fallback;
}

function getNumber(
  obj: Record<string, unknown> | undefined,
  key: string,
  fallback: number,
): number {
  const val = obj?.[key];
  return typeof val === "number" ? val : fallback;
}

function getObj(
  obj: Record<string, unknown> | undefined,
  key: string,
): Record<string, unknown> | undefined {
  const val = obj?.[key];
  return typeof val === "object" && val !== null && !Array.isArray(val)
    ? (val as Record<string, unknown>)
    : undefined;
}

export function parseConfig(
  pluginConfig?: Record<string, unknown>,
): MemoryHubConfig {
  const raw = pluginConfig ?? {};
  const server = getObj(raw, "server");
  const auth = getObj(raw, "auth");
  const autoRecall = getObj(raw, "autoRecall");
  const autoCapture = getObj(raw, "autoCapture");

  const url = getString(server, "url") ?? "";
  const apiKey = getString(auth, "apiKey");
  const authMode = getString(auth, "mode") === "oauth" ? "oauth" : "api_key";
  const shared = normalizeSharedConfig(raw, { url, apiKey });

  return {
    server: {
      ...shared.server,
      transport:
        getString(server, "transport") === "http-sse"
          ? "http-sse"
          : "streamable-http",
    },
    auth: {
      ...shared.auth,
      mode: authMode,
    },
    autoRecall: {
      ...shared.autoRecall,
      useFocus: getBool(autoRecall, "useFocus", true),
    },
    autoCapture: {
      enabled: getBool(autoCapture, "enabled", false),
      defaultScope: getString(autoCapture, "defaultScope") ?? "user",
      defaultWeight: getNumber(autoCapture, "defaultWeight", 0.7),
    },
    defaults: shared.defaults,
    needsSetup: !url || (!apiKey && authMode !== "oauth"),
  };
}
