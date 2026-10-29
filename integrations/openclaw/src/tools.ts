import { Type } from "@sinclair/typebox";
import {
  buildMemoryOperation,
  MEMORY_TOOL_DESCRIPTIONS,
} from "../../common/src/memory-operations.js";
import type { MemoryHubMcpClient } from "./mcp-client.js";
import type { MemoryHubConfig } from "./config.js";
import type { AnyAgentTool, AgentToolResult } from "./openclaw-plugin-sdk.js";

const contentTypeFilter = Type.Union(
  [
    Type.Literal("experiential"),
    Type.Literal("knowledge"),
    Type.Literal("behavioral"),
    Type.Literal("procedural"),
  ],
  { description: "Filter by content type. Omit to include all types." },
);

const contentTypeForWrite = Type.Union(
  [
    Type.Literal("experiential"),
    Type.Literal("knowledge"),
    Type.Literal("behavioral"),
    Type.Literal("procedural"),
  ],
  {
    description:
      "Content type: experiential (server default), knowledge (facts and preferences), behavioral, or procedural.",
  },
);

function textResult(data: unknown): AgentToolResult {
  return {
    content: [
      { type: "text", text: JSON.stringify(data, null, 2) },
    ],
  };
}

function errorResult(message: string): AgentToolResult {
  return {
    content: [{ type: "text", text: `Error: ${message}` }],
  };
}

export function createTools(
  mcpClient: MemoryHubMcpClient,
  config: MemoryHubConfig,
  withSession: <T>(operation: () => Promise<T>) => Promise<T> = (operation) =>
    operation(),
): AnyAgentTool[] {
  async function execute(
    name: keyof typeof MEMORY_TOOL_DESCRIPTIONS,
    params: Record<string, unknown>,
    fallback: string,
  ): Promise<AgentToolResult> {
    try {
      const operation = buildMemoryOperation(name, params, config.defaults);
      const result = await withSession(() =>
        mcpClient.callMemory(operation.action, operation.params),
      );
      return textResult(result);
    } catch (error) {
      return errorResult(error instanceof Error ? error.message : fallback);
    }
  }

  const memoryhubSearch: AnyAgentTool = {
    name: "memoryhub_search",
    label: "MemoryHub Search",
    description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_search,
    parameters: Type.Object({
      query: Type.String({ description: "Natural language search query" }),
      limit: Type.Optional(
        Type.Integer({
          description: "Max results (default: 10)",
          minimum: 1,
          maximum: 50,
        }),
      ),
      scope: Type.Optional(
        Type.String({
          description:
            "Filter by scope: user, project, campaign, role, organizational, enterprise",
        }),
      ),
      domains: Type.Optional(
        Type.Array(Type.String(), {
          description: "Boost results tagged with these domain labels",
        }),
      ),
      content_type: Type.Optional(
        contentTypeFilter,
      ),
    }),
    async execute(_toolCallId, params) {
      return execute("memoryhub_search", params, "Search failed");
    },
  };

  const memoryhubRead: AnyAgentTool = {
    name: "memoryhub_read",
    label: "MemoryHub Read",
    description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_read,
    parameters: Type.Object({
      memory_id: Type.String({ description: "UUID of the memory to read" }),
      include_versions: Type.Optional(
        Type.Boolean({
          description: "Include version history (default: false)",
        }),
      ),
      hydrate: Type.Optional(
        Type.Boolean({
          description:
            "Fetch full content for S3-backed memories (default: false)",
        }),
      ),
    }),
    async execute(_toolCallId, params) {
      return execute("memoryhub_read", params, "Read failed");
    },
  };

  const memoryhubList: AnyAgentTool = {
    name: "memoryhub_list",
    label: "MemoryHub List",
    description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_list,
    parameters: Type.Object({
      limit: Type.Optional(
        Type.Integer({
          description: "Max results (default: 20)",
          minimum: 1,
          maximum: 100,
        }),
      ),
      scope: Type.Optional(
        Type.String({ description: "Filter by scope" }),
      ),
      content_type: Type.Optional(
        contentTypeFilter,
      ),
      cursor: Type.Optional(
        Type.String({
          description: "Pagination cursor from previous result",
        }),
      ),
    }),
    async execute(_toolCallId, params) {
      return execute("memoryhub_list", params, "List failed");
    },
  };

  const memoryhubWrite: AnyAgentTool = {
    name: "memoryhub_write",
    label: "MemoryHub Write",
    description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_write,
    parameters: Type.Object({
      content: Type.String({ description: "The memory text to store" }),
      scope: Type.Optional(
        Type.String({
          description:
            "Scope: user (default), project, campaign, role, organizational, enterprise",
        }),
      ),
      weight: Type.Optional(
        Type.Number({
          description: "Importance 0.0-1.0 (default: 0.7)",
          minimum: 0,
          maximum: 1,
        }),
      ),
      domains: Type.Optional(
        Type.Array(Type.String(), {
          description: "Domain labels for retrieval boosting",
        }),
      ),
      content_type: Type.Optional(
        contentTypeForWrite,
      ),
      metadata: Type.Optional(
        Type.Record(Type.String(), Type.Unknown(), {
          description: "Arbitrary key-value metadata",
        }),
      ),
      parent_id: Type.Optional(
        Type.String({ description: "Parent memory ID for branching" }),
      ),
      branch_type: Type.Optional(
        Type.String({
          description:
            "Branch type: revision, rationale, example, dissent",
        }),
      ),
    }),
    async execute(_toolCallId, params) {
      return execute("memoryhub_write", params, "Write failed");
    },
  };

  const memoryhubUpdate: AnyAgentTool = {
    name: "memoryhub_update",
    label: "MemoryHub Update",
    description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_update,
    parameters: Type.Object({
      memory_id: Type.String({
        description: "UUID of the memory to update",
      }),
      content: Type.Optional(
        Type.String({ description: "New content" }),
      ),
      weight: Type.Optional(
        Type.Number({
          description: "New importance weight",
          minimum: 0,
          maximum: 1,
        }),
      ),
      metadata: Type.Optional(
        Type.Record(Type.String(), Type.Unknown(), {
          description: "Updated metadata (merged with existing)",
        }),
      ),
      domains: Type.Optional(
        Type.Array(Type.String(), {
          description: "Updated domain labels",
        }),
      ),
    }),
    async execute(_toolCallId, params) {
      return execute("memoryhub_update", params, "Update failed");
    },
  };

  const memoryhubDelete: AnyAgentTool = {
    name: "memoryhub_delete",
    label: "MemoryHub Delete",
    description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_delete,
    parameters: Type.Object({
      memory_id: Type.String({
        description: "UUID of the memory to delete",
      }),
    }),
    async execute(_toolCallId, params) {
      return execute("memoryhub_delete", params, "Delete failed");
    },
  };

  return [
    memoryhubSearch,
    memoryhubRead,
    memoryhubList,
    memoryhubWrite,
    memoryhubUpdate,
    memoryhubDelete,
  ];
}
