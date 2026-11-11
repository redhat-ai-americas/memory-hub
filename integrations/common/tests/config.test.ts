import { describe, expect, it } from "vitest";
import { normalizeSharedConfig } from "../src/config.js";

describe("normalizeSharedConfig", () => {
  it("uses shared defaults and resolved host credentials", () => {
    expect(normalizeSharedConfig({}, {
      url: "https://memoryhub.example/mcp/",
      apiKey: "test-key",
    })).toEqual({
      server: { url: "https://memoryhub.example/mcp/" },
      auth: { apiKey: "test-key" },
      autoRecall: {
        enabled: true,
        maxResults: 10,
        maxResponseTokens: 4000,
      },
      defaults: { scope: "user", projectId: undefined, domains: [] },
      needsSetup: false,
    });
  });

  it("normalizes shared options and rejects values of the wrong type", () => {
    expect(normalizeSharedConfig({
      autoRecall: { enabled: false, maxResults: "many", maxResponseTokens: 3000 },
      defaults: { scope: "project", projectId: 42, domains: ["ops", 2] },
    }, { url: "", apiKey: undefined })).toMatchObject({
      autoRecall: { enabled: false, maxResults: 10, maxResponseTokens: 3000 },
      defaults: { scope: "project", domains: ["ops"] },
      needsSetup: true,
    });
  });
});
