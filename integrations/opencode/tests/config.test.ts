import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveConfig } from "../src/config.js";

describe("resolveConfig", () => {
  let home: string;

  beforeEach(() => {
    home = mkdtempSync(join(tmpdir(), "mh-opencode-test-"));
  });

  afterEach(() => {
    rmSync(home, { recursive: true, force: true });
  });

  function writeCredentials(content: string): void {
    const dir = join(home, ".config", "memoryhub");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "credentials"), content);
  }

  it("uses plugin options first", () => {
    const config = resolveConfig(
      {
        server: { url: "https://from-options.example.com/mcp/" },
        auth: { apiKey: "mh-dev-aaaaaaaaaaaaaaaa" },
      },
      { env: { MEMORYHUB_URL: "https://from-env.example.com/mcp/" }, home },
    );
    expect(config.server.url).toBe("https://from-options.example.com/mcp/");
    expect(config.auth.apiKey).toBe("mh-dev-aaaaaaaaaaaaaaaa");
    expect(config.needsSetup).toBe(false);
  });

  it("falls back to env vars", () => {
    const config = resolveConfig(undefined, {
      env: {
        MEMORYHUB_URL: "https://from-env.example.com/mcp/",
        MEMORYHUB_API_KEY: "mh-dev-bbbbbbbbbbbbbbbb",
      },
      home,
    });
    expect(config.server.url).toBe("https://from-env.example.com/mcp/");
    expect(config.auth.apiKey).toBe("mh-dev-bbbbbbbbbbbbbbbb");
    expect(config.needsSetup).toBe(false);
  });

  it("falls back to the credentials file [default] section", () => {
    writeCredentials(
      [
        "[default]",
        "url = https://from-creds.example.com/mcp/",
        "api_key = mh-dev-cccccccccccccccc",
      ].join("\n"),
    );
    const config = resolveConfig(undefined, { env: {}, home });
    expect(config.server.url).toBe("https://from-creds.example.com/mcp/");
    expect(config.auth.apiKey).toBe("mh-dev-cccccccccccccccc");
    expect(config.needsSetup).toBe(false);
  });

  it("honors MEMORYHUB_CONTEXT section with [default] fallback per key", () => {
    writeCredentials(
      [
        "[default]",
        "url = https://default.example.com/mcp/",
        "api_key = mh-dev-dddddddddddddddd",
        "",
        "[mcp-rhoai]",
        "url = https://rhoai.example.com/mcp/",
      ].join("\n"),
    );
    const config = resolveConfig(undefined, {
      env: { MEMORYHUB_CONTEXT: "mcp-rhoai" },
      home,
    });
    expect(config.server.url).toBe("https://rhoai.example.com/mcp/");
    // api_key missing in [mcp-rhoai] -> falls back to [default]
    expect(config.auth.apiKey).toBe("mh-dev-dddddddddddddddd");
  });

  it("ignores comments and blank lines in the credentials file", () => {
    writeCredentials(
      [
        "# a comment",
        "",
        "[default]",
        "; another comment",
        "api_key = mh-dev-eeeeeeeeeeeeeeee",
      ].join("\n"),
    );
    const config = resolveConfig(undefined, {
      env: { MEMORYHUB_URL: "https://x.example.com/mcp/" },
      home,
    });
    expect(config.auth.apiKey).toBe("mh-dev-eeeeeeeeeeeeeeee");
  });

  it("treats empty values in the context section as missing (falls back to [default])", () => {
    writeCredentials(
      [
        "[default]",
        "url = https://default.example.com/mcp/",
        "api_key = mh-dev-dddddddddddddddd",
        "",
        "[staging]",
        "url =",
        "api_key =",
      ].join("\n"),
    );
    const config = resolveConfig(undefined, {
      env: { MEMORYHUB_CONTEXT: "staging" },
      home,
    });
    expect(config.server.url).toBe("https://default.example.com/mcp/");
    expect(config.auth.apiKey).toBe("mh-dev-dddddddddddddddd");
    expect(config.needsSetup).toBe(false);
  });

  it("falls back to the flat api-key file", () => {
    const dir = join(home, ".config", "memoryhub");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "api-key"),
      "# comment line\nmh-dev-ffffffffffffffff\n",
    );
    const config = resolveConfig(undefined, {
      env: { MEMORYHUB_URL: "https://x.example.com/mcp/" },
      home,
    });
    expect(config.auth.apiKey).toBe("mh-dev-ffffffffffffffff");
  });

  it("needsSetup when url is missing", () => {
    const config = resolveConfig(
      { auth: { apiKey: "mh-dev-aaaaaaaaaaaaaaaa" } },
      { env: {}, home },
    );
    expect(config.needsSetup).toBe(true);
  });

  it("needsSetup when apiKey is missing", () => {
    const config = resolveConfig(
      { server: { url: "https://x.example.com/mcp/" } },
      { env: {}, home },
    );
    expect(config.needsSetup).toBe(true);
  });

  it("applies autoRecall and defaults overrides with fallbacks", () => {
    const config = resolveConfig(
      {
        server: { url: "https://x.example.com/mcp/" },
        auth: { apiKey: "mh-dev-aaaaaaaaaaaaaaaa" },
        autoRecall: { enabled: false, maxResults: 5 },
        defaults: { scope: "project", projectId: "memory-hub", domains: ["k8s"] },
      },
      { env: {}, home },
    );
    expect(config.autoRecall.enabled).toBe(false);
    expect(config.autoRecall.maxResults).toBe(5);
    expect(config.autoRecall.maxResponseTokens).toBe(4000);
    expect(config.defaults.scope).toBe("project");
    expect(config.defaults.projectId).toBe("memory-hub");
    expect(config.defaults.domains).toEqual(["k8s"]);
  });

  it("defaults are sane with no input at all", () => {
    const config = resolveConfig(undefined, { env: {}, home });
    expect(config.autoRecall).toEqual({
      enabled: true,
      maxResults: 10,
      maxResponseTokens: 4000,
    });
    expect(config.defaults.scope).toBe("user");
    expect(config.defaults.domains).toEqual([]);
    expect(config.needsSetup).toBe(true);
  });

  it("ignores malformed option types instead of crashing", () => {
    const config = resolveConfig(
      {
        server: "not-an-object",
        autoRecall: { enabled: "yes", maxResults: "many" },
        defaults: { domains: ["ok", 42, null] },
      } as Record<string, unknown>,
      { env: { MEMORYHUB_URL: "https://x.example.com/mcp/" }, home },
    );
    expect(config.server.url).toBe("https://x.example.com/mcp/");
    expect(config.autoRecall.enabled).toBe(true);
    expect(config.autoRecall.maxResults).toBe(10);
    expect(config.defaults.domains).toEqual(["ok"]);
  });
});
