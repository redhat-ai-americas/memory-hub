export interface MemoryHubConfig {
  server: {
    url: string;
    transport: "streamable-http" | "http-sse";
  };
  auth: {
    mode: "api_key" | "oauth";
    apiKey?: string;
  };
  autoRecall: {
    enabled: boolean;
    maxResults: number;
    maxResponseTokens: number;
    useFocus: boolean;
  };
  autoCapture: {
    enabled: boolean;
    defaultScope: string;
    defaultWeight: number;
  };
  defaults: {
    scope: string;
    projectId?: string;
    domains: string[];
  };
  needsSetup: boolean;
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

function getStringArray(
  obj: Record<string, unknown> | undefined,
  key: string,
): string[] {
  const val = obj?.[key];
  if (Array.isArray(val)) {
    return val.filter((v): v is string => typeof v === "string");
  }
  return [];
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
  const defaults = getObj(raw, "defaults");

  const url = getString(server, "url") ?? "";
  const apiKey = getString(auth, "apiKey");
  const needsSetup = !url || (!apiKey && getString(auth, "mode") !== "oauth");

  return {
    server: {
      url,
      transport:
        getString(server, "transport") === "http-sse"
          ? "http-sse"
          : "streamable-http",
    },
    auth: {
      mode:
        getString(auth, "mode") === "oauth" ? "oauth" : "api_key",
      apiKey,
    },
    autoRecall: {
      enabled: getBool(autoRecall, "enabled", true),
      maxResults: getNumber(autoRecall, "maxResults", 10),
      maxResponseTokens: getNumber(autoRecall, "maxResponseTokens", 4000),
      useFocus: getBool(autoRecall, "useFocus", true),
    },
    autoCapture: {
      enabled: getBool(autoCapture, "enabled", false),
      defaultScope: getString(autoCapture, "defaultScope") ?? "user",
      defaultWeight: getNumber(autoCapture, "defaultWeight", 0.7),
    },
    defaults: {
      scope: getString(defaults, "scope") ?? "user",
      projectId: getString(defaults, "projectId"),
      domains: getStringArray(defaults, "domains"),
    },
    needsSetup,
  };
}
