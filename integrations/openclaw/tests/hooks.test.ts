import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createBeforePromptBuildHook,
  createAgentEndHook,
} from "../src/hooks.js";
import { parseConfig } from "../src/config.js";
import { createMockMcpClient, createMockLogger } from "./helpers.js";
import type { MemoryHubMcpClient } from "../src/mcp-client.js";
import type { MemoryHubConfig } from "../src/config.js";
import type { PluginLogger } from "../src/openclaw-plugin-sdk.js";

const MOCK_PROTOCOL = "# MemoryHub Memory Protocol\nTest protocol content.";

describe("before_prompt_build hook", () => {
  let mcpClient: MemoryHubMcpClient;
  let config: MemoryHubConfig;
  let logger: PluginLogger;

  beforeEach(() => {
    mcpClient = createMockMcpClient();
    config = parseConfig({
      server: { url: "https://hub.example.com/mcp/" },
      auth: { apiKey: "mh-dev-test" },
    });
    logger = createMockLogger();
  });

  it("searches and returns formatted memories as prependContext", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      results: [
        {
          id: "m1",
          content: "User prefers dark mode",
          weight: 0.9,
          scope: "user",
          relevance_score: 0.92,
        },
        {
          id: "m2",
          content: "Team uses PostgreSQL",
          weight: 0.8,
          scope: "project",
          relevance_score: 0.87,
        },
      ],
    });

    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "What are my preferences?" }],
      },
      {},
    );

    expect(result).toBeDefined();
    expect(result!.prependContext).toContain("<relevant-memories>");
    expect(result!.prependContext).toContain("User prefers dark mode");
    expect(result!.prependContext).toContain("scope:user, weight:0.9");
    expect(result!.prependContext).toContain("92%");
    expect(result!.prependContext).toContain("Team uses PostgreSQL");
    expect(result!.prependContext).toContain("scope:project, weight:0.8");
    expect(result!.prependContext).toContain("</relevant-memories>");
  });

  it("includes prependSystemContext when protocol content is provided", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      results: [
        { id: "m1", content: "A fact", weight: 0.8, scope: "user", relevance_score: 0.9 },
      ],
    });

    const hook = createBeforePromptBuildHook(mcpClient, config, logger, MOCK_PROTOCOL);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "What are my preferences?" }],
      },
      {},
    );

    expect(result).toBeDefined();
    expect(result!.prependSystemContext).toBe(MOCK_PROTOCOL);
    expect(result!.prependContext).toContain("<relevant-memories>");
  });

  it("returns only prependSystemContext when autoRecall is disabled", async () => {
    config.autoRecall.enabled = false;

    const hook = createBeforePromptBuildHook(mcpClient, config, logger, MOCK_PROTOCOL);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "What are my preferences?" }],
      },
      {},
    );

    expect(result).toBeDefined();
    expect(result!.prependSystemContext).toBe(MOCK_PROTOCOL);
    expect(result!.prependContext).toBeUndefined();
    expect(mcpClient.callMemory).not.toHaveBeenCalled();
  });

  it("skips recall when autoRecall is disabled and no protocol", async () => {
    config.autoRecall.enabled = false;

    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "What are my preferences?" }],
      },
      {},
    );

    expect(result).toBeUndefined();
    expect(mcpClient.callMemory).not.toHaveBeenCalled();
  });

  it("returns only prependSystemContext when user text is too short", async () => {
    const hook = createBeforePromptBuildHook(mcpClient, config, logger, MOCK_PROTOCOL);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "hi" }],
      },
      {},
    );

    expect(result).toBeDefined();
    expect(result!.prependSystemContext).toBe(MOCK_PROTOCOL);
    expect(result!.prependContext).toBeUndefined();
    expect(mcpClient.callMemory).not.toHaveBeenCalled();
  });

  it("skips recall when user text is too short and no protocol", async () => {
    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "hi" }],
      },
      {},
    );

    expect(result).toBeUndefined();
    expect(mcpClient.callMemory).not.toHaveBeenCalled();
  });

  it("returns only prependSystemContext when no memories found", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      results: [],
    });

    const hook = createBeforePromptBuildHook(mcpClient, config, logger, MOCK_PROTOCOL);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "Tell me about the project" }],
      },
      {},
    );

    expect(result).toBeDefined();
    expect(result!.prependSystemContext).toBe(MOCK_PROTOCOL);
    expect(result!.prependContext).toBeUndefined();
  });

  it("returns undefined when no memories found and no protocol", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      results: [],
    });

    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "Tell me about the project" }],
      },
      {},
    );

    expect(result).toBeUndefined();
  });

  it("returns prependSystemContext even when MCP errors occur", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("connection refused"),
    );

    const hook = createBeforePromptBuildHook(mcpClient, config, logger, MOCK_PROTOCOL);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "What are my preferences?" }],
      },
      {},
    );

    expect(result).toBeDefined();
    expect(result!.prependSystemContext).toBe(MOCK_PROTOCOL);
    expect(result!.prependContext).toBeUndefined();
    expect(logger.warn).toHaveBeenCalledWith(
      expect.stringContaining("connection refused"),
    );
  });

  it("handles MCP errors gracefully with no protocol", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("connection refused"),
    );

    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "What are my preferences?" }],
      },
      {},
    );

    expect(result).toBeUndefined();
    expect(logger.warn).toHaveBeenCalledWith(
      expect.stringContaining("connection refused"),
    );
  });

  it("extracts text from the last user message", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      results: [],
    });

    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    await hook(
      {
        prompt: "",
        messages: [
          { role: "user", content: "first message" },
          { role: "assistant", content: "reply" },
          { role: "user", content: "second message about preferences" },
        ],
      },
      {},
    );

    expect(mcpClient.callMemory).toHaveBeenCalledWith("search", {
      query: "second message about preferences",
      options: {
        max_results: 10,
        max_response_tokens: 4000,
      },
    });
  });

  it("handles multipart content arrays", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      results: [],
    });

    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    await hook(
      {
        prompt: "",
        messages: [
          {
            role: "user",
            content: [
              { type: "text", text: "What do you know" },
              { type: "text", text: " about my setup?" },
            ],
          },
        ],
      },
      {},
    );

    expect(mcpClient.callMemory).toHaveBeenCalledWith("search", {
      query: "What do you know\n about my setup?",
      options: { max_results: 10, max_response_tokens: 4000 },
    });
  });

  it("passes configured domains to search", async () => {
    config.defaults.domains = ["eng", "ops"];
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      results: [],
    });

    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "Tell me about the project" }],
      },
      {},
    );

    const callArgs = (mcpClient.callMemory as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(callArgs[1].options.domains).toEqual(["eng", "ops"]);
  });

  it("uses stub when content is missing", async () => {
    (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      results: [
        { id: "m1", stub: "truncated memory...", weight: 0.7, scope: "user" },
      ],
    });

    const hook = createBeforePromptBuildHook(mcpClient, config, logger);
    const result = await hook(
      {
        prompt: "",
        messages: [{ role: "user", content: "What do you remember?" }],
      },
      {},
    );

    expect(result!.prependContext).toContain("truncated memory...");
  });
});

describe("agent_end hook", () => {
  let mcpClient: MemoryHubMcpClient;
  let logger: PluginLogger;

  beforeEach(() => {
    mcpClient = createMockMcpClient();
    logger = createMockLogger();
  });

  it("logs stub message when autoCapture is enabled", async () => {
    const config = parseConfig({
      server: { url: "https://hub.example.com/mcp/" },
      auth: { apiKey: "key" },
      autoCapture: { enabled: true },
    });

    const hook = createAgentEndHook(mcpClient, config, logger);
    await hook({ messages: [], success: true }, {});

    expect(logger.info).toHaveBeenCalledWith(
      "memoryhub: auto-capture not yet implemented",
    );
  });

  it("does nothing when autoCapture is disabled", async () => {
    const config = parseConfig({
      server: { url: "https://hub.example.com/mcp/" },
      auth: { apiKey: "key" },
    });

    const hook = createAgentEndHook(mcpClient, config, logger);
    await hook({ messages: [], success: true }, {});

    expect(logger.info).not.toHaveBeenCalled();
  });
});
