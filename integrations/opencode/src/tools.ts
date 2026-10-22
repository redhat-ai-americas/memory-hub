import { tool, type ToolDefinition } from "@opencode-ai/plugin";
import {
  buildMemoryOperation,
  MEMORY_TOOL_DESCRIPTIONS,
} from "../../common/src/memory-operations.js";
import { type MemoryHubMcpClient } from "./mcp-client.js";
import type { MemoryHubConfig } from "./config.js";

const z = tool.schema;

const contentTypeFilter = z
  .enum(["experiential", "knowledge", "behavioral", "procedural"])
  .describe("Filter by content type. Omit to include all types.");

const contentTypeForWrite = z
  .enum(["experiential", "knowledge", "behavioral", "procedural"])
  .describe(
    "Content type: experiential (server default), knowledge (facts and preferences), behavioral, or procedural.",
  );

function ok(title: string, data: unknown) {
  return { title, output: JSON.stringify(data, null, 2) };
}

function err(e: unknown, fallback: string) {
  return {
    title: "Error",
    output: e instanceof Error ? e.message : fallback,
  };
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
  async function execute(
    name: keyof typeof MEMORY_TOOL_DESCRIPTIONS,
    args: Record<string, unknown>,
    title: string,
    fallback: string,
  ) {
    try {
      const operation = buildMemoryOperation(name, args, config.defaults);
      const result = await withSession(() =>
        mcpClient.callMemory(operation.action, operation.params),
      );
      return ok(title, result);
    } catch (error) {
      return err(error, fallback);
    }
  }

  return {
    memoryhub_search: tool({
      description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_search,
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
        content_type: contentTypeFilter.optional(),
      },
      async execute(args) {
        return execute("memoryhub_search", args, "MemoryHub search", "Search failed");
      },
    }),

    memoryhub_read: tool({
      description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_read,
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
        return execute("memoryhub_read", args, "MemoryHub read", "Read failed");
      },
    }),

    memoryhub_list: tool({
      description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_list,
      args: {
        limit: z
          .number()
          .int()
          .min(1)
          .max(100)
          .optional()
          .describe("Max results (default: 20)"),
        scope: z.string().optional().describe("Filter by scope"),
        content_type: contentTypeFilter.optional(),
        cursor: z
          .string()
          .optional()
          .describe("Pagination cursor from previous result"),
      },
      async execute(args) {
        return execute("memoryhub_list", args, "MemoryHub list", "List failed");
      },
    }),

    memoryhub_write: tool({
      description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_write,
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
        content_type: contentTypeForWrite.optional(),
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
        return execute("memoryhub_write", args, "MemoryHub write", "Write failed");
      },
    }),

    memoryhub_update: tool({
      description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_update,
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
        return execute("memoryhub_update", args, "MemoryHub update", "Update failed");
      },
    }),

    memoryhub_delete: tool({
      description: MEMORY_TOOL_DESCRIPTIONS.memoryhub_delete,
      args: {
        memory_id: z.string().describe("UUID of the memory to delete"),
      },
      async execute(args) {
        return execute("memoryhub_delete", args, "MemoryHub delete", "Delete failed");
      },
    }),
  };
}
