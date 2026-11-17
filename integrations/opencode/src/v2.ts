import { Plugin } from "@opencode/plugin";
import {
  DEFAULT_MEMORY_TOOL_NAMES,
  MEMORY_TOOL_CATALOG,
  buildMemoryOperation,
} from "../../common/src/memory-operations.js";
import { PROTOCOL_CONTENT } from "../../common/src/protocol.js";
import { formatMemories, searchWithTimeout } from "../../common/src/recall.js";
import { resolveConfig } from "./config.js";
import { createLogger } from "./logger.js";
import { createMcpClient } from "./mcp-client.js";
import { createSessionManager } from "./session.js";

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
  return { content: `${title}\n${JSON.stringify(value, null, 2)}` };
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

    const registrations: Array<{ dispose: () => Promise<void> }> = [];
    const toolRegistration = await ctx.tool.transform((editor) => {
      for (const name of DEFAULT_MEMORY_TOOL_NAMES) {
        editor.add({
          name,
          description: MEMORY_TOOL_CATALOG[name].description,
          input: {
            type: "object",
            properties: inputs[name],
            required: required[name] ?? [],
            additionalProperties: false,
          },
          execute: async (args) => {
            const operation = buildMemoryOperation(
              name,
              args as Record<string, unknown>,
              config.defaults,
              MEMORY_TOOL_CATALOG,
            );
            const value = await withSession(() => client.callMemory(operation.action, operation.params));
            return result(`MemoryHub ${name.replace("memoryhub_", "")}`, value);
          },
        });
      }
    });

    registrations.push(toolRegistration);

    const promptRegistration = await ctx.session.hook("prompt", async (input) => {
      if (!config.autoRecall.enabled || input.prompt.text.length < 5) return;
      try {
        const results = await searchWithTimeout(
          client,
          input.prompt.text,
          config,
          withSession,
        );
        if (results.length > 0) {
          input.prompt.text = `${formatMemories(results)}\n\n${input.prompt.text}`;
        }
      } catch (error) {
        logger.warn(
          `auto-recall failed: ${error instanceof Error ? error.message : "unknown error"}`,
        );
      }
    });
    registrations.push(promptRegistration);

    const contextRegistration = await ctx.session.hook("context", async (input) => {
      if (!input.system.some((part) => part.type === "text" && part.text === PROTOCOL_CONTENT)) {
        input.system.push({ type: "text", text: PROTOCOL_CONTENT });
      }
    });
    registrations.push(contextRegistration);

    return async () => {
      for (const registration of registrations.reverse()) {
        await registration.dispose();
      }
      await client.close();
      logger.info("stopped");
    };
  },
});
