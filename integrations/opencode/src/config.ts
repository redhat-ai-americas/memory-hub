import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export interface MemoryHubConfig {
  server: {
    url: string;
  };
  auth: {
    apiKey?: string;
  };
  autoRecall: {
    enabled: boolean;
    maxResults: number;
    maxResponseTokens: number;
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

/**
 * Minimal INI reader for ~/.config/memoryhub/credentials — the same format
 * the CLI, SDK, and the Claude Code SessionStart hook use. Returns the value
 * of `key` in `[section]`, falling back to `[default]`.
 */
function readCredentialsValue(
  credsPath: string,
  section: string,
  key: string,
): string | undefined {
  let raw: string;
  try {
    raw = readFileSync(credsPath, "utf-8");
  } catch {
    return undefined;
  }

  const sections: Record<string, Record<string, string>> = {};
  let current = "";
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || trimmed.startsWith(";")) {
      continue;
    }
    const sectionMatch = trimmed.match(/^\[(.+)\]$/);
    if (sectionMatch) {
      current = sectionMatch[1];
      sections[current] ??= {};
      continue;
    }
    const eq = trimmed.indexOf("=");
    if (eq > 0 && current) {
      const k = trimmed.slice(0, eq).trim();
      const v = trimmed.slice(eq + 1).trim();
      sections[current][k] = v;
    }
  }

  // `||` (not `??`): an empty value like `url =` counts as missing, so the
  // per-key [default] fallback still applies.
  return sections[section]?.[key] || sections["default"]?.[key] || undefined;
}

export interface ConfigEnv {
  env?: Record<string, string | undefined>;
  home?: string;
}

/**
 * Resolve plugin configuration. Precedence per value:
 *   1. Plugin options from opencode.json
 *      ("plugin": [["@memory-hub/opencode-mh-plugin", { ... }]])
 *   2. MEMORYHUB_URL / MEMORYHUB_API_KEY environment variables
 *   3. ~/.config/memoryhub/credentials (INI; section from MEMORYHUB_CONTEXT,
 *      falling back to [default]; keys `url` and `api_key`)
 *   4. ~/.config/memoryhub/api-key (flat file, api key only, backwards compat)
 */
export function resolveConfig(
  options?: Record<string, unknown>,
  { env = process.env, home = homedir() }: ConfigEnv = {},
): MemoryHubConfig {
  const raw = options ?? {};
  const server = getObj(raw, "server");
  const auth = getObj(raw, "auth");
  const autoRecall = getObj(raw, "autoRecall");
  const defaults = getObj(raw, "defaults");

  const credsPath = join(home, ".config", "memoryhub", "credentials");
  const section = env.MEMORYHUB_CONTEXT || "default";

  let url = getString(server, "url") ?? env.MEMORYHUB_URL ?? "";
  if (!url) {
    url = readCredentialsValue(credsPath, section, "url") ?? "";
  }

  let apiKey = getString(auth, "apiKey") ?? env.MEMORYHUB_API_KEY;
  if (!apiKey) {
    apiKey = readCredentialsValue(credsPath, section, "api_key");
  }
  if (!apiKey) {
    try {
      const flat = readFileSync(
        join(home, ".config", "memoryhub", "api-key"),
        "utf-8",
      );
      const cleaned = flat
        .split("\n")
        .filter((l) => !l.trim().startsWith("#"))
        .join("")
        .trim();
      if (cleaned) apiKey = cleaned;
    } catch {
      // no flat api-key file — fine
    }
  }

  return {
    server: { url },
    auth: { apiKey },
    autoRecall: {
      enabled: getBool(autoRecall, "enabled", true),
      maxResults: getNumber(autoRecall, "maxResults", 10),
      maxResponseTokens: getNumber(autoRecall, "maxResponseTokens", 4000),
    },
    defaults: {
      scope: getString(defaults, "scope") ?? "user",
      projectId: getString(defaults, "projectId"),
      domains: getStringArray(defaults, "domains"),
    },
    needsSetup: !url || !apiKey,
  };
}
