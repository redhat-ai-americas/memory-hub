import { Plugin } from "@opencode/plugin";
import { MEMORY_TOOL_DESCRIPTIONS } from "../../common/src/memory-operations.js";
import { resolveConfig } from "./config.js";
import { createLogger } from "./logger.js";
import { createMcpClient } from "./mcp-client.js";
import { createSessionManager } from "./session.js";
import { buildMemoryOperation } from "../../common/src/memory-operations.js";

const string = { type: "string" } as const;
const number = { type: "number" } as const;
const boolean = { type: "boolean" } as const;
const stringArray = { type: "array", items: string } as const;
const contentTypes = ["experiential", "knowledge", "behavioral", "procedural"];

const inputs: Record<string, Record<string, unknown>> = {
  memoryhub_search: {
    query: string, limit: number, scope: string, domains: stringArray,
    content_type: { type: "string", enum: contentTypes },
  },
  memoryhub_read: { memory_id: string, include_versions: boolean, hydrate: boolean },
  memoryhub_list: {
    limit: number, scope: string, cursor: string,
    content_type: { type: "string", enum: contentTypes },
  },
  memoryhub_write: {
    content: string, scope: string, weight: number, domains: stringArray,
    content_type: { type: "string", enum: contentTypes },
    metadata: { type: "object", additionalProperties: true },
    parent_id: string, branch_type: string,
  },
  memoryhub_update: {
    memory_id: string, content: string, weight: number, domains: stringArray,
    metadata: { type: "object", additionalProperties: true },
  },
  memoryhub_delete: { memory_id: string },
};

const required: Record<string, string[]> = {
  memoryhub_search: ["query"],
  memoryhub_read: ["memory_id"],
  memoryhub_write: ["content"],
  memoryhub_update: ["memory_id"],
  memoryhub_delete: ["memory_id"],
};

function result(title: string, value: unknown) {
  return { title, content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] };
}

export const V2MemoryHubPlugin = Plugin.define({
  id: "memoryhub",
  async setup(ctx) {
    const config = resolveConfig(ctx.options);
    const logger = createLogger();
    if (config.needsSetup) {
      logger.warn("missing server URL or API key — plugin disabled");
      return;
    }

    const client = createMcpClient(config.server.url);
    const { withSession } = createSessionManager(client, config.auth.apiKey, logger);
    logger.info(`initialized (server: ${config.server.url})`);

    await ctx.tool.transform((editor) => {
      for (const name of Object.keys(inputs)) {
        editor.add({
          name,
          description: MEMORY_TOOL_DESCRIPTIONS[name as keyof typeof MEMORY_TOOL_DESCRIPTIONS],
          input: {
            type: "object",
            properties: inputs[name],
            required: required[name] ?? [],
            additionalProperties: false,
          },
          execute: async (args) => {
            const operation = buildMemoryOperation(name, args as Record<string, unknown>, config.defaults);
            const value = await withSession(() => client.callMemory(operation.action, operation.params));
            return result(`MemoryHub ${name.replace("memoryhub_", "")}`, value);
          },
        });
      }
    });
  },
});
