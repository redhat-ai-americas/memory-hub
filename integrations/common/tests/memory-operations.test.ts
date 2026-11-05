import { describe, expect, it } from "vitest";
import {
  buildMemoryOperation,
  DEFAULT_MEMORY_TOOL_NAMES,
  extendMemoryToolCatalog,
  MEMORY_TOOL_CATALOG,
  MEMORY_TOOL_DESCRIPTIONS,
} from "../src/memory-operations.js";

const defaults = { scope: "user", projectId: "project-1", domains: ["ops"] };

describe("buildMemoryOperation", () => {
  it("maps all six host tools to the MCP memory actions", () => {
    const expected = ["search", "read", "list", "write", "update", "delete"];
    const tools = Object.keys(MEMORY_TOOL_DESCRIPTIONS) as Array<keyof typeof MEMORY_TOOL_DESCRIPTIONS>;
    expect(tools.map((tool) => buildMemoryOperation(tool, {}, defaults).action)).toEqual(expected);
  });

  it("keeps the six tools as the default catalog profile", () => {
    expect(DEFAULT_MEMORY_TOOL_NAMES).toEqual([
      "memoryhub_search",
      "memoryhub_read",
      "memoryhub_list",
      "memoryhub_write",
      "memoryhub_update",
      "memoryhub_delete",
    ]);
    expect(Object.keys(MEMORY_TOOL_CATALOG)).toEqual(DEFAULT_MEMORY_TOOL_NAMES);
  });

  it("allows adapters to extend the catalog without changing common mappings", () => {
    const catalog = extendMemoryToolCatalog({
      memoryhub_threads: {
        description: "Manage conversation threads.",
        buildOperation: (args) => ({
          action: "thread",
          params: { action: args.action },
        }),
      },
    });

    expect(buildMemoryOperation("memoryhub_threads", { action: "list" }, defaults, catalog)).toEqual({
      action: "thread",
      params: { action: "list" },
    });
    expect(Object.keys(MEMORY_TOOL_CATALOG)).toHaveLength(6);
  });

  it("rejects tools that are not in the selected catalog", () => {
    expect(() => buildMemoryOperation("memoryhub_unknown", {}, defaults)).toThrow(
      "Unknown MemoryHub tool: memoryhub_unknown",
    );
  });

  it("applies search defaults while preserving explicit arguments", () => {
    expect(buildMemoryOperation("memoryhub_search", {
      query: "deployment choice",
      limit: 7,
      scope: "project",
      content_type: "knowledge",
    }, defaults)).toEqual({
      action: "search",
      params: {
        query: "deployment choice",
        scope: "project",
        project_id: "project-1",
        options: {
          max_results: 7,
          content_type: "knowledge",
          domains: ["ops"],
        },
      },
    });
  });

  it("maps writes and updates into action-specific options", () => {
    expect(buildMemoryOperation("memoryhub_write", {
      content: "keep this",
      weight: 0.8,
      domains: ["work"],
    }, defaults)).toMatchObject({
      action: "write",
      params: {
        content: "keep this",
        scope: "user",
        project_id: "project-1",
        options: { weight: 0.8, domains: ["work"] },
      },
    });
    expect(buildMemoryOperation("memoryhub_update", {
      memory_id: "m1",
      content: "new",
      weight: 0.5,
    }, defaults)).toEqual({
      action: "update",
      params: { memory_id: "m1", content: "new", options: { weight: 0.5 } },
    });
  });
});
