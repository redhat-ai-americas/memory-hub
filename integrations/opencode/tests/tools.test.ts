import { describe, it, expect, vi } from "vitest";
import { createTools } from "../src/tools.js";
import type { ToolContext } from "@opencode-ai/plugin";
import {
  createMockMcpClient,
  testConfig,
  passthroughSession,
} from "./helpers.js";

const ctx = {} as ToolContext;

function makeTools(
  clientOverrides?: Parameters<typeof createMockMcpClient>[0],
  configOverrides?: Parameters<typeof testConfig>[0],
) {
  const client = createMockMcpClient(clientOverrides);
  const tools = createTools(
    client,
    testConfig(configOverrides),
    passthroughSession,
  );
  return { client, tools };
}

describe("createTools", () => {
  it("registers the six memoryhub tools", () => {
    const { tools } = makeTools();
    expect(Object.keys(tools).sort()).toEqual([
      "memoryhub_delete",
      "memoryhub_list",
      "memoryhub_read",
      "memoryhub_search",
      "memoryhub_update",
      "memoryhub_write",
    ]);
    for (const t of Object.values(tools)) {
      expect(t.description.length).toBeGreaterThan(0);
      expect(typeof t.execute).toBe("function");
    }
  });

  describe("memoryhub_search", () => {
    it("maps params onto memory(action=search)", async () => {
      const { client, tools } = makeTools(
        { callMemory: vi.fn().mockResolvedValue({ results: [] }) },
        { defaults: { scope: "user", projectId: "proj-1", domains: [] } },
      );
      await tools.memoryhub_search.execute(
        {
          query: "deployment patterns",
          limit: 5,
          scope: "project",
          content_type: "factual",
        },
        ctx,
      );
      expect(client.callMemory).toHaveBeenCalledWith("search", {
        query: "deployment patterns",
        scope: "project",
        project_id: "proj-1",
        options: { max_results: 5, content_type: "factual" },
      });
    });

    it("falls back to config default domains", async () => {
      const { client, tools } = makeTools(undefined, {
        defaults: { scope: "user", projectId: undefined, domains: ["k8s"] },
      });
      await tools.memoryhub_search.execute({ query: "anything" }, ctx);
      const [, params] = vi.mocked(client.callMemory).mock.calls[0];
      expect((params.options as Record<string, unknown>).domains).toEqual([
        "k8s",
      ]);
      expect(params).not.toHaveProperty("project_id");
    });

    it("param domains override config domains", async () => {
      const { client, tools } = makeTools(undefined, {
        defaults: { scope: "user", projectId: undefined, domains: ["k8s"] },
      });
      await tools.memoryhub_search.execute(
        { query: "anything", domains: ["auth"] },
        ctx,
      );
      const [, params] = vi.mocked(client.callMemory).mock.calls[0];
      expect((params.options as Record<string, unknown>).domains).toEqual([
        "auth",
      ]);
    });

    it("returns a JSON result envelope", async () => {
      const { tools } = makeTools({
        callMemory: vi.fn().mockResolvedValue({ results: [{ id: "m1" }] }),
      });
      const result = await tools.memoryhub_search.execute(
        { query: "anything" },
        ctx,
      );
      expect(result).toEqual({
        title: "MemoryHub search",
        output: JSON.stringify({ results: [{ id: "m1" }] }, null, 2),
      });
    });

    it("returns an error string instead of throwing", async () => {
      const { tools } = makeTools({
        callMemory: vi.fn().mockRejectedValue(new Error("boom")),
      });
      const result = await tools.memoryhub_search.execute(
        { query: "anything" },
        ctx,
      );
      expect(result).toBe("Error: boom");
    });
  });

  describe("memoryhub_read", () => {
    it("maps flags into options", async () => {
      const { client, tools } = makeTools();
      await tools.memoryhub_read.execute(
        { memory_id: "mem-1", include_versions: true, hydrate: true },
        ctx,
      );
      expect(client.callMemory).toHaveBeenCalledWith("read", {
        memory_id: "mem-1",
        options: { include_versions: true, hydrate: true },
      });
    });
  });

  describe("memoryhub_list", () => {
    it("maps pagination params", async () => {
      const { client, tools } = makeTools(undefined, {
        defaults: { scope: "user", projectId: "proj-1", domains: [] },
      });
      await tools.memoryhub_list.execute(
        { limit: 20, scope: "user", cursor: "abc" },
        ctx,
      );
      expect(client.callMemory).toHaveBeenCalledWith("list", {
        scope: "user",
        project_id: "proj-1",
        options: { max_results: 20, cursor: "abc" },
      });
    });
  });

  describe("memoryhub_write", () => {
    it("maps write params, defaulting scope from config", async () => {
      const { client, tools } = makeTools(undefined, {
        defaults: { scope: "project", projectId: "proj-1", domains: [] },
      });
      await tools.memoryhub_write.execute(
        {
          content: "Use Podman, not Docker",
          weight: 0.9,
          domains: ["tooling"],
          metadata: { source: "test" },
          parent_id: "mem-0",
          branch_type: "rationale",
        },
        ctx,
      );
      expect(client.callMemory).toHaveBeenCalledWith("write", {
        content: "Use Podman, not Docker",
        scope: "project",
        project_id: "proj-1",
        options: {
          weight: 0.9,
          metadata: { source: "test" },
          parent_id: "mem-0",
          branch_type: "rationale",
          domains: ["tooling"],
        },
      });
    });

    it("explicit scope wins over config default", async () => {
      const { client, tools } = makeTools();
      await tools.memoryhub_write.execute(
        { content: "fact", scope: "organizational" },
        ctx,
      );
      const [, params] = vi.mocked(client.callMemory).mock.calls[0];
      expect(params.scope).toBe("organizational");
    });

    it("weight 0 is forwarded (falsy-safe)", async () => {
      const { client, tools } = makeTools();
      await tools.memoryhub_write.execute({ content: "fact", weight: 0 }, ctx);
      const [, params] = vi.mocked(client.callMemory).mock.calls[0];
      expect((params.options as Record<string, unknown>).weight).toBe(0);
    });
  });

  describe("memoryhub_update", () => {
    it("puts content top-level and the rest in options", async () => {
      const { client, tools } = makeTools();
      await tools.memoryhub_update.execute(
        { memory_id: "mem-1", content: "new text", weight: 0.5 },
        ctx,
      );
      expect(client.callMemory).toHaveBeenCalledWith("update", {
        memory_id: "mem-1",
        content: "new text",
        options: { weight: 0.5 },
      });
    });
  });

  describe("memoryhub_delete", () => {
    it("sends only the memory_id", async () => {
      const { client, tools } = makeTools();
      await tools.memoryhub_delete.execute({ memory_id: "mem-1" }, ctx);
      expect(client.callMemory).toHaveBeenCalledWith("delete", {
        memory_id: "mem-1",
      });
    });
  });

  it("runs every call through withSession", async () => {
    const client = createMockMcpClient();
    const withSession = vi.fn(<T>(fn: () => Promise<T>) => fn());
    const tools = createTools(client, testConfig(), withSession);
    await tools.memoryhub_search.execute({ query: "anything" }, ctx);
    await tools.memoryhub_delete.execute({ memory_id: "m" }, ctx);
    expect(withSession).toHaveBeenCalledTimes(2);
  });
});
