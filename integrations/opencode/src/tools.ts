import { tool, type ToolDefinition } from "@opencode-ai/plugin";
import { type MemoryHubMcpClient } from "./mcp-client.js";
import type { MemoryHubConfig } from "./config.js";

const z = tool.schema;

function ok(title: string, data: unknown) {
  return { title, output: JSON.stringify(data, null, 2) };
}

function err(e: unknown, fallback: string): string {
  return `Error: ${e instanceof Error ? e.message : fallback}`;
}

/**
 * The six MemoryHub tools, keyed by tool name as opencode registers them.
 * Every body maps its params onto the MCP server's multiplexed
 * `memory(action=...)` tool. `withSession` handles lazy session
 * registration and one silent re-register retry on session expiry.
 */
export function createTools(
  mcpClient: MemoryHubMcpClient,
  config: MemoryHubConfig,
  withSession: <T>(fn: () => Promise<T>) => Promise<T>,
): Record<string, ToolDefinition> {
  return {
    memoryhub_search: tool({
      description:
        "Search through long-term memories. Use when you need context about past decisions, preferences, learned facts, or previously discussed topics.",
      args: {
        query: z.string().describe("Natural language search query"),
        limit: z
          .number()
          .int()
          .min(1)
          .max(50)
          .optional()
          .describe("Max results (default: 10)"),
        scope: z
          .string()
          .optional()
          .describe(
            "Filter by scope: user, project, campaign, role, organizational, enterprise",
          ),
        domains: z
          .array(z.string())
          .optional()
          .describe("Boost results tagged with these domain labels"),
        content_type: z
          .string()
          .optional()
          .describe("Filter: factual, behavioral, or all"),
      },
      async execute(args) {
        try {
          const options: Record<string, unknown> = {};
          if (args.limit) options.max_results = args.limit;
          if (args.content_type) options.content_type = args.content_type;

          const domains =
            args.domains ??
            (config.defaults.domains.length > 0
              ? config.defaults.domains
              : undefined);
          if (domains) options.domains = domains;

          const callParams: Record<string, unknown> = {
            query: args.query,
            options,
          };
          if (args.scope) callParams.scope = args.scope;
          if (config.defaults.projectId) {
            callParams.project_id = config.defaults.projectId;
          }

          const result = await withSession(() =>
            mcpClient.callMemory("search", callParams),
          );
          return ok("MemoryHub search", result);
        } catch (e) {
          return err(e, "Search failed");
        }
      },
    }),

    memoryhub_read: tool({
      description:
        "Retrieve a specific memory by its ID, optionally including its version history.",
      args: {
        memory_id: z.string().describe("UUID of the memory to read"),
        include_versions: z
          .boolean()
          .optional()
          .describe("Include version history (default: false)"),
        hydrate: z
          .boolean()
          .optional()
          .describe("Fetch full content for S3-backed memories (default: false)"),
      },
      async execute(args) {
        try {
          const options: Record<string, unknown> = {};
          if (args.include_versions) options.include_versions = true;
          if (args.hydrate) options.hydrate = true;

          const result = await withSession(() =>
            mcpClient.callMemory("read", {
              memory_id: args.memory_id,
              options,
            }),
          );
          return ok("MemoryHub read", result);
        } catch (e) {
          return err(e, "Read failed");
        }
      },
    }),

    memoryhub_list: tool({
      description:
        "List memories without semantic ranking, ordered by creation time. Use for browsing or auditing what has been stored.",
      args: {
        limit: z
          .number()
          .int()
          .min(1)
          .max(100)
          .optional()
          .describe("Max results (default: 20)"),
        scope: z.string().optional().describe("Filter by scope"),
        content_type: z
          .string()
          .optional()
          .describe("Filter: factual, behavioral, or all"),
        cursor: z
          .string()
          .optional()
          .describe("Pagination cursor from previous result"),
      },
      async execute(args) {
        try {
          const options: Record<string, unknown> = {};
          if (args.limit) options.max_results = args.limit;
          if (args.content_type) options.content_type = args.content_type;
          if (args.cursor) options.cursor = args.cursor;

          const callParams: Record<string, unknown> = { options };
          if (args.scope) callParams.scope = args.scope;
          if (config.defaults.projectId) {
            callParams.project_id = config.defaults.projectId;
          }

          const result = await withSession(() =>
            mcpClient.callMemory("list", callParams),
          );
          return ok("MemoryHub list", result);
        } catch (e) {
          return err(e, "List failed");
        }
      },
    }),

    memoryhub_write: tool({
      description:
        "Save information to long-term memory. Use for preferences, decisions, facts, and important context.",
      args: {
        content: z.string().describe("The memory text to store"),
        scope: z
          .string()
          .optional()
          .describe(
            "Scope: user (default), project, campaign, role, organizational, enterprise",
          ),
        weight: z
          .number()
          .min(0)
          .max(1)
          .optional()
          .describe("Importance 0.0-1.0 (default: 0.7)"),
        domains: z
          .array(z.string())
          .optional()
          .describe("Domain labels for retrieval boosting"),
        content_type: z
          .string()
          .optional()
          .describe("factual (default) or behavioral"),
        metadata: z
          .record(z.string(), z.unknown())
          .optional()
          .describe("Arbitrary key-value metadata"),
        parent_id: z
          .string()
          .optional()
          .describe("Parent memory ID for branching"),
        branch_type: z
          .string()
          .optional()
          .describe("Branch type: revision, rationale, example, dissent"),
      },
      async execute(args) {
        try {
          const scope = args.scope ?? config.defaults.scope;

          const options: Record<string, unknown> = {};
          if (args.weight !== undefined) options.weight = args.weight;
          if (args.content_type) options.content_type = args.content_type;
          if (args.metadata) options.metadata = args.metadata;
          if (args.parent_id) options.parent_id = args.parent_id;
          if (args.branch_type) options.branch_type = args.branch_type;
          if (args.domains) options.domains = args.domains;

          const callParams: Record<string, unknown> = {
            content: args.content,
            scope,
            options,
          };
          if (config.defaults.projectId) {
            callParams.project_id = config.defaults.projectId;
          }

          const result = await withSession(() =>
            mcpClient.callMemory("write", callParams),
          );
          return ok("MemoryHub write", result);
        } catch (e) {
          return err(e, "Write failed");
        }
      },
    }),

    memoryhub_update: tool({
      description:
        "Update an existing memory, creating a new version. The old version is preserved in the version chain.",
      args: {
        memory_id: z.string().describe("UUID of the memory to update"),
        content: z.string().optional().describe("New content"),
        weight: z
          .number()
          .min(0)
          .max(1)
          .optional()
          .describe("New importance weight"),
        metadata: z
          .record(z.string(), z.unknown())
          .optional()
          .describe("Updated metadata (merged with existing)"),
        domains: z
          .array(z.string())
          .optional()
          .describe("Updated domain labels"),
      },
      async execute(args) {
        try {
          const options: Record<string, unknown> = {};
          if (args.weight !== undefined) options.weight = args.weight;
          if (args.metadata) options.metadata = args.metadata;
          if (args.domains) options.domains = args.domains;

          const callParams: Record<string, unknown> = {
            memory_id: args.memory_id,
            options,
          };
          if (args.content) callParams.content = args.content;

          const result = await withSession(() =>
            mcpClient.callMemory("update", callParams),
          );
          return ok("MemoryHub update", result);
        } catch (e) {
          return err(e, "Update failed");
        }
      },
    }),

    memoryhub_delete: tool({
      description:
        "Delete a memory. This is a soft-delete — the memory and its version chain are marked as deleted but not physically removed.",
      args: {
        memory_id: z.string().describe("UUID of the memory to delete"),
      },
      async execute(args) {
        try {
          const result = await withSession(() =>
            mcpClient.callMemory("delete", {
              memory_id: args.memory_id,
            }),
          );
          return ok("MemoryHub delete", result);
        } catch (e) {
          return err(e, "Delete failed");
        }
      },
    }),
  };
}
