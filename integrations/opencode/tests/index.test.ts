import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { PluginInput } from "@opencode-ai/plugin";

// Point homedir at an empty temp dir so a developer's real
// ~/.config/memoryhub/credentials can't leak into these tests.
const emptyHome = mkdtempSync(join(tmpdir(), "mh-opencode-home-"));
vi.mock("node:os", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:os")>();
  return { ...actual, homedir: () => emptyHome };
});

import { MemoryHubPlugin } from "../src/index.js";

const pluginInput = {} as PluginInput;

describe("MemoryHubPlugin", () => {
  const savedEnv = { ...process.env };

  beforeEach(() => {
    delete process.env.MEMORYHUB_URL;
    delete process.env.MEMORYHUB_API_KEY;
    delete process.env.MEMORYHUB_CONTEXT;
  });

  afterEach(() => {
    process.env = { ...savedEnv };
  });

  it("returns empty hooks when unconfigured", async () => {
    const hooks = await MemoryHubPlugin(pluginInput, undefined);
    expect(hooks).toEqual({});
  });

  it("returns tools and hooks when configured via options", async () => {
    const hooks = await MemoryHubPlugin(pluginInput, {
      server: { url: "https://example.com/mcp/" },
      auth: { apiKey: "mh-dev-0123456789abcdef" },
    });

    expect(Object.keys(hooks.tool ?? {}).sort()).toEqual([
      "memoryhub_delete",
      "memoryhub_list",
      "memoryhub_read",
      "memoryhub_search",
      "memoryhub_update",
      "memoryhub_write",
    ]);
    expect(hooks["chat.message"]).toBeTypeOf("function");
    expect(hooks["experimental.chat.messages.transform"]).toBeTypeOf(
      "function",
    );
    expect(hooks["experimental.chat.system.transform"]).toBeTypeOf("function");
    expect(hooks.dispose).toBeTypeOf("function");
  });

  it("injects the memory protocol into the system prompt", async () => {
    const hooks = await MemoryHubPlugin(pluginInput, {
      server: { url: "https://example.com/mcp/" },
      auth: { apiKey: "mh-dev-0123456789abcdef" },
    });

    const output = { system: [] as string[] };
    await hooks["experimental.chat.system.transform"]!(
      { model: {} as never },
      output,
    );
    expect(output.system.join("\n")).toContain("MemoryHub Memory Protocol");
  });

  it("configures from env vars", async () => {
    process.env.MEMORYHUB_URL = "https://env.example.com/mcp/";
    process.env.MEMORYHUB_API_KEY = "mh-dev-0123456789abcdef";
    const hooks = await MemoryHubPlugin(pluginInput, undefined);
    expect(hooks.tool).toBeDefined();
  });
});

afterEach(() => {
  // final cleanup of the temp home when the file finishes
});

process.on("exit", () => {
  try {
    rmSync(emptyHome, { recursive: true, force: true });
  } catch {
    // best effort
  }
});
