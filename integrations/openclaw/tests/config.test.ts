import { describe, it, expect } from "vitest";
import { parseConfig } from "../src/config.js";

describe("parseConfig", () => {
  it("parses a complete valid config", () => {
    const cfg = parseConfig({
      server: { url: "https://hub.example.com/mcp/", transport: "streamable-http" },
      auth: { mode: "api_key", apiKey: "mh-dev-abc123" },
      autoRecall: { enabled: true, maxResults: 5, maxResponseTokens: 2000, useFocus: false },
      autoCapture: { enabled: true, defaultScope: "project", defaultWeight: 0.9 },
      defaults: { scope: "project", projectId: "proj-1", domains: ["eng", "ops"] },
    });

    expect(cfg.needsSetup).toBe(false);
    expect(cfg.server.url).toBe("https://hub.example.com/mcp/");
    expect(cfg.server.transport).toBe("streamable-http");
    expect(cfg.auth.mode).toBe("api_key");
    expect(cfg.auth.apiKey).toBe("mh-dev-abc123");
    expect(cfg.autoRecall.enabled).toBe(true);
    expect(cfg.autoRecall.maxResults).toBe(5);
    expect(cfg.autoRecall.maxResponseTokens).toBe(2000);
    expect(cfg.autoRecall.useFocus).toBe(false);
    expect(cfg.autoCapture.enabled).toBe(true);
    expect(cfg.autoCapture.defaultScope).toBe("project");
    expect(cfg.autoCapture.defaultWeight).toBe(0.9);
    expect(cfg.defaults.scope).toBe("project");
    expect(cfg.defaults.projectId).toBe("proj-1");
    expect(cfg.defaults.domains).toEqual(["eng", "ops"]);
  });

  it("applies defaults for missing optional fields", () => {
    const cfg = parseConfig({
      server: { url: "https://hub.example.com/mcp/" },
      auth: { apiKey: "mh-dev-abc123" },
    });

    expect(cfg.needsSetup).toBe(false);
    expect(cfg.server.transport).toBe("streamable-http");
    expect(cfg.auth.mode).toBe("api_key");
    expect(cfg.autoRecall.enabled).toBe(true);
    expect(cfg.autoRecall.maxResults).toBe(10);
    expect(cfg.autoRecall.maxResponseTokens).toBe(4000);
    expect(cfg.autoRecall.useFocus).toBe(true);
    expect(cfg.autoCapture.enabled).toBe(false);
    expect(cfg.autoCapture.defaultScope).toBe("user");
    expect(cfg.autoCapture.defaultWeight).toBe(0.7);
    expect(cfg.defaults.scope).toBe("user");
    expect(cfg.defaults.projectId).toBeUndefined();
    expect(cfg.defaults.domains).toEqual([]);
  });

  it("sets needsSetup when URL is missing", () => {
    const cfg = parseConfig({
      auth: { apiKey: "mh-dev-abc123" },
    });
    expect(cfg.needsSetup).toBe(true);
  });

  it("sets needsSetup when API key is missing in api_key mode", () => {
    const cfg = parseConfig({
      server: { url: "https://hub.example.com/mcp/" },
    });
    expect(cfg.needsSetup).toBe(true);
  });

  it("does not require API key in oauth mode", () => {
    const cfg = parseConfig({
      server: { url: "https://hub.example.com/mcp/" },
      auth: { mode: "oauth" },
    });
    expect(cfg.needsSetup).toBe(false);
    expect(cfg.auth.mode).toBe("oauth");
  });

  it("handles undefined pluginConfig", () => {
    const cfg = parseConfig(undefined);
    expect(cfg.needsSetup).toBe(true);
    expect(cfg.server.url).toBe("");
  });

  it("handles empty pluginConfig", () => {
    const cfg = parseConfig({});
    expect(cfg.needsSetup).toBe(true);
  });

  it("selects http-sse transport when configured", () => {
    const cfg = parseConfig({
      server: { url: "https://hub.example.com/mcp/", transport: "http-sse" },
      auth: { apiKey: "key" },
    });
    expect(cfg.server.transport).toBe("http-sse");
  });

  it("filters non-string values from domains array", () => {
    const cfg = parseConfig({
      server: { url: "https://hub.example.com/mcp/" },
      auth: { apiKey: "key" },
      defaults: { domains: ["valid", 123, null, "also-valid"] },
    });
    expect(cfg.defaults.domains).toEqual(["valid", "also-valid"]);
  });
});
