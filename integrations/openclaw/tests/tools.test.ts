import { describe, it, expect, vi, beforeEach } from "vitest";
import { createTools } from "../src/tools.js";
import { parseConfig } from "../src/config.js";
import { createMockMcpClient } from "./helpers.js";
import type { MemoryHubMcpClient } from "../src/mcp-client.js";
import type { MemoryHubConfig } from "../src/config.js";

describe("tools", () => {
  let mcpClient: MemoryHubMcpClient;
  let config: MemoryHubConfig;

  beforeEach(() => {
    mcpClient = createMockMcpClient();
    config = parseConfig({
      server: { url: "https://hub.example.com/mcp/" },
      auth: { apiKey: "mh-dev-test" },
    });
  });

  function findTool(name: string) {
    const tools = createTools(mcpClient, config);
    const tool = tools.find((t) => t.name === name);
    if (!tool) throw new Error(`Tool ${name} not found`);
    return tool;
  }

  describe("memoryhub_search", () => {
    it("calls memory(action=search) with query", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        results: [{ id: "m1", content: "test memory", weight: 0.8 }],
        total_matching: 1,
        has_more: false,
      });

      const tool = findTool("memoryhub_search");
      const result = await tool.execute("tc1", { query: "preferences" });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("search", {
        query: "preferences",
        options: {},
      });
      expect(result.content[0].type).toBe("text");
      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.results).toHaveLength(1);
    });

    it("passes limit and content_type as options", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({ results: [] });

      const tool = findTool("memoryhub_search");
      await tool.execute("tc1", {
        query: "test",
        limit: 5,
        content_type: "behavioral",
      });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("search", {
        query: "test",
        options: { max_results: 5, content_type: "behavioral" },
      });
    });

    it("passes configured default domains", async () => {
      config.defaults.domains = ["eng", "ops"];
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({ results: [] });

      const tool = findTool("memoryhub_search");
      await tool.execute("tc1", { query: "test" });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("search", {
        query: "test",
        options: { domains: ["eng", "ops"] },
      });
    });

    it("passes scope as top-level param not in options", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({ results: [] });

      const tool = findTool("memoryhub_search");
      await tool.execute("tc1", { query: "test", scope: "project" });

      const callArgs = (mcpClient.callMemory as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(callArgs[1].scope).toBe("project");
      expect(callArgs[1].options.scope).toBeUndefined();
    });

    it("includes configured projectId", async () => {
      config.defaults.projectId = "proj-1";
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({ results: [] });

      const tool = findTool("memoryhub_search");
      await tool.execute("tc1", { query: "test" });

      const callArgs = (mcpClient.callMemory as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(callArgs[1].project_id).toBe("proj-1");
    });

    it("returns error result on failure", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error("connection refused"),
      );

      const tool = findTool("memoryhub_search");
      const result = await tool.execute("tc1", { query: "test" });

      expect(result.content[0].text).toContain("Error: connection refused");
    });
  });

  describe("memoryhub_read", () => {
    it("calls memory(action=read) with memory_id", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        id: "m1",
        content: "stored fact",
      });

      const tool = findTool("memoryhub_read");
      await tool.execute("tc1", { memory_id: "m1" });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("read", {
        memory_id: "m1",
        options: {},
      });
    });

    it("passes include_versions and hydrate options", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({});

      const tool = findTool("memoryhub_read");
      await tool.execute("tc1", {
        memory_id: "m1",
        include_versions: true,
        hydrate: true,
      });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("read", {
        memory_id: "m1",
        options: { include_versions: true, hydrate: true },
      });
    });
  });

  describe("memoryhub_list", () => {
    it("calls memory(action=list) with defaults", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        results: [],
        count: 0,
      });

      const tool = findTool("memoryhub_list");
      await tool.execute("tc1", {});

      expect(mcpClient.callMemory).toHaveBeenCalledWith("list", {
        options: {},
      });
    });

    it("passes scope and cursor", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        results: [],
        count: 0,
      });

      const tool = findTool("memoryhub_list");
      await tool.execute("tc1", {
        limit: 5,
        scope: "project",
        cursor: "abc123",
      });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("list", {
        options: { max_results: 5, cursor: "abc123" },
        scope: "project",
      });
    });

    it("includes configured projectId", async () => {
      config.defaults.projectId = "proj-1";
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        results: [],
        count: 0,
      });

      const tool = findTool("memoryhub_list");
      await tool.execute("tc1", {});

      const callArgs = (mcpClient.callMemory as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(callArgs[1].project_id).toBe("proj-1");
    });
  });

  describe("memoryhub_write", () => {
    it("calls memory(action=write) with content and default scope", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        memory: { id: "new-id", content: "test" },
        curation: { blocked: false },
      });

      const tool = findTool("memoryhub_write");
      await tool.execute("tc1", { content: "User prefers dark mode" });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("write", {
        content: "User prefers dark mode",
        scope: "user",
        options: {},
      });
    });

    it("passes weight, domains, and metadata", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        memory: { id: "new-id" },
        curation: { blocked: false },
      });

      const tool = findTool("memoryhub_write");
      await tool.execute("tc1", {
        content: "important fact",
        scope: "project",
        weight: 0.9,
        domains: ["security"],
        metadata: { source: "meeting" },
        content_type: "behavioral",
      });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("write", {
        content: "important fact",
        scope: "project",
        options: {
          weight: 0.9,
          domains: ["security"],
          metadata: { source: "meeting" },
          content_type: "behavioral",
        },
      });
    });

    it("includes configured projectId as top-level param", async () => {
      config.defaults.projectId = "proj-1";
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        memory: { id: "new-id" },
        curation: { blocked: false },
      });

      const tool = findTool("memoryhub_write");
      await tool.execute("tc1", { content: "test" });

      const callArgs = (mcpClient.callMemory as ReturnType<typeof vi.fn>).mock
        .calls[0];
      expect(callArgs[1].project_id).toBe("proj-1");
      expect(callArgs[1].options.project_id).toBeUndefined();
    });
  });

  describe("memoryhub_update", () => {
    it("calls memory(action=update) with memory_id and content", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        id: "m1",
        version: 2,
      });

      const tool = findTool("memoryhub_update");
      await tool.execute("tc1", {
        memory_id: "m1",
        content: "updated content",
      });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("update", {
        memory_id: "m1",
        content: "updated content",
        options: {},
      });
    });

    it("passes weight and metadata options", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({});

      const tool = findTool("memoryhub_update");
      await tool.execute("tc1", {
        memory_id: "m1",
        weight: 0.5,
        metadata: { updated: true },
      });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("update", {
        memory_id: "m1",
        options: { weight: 0.5, metadata: { updated: true } },
      });
    });
  });

  describe("memoryhub_delete", () => {
    it("calls memory(action=delete) with memory_id", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
        deleted_id: "m1",
        total_deleted: 1,
      });

      const tool = findTool("memoryhub_delete");
      await tool.execute("tc1", { memory_id: "m1" });

      expect(mcpClient.callMemory).toHaveBeenCalledWith("delete", {
        memory_id: "m1",
      });
    });

    it("returns error on failure", async () => {
      (mcpClient.callMemory as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error("Memory m1 not found"),
      );

      const tool = findTool("memoryhub_delete");
      const result = await tool.execute("tc1", { memory_id: "m1" });

      expect(result.content[0].text).toContain("Error: Memory m1 not found");
    });
  });

  it("creates all 6 tools", () => {
    const tools = createTools(mcpClient, config);
    expect(tools).toHaveLength(6);
    const names = tools.map((t) => t.name);
    expect(names).toEqual([
      "memoryhub_search",
      "memoryhub_read",
      "memoryhub_list",
      "memoryhub_write",
      "memoryhub_update",
      "memoryhub_delete",
    ]);
  });
});
