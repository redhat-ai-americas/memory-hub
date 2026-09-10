import { Type } from "@sinclair/typebox";
import type { MemoryHubMcpClient } from "./mcp-client.js";
import type { MemoryHubConfig } from "./config.js";
import type { AnyAgentTool, AgentToolResult } from "./openclaw-plugin-sdk.js";

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
): AnyAgentTool[] {
  const memoryhubSearch: AnyAgentTool = {
    name: "memoryhub_search",
    label: "MemoryHub Search",
    description:
      "Search through long-term memories. Use when you need context about past decisions, preferences, learned facts, or previously discussed topics.",
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
        Type.String({
          description: "Filter: factual, behavioral, or all",
        }),
      ),
    }),
    async execute(_toolCallId, params) {
      try {
        const options: Record<string, unknown> = {};
        if (params.limit) options.max_results = params.limit;
        if (params.content_type) options.content_type = params.content_type;

        const domains =
          (params.domains as string[] | undefined) ??
          (config.defaults.domains.length > 0
            ? config.defaults.domains
            : undefined);
        if (domains) options.domains = domains;

        const callParams: Record<string, unknown> = {
          query: params.query,
          options,
        };
        if (params.scope) callParams.scope = params.scope;
        if (config.defaults.projectId) {
          callParams.project_id = config.defaults.projectId;
        }

        const result = await mcpClient.callMemory("search", callParams);
        return textResult(result);
      } catch (e) {
        return errorResult(
          e instanceof Error ? e.message : "Search failed",
        );
      }
    },
  };

  const memoryhubRead: AnyAgentTool = {
    name: "memoryhub_read",
    label: "MemoryHub Read",
    description:
      "Retrieve a specific memory by its ID, optionally including its version history.",
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
      try {
        const options: Record<string, unknown> = {};
        if (params.include_versions) options.include_versions = true;
        if (params.hydrate) options.hydrate = true;

        const result = await mcpClient.callMemory("read", {
          memory_id: params.memory_id,
          options,
        });
        return textResult(result);
      } catch (e) {
        return errorResult(
          e instanceof Error ? e.message : "Read failed",
        );
      }
    },
  };

  const memoryhubList: AnyAgentTool = {
    name: "memoryhub_list",
    label: "MemoryHub List",
    description:
      "List memories without semantic ranking, ordered by creation time. Use for browsing or auditing what has been stored.",
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
        Type.String({
          description: "Filter: factual, behavioral, or all",
        }),
      ),
      cursor: Type.Optional(
        Type.String({
          description: "Pagination cursor from previous result",
        }),
      ),
    }),
    async execute(_toolCallId, params) {
      try {
        const options: Record<string, unknown> = {};
        if (params.limit) options.max_results = params.limit;
        if (params.content_type) options.content_type = params.content_type;
        if (params.cursor) options.cursor = params.cursor;

        const callParams: Record<string, unknown> = { options };
        if (params.scope) callParams.scope = params.scope;
        if (config.defaults.projectId) {
          callParams.project_id = config.defaults.projectId;
        }

        const result = await mcpClient.callMemory("list", callParams);
        return textResult(result);
      } catch (e) {
        return errorResult(
          e instanceof Error ? e.message : "List failed",
        );
      }
    },
  };

  const memoryhubWrite: AnyAgentTool = {
    name: "memoryhub_write",
    label: "MemoryHub Write",
    description:
      "Save information to long-term memory. Use for preferences, decisions, facts, and important context.",
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
        Type.String({
          description: "factual (default) or behavioral",
        }),
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
      try {
        const scope =
          (params.scope as string | undefined) ?? config.defaults.scope;

        const options: Record<string, unknown> = {};
        if (params.weight !== undefined) options.weight = params.weight;
        if (params.content_type) options.content_type = params.content_type;
        if (params.metadata) options.metadata = params.metadata;
        if (params.parent_id) options.parent_id = params.parent_id;
        if (params.branch_type) options.branch_type = params.branch_type;

        const domains = params.domains as string[] | undefined;
        if (domains) options.domains = domains;

        const callParams: Record<string, unknown> = {
          content: params.content,
          scope,
          options,
        };
        if (config.defaults.projectId) {
          callParams.project_id = config.defaults.projectId;
        }

        const result = await mcpClient.callMemory("write", callParams);
        return textResult(result);
      } catch (e) {
        return errorResult(
          e instanceof Error ? e.message : "Write failed",
        );
      }
    },
  };

  const memoryhubUpdate: AnyAgentTool = {
    name: "memoryhub_update",
    label: "MemoryHub Update",
    description:
      "Update an existing memory, creating a new version. The old version is preserved in the version chain.",
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
      try {
        const options: Record<string, unknown> = {};
        if (params.weight !== undefined) options.weight = params.weight;
        if (params.metadata) options.metadata = params.metadata;
        if (params.domains) options.domains = params.domains;

        const callParams: Record<string, unknown> = {
          memory_id: params.memory_id,
          options,
        };
        if (params.content) callParams.content = params.content;

        const result = await mcpClient.callMemory("update", callParams);
        return textResult(result);
      } catch (e) {
        return errorResult(
          e instanceof Error ? e.message : "Update failed",
        );
      }
    },
  };

  const memoryhubDelete: AnyAgentTool = {
    name: "memoryhub_delete",
    label: "MemoryHub Delete",
    description:
      "Delete a memory. This is a soft-delete — the memory and its version chain are marked as deleted but not physically removed.",
    parameters: Type.Object({
      memory_id: Type.String({
        description: "UUID of the memory to delete",
      }),
    }),
    async execute(_toolCallId, params) {
      try {
        const result = await mcpClient.callMemory("delete", {
          memory_id: params.memory_id,
        });
        return textResult(result);
      } catch (e) {
        return errorResult(
          e instanceof Error ? e.message : "Delete failed",
        );
      }
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
