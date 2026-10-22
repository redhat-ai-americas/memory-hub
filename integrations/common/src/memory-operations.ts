export interface MemoryDefaults {
  scope: string;
  projectId?: string;
  domains: string[];
}

export interface MemoryOperation {
  action: "search" | "read" | "list" | "write" | "update" | "delete";
  params: Record<string, unknown>;
}

export const MEMORY_TOOL_DESCRIPTIONS = {
  memoryhub_search:
    "Search through long-term memories. Use when you need context about past decisions, preferences, learned facts, or previously discussed topics.",
  memoryhub_read:
    "Retrieve a specific memory by its ID, optionally including its version history.",
  memoryhub_list:
    "List memories without semantic ranking, ordered by creation time. Use for browsing or auditing what has been stored.",
  memoryhub_write:
    "Save information to long-term memory. Use for preferences, decisions, facts, and important context.",
  memoryhub_update:
    "Update an existing memory, creating a new version. The old version is preserved in the version chain.",
  memoryhub_delete:
    "Delete a memory. This is a soft-delete — the memory and its version chain are marked as deleted but not physically removed.",
} as const;

function withProject(
  params: Record<string, unknown>,
  defaults: MemoryDefaults,
): Record<string, unknown> {
  return defaults.projectId
    ? { ...params, project_id: defaults.projectId }
    : params;
}

export function buildMemoryOperation(
  tool: keyof typeof MEMORY_TOOL_DESCRIPTIONS,
  args: Record<string, unknown>,
  defaults: MemoryDefaults,
): MemoryOperation {
  switch (tool) {
    case "memoryhub_search": {
      const options: Record<string, unknown> = {};
      if (args.limit) options.max_results = args.limit;
      if (args.content_type) options.content_type = args.content_type;
      const domains = args.domains ?? (defaults.domains.length ? defaults.domains : undefined);
      if (domains) options.domains = domains;
      const params: Record<string, unknown> = { query: args.query, options };
      if (args.scope) params.scope = args.scope;
      return { action: "search", params: withProject(params, defaults) };
    }
    case "memoryhub_read": {
      const options: Record<string, unknown> = {};
      if (args.include_versions) options.include_versions = true;
      if (args.hydrate) options.hydrate = true;
      return {
        action: "read",
        params: { memory_id: args.memory_id, options },
      };
    }
    case "memoryhub_list": {
      const options: Record<string, unknown> = {};
      if (args.limit) options.max_results = args.limit;
      if (args.content_type) options.content_type = args.content_type;
      if (args.cursor) options.cursor = args.cursor;
      const params: Record<string, unknown> = { options };
      if (args.scope) params.scope = args.scope;
      return { action: "list", params: withProject(params, defaults) };
    }
    case "memoryhub_write": {
      const options: Record<string, unknown> = {};
      for (const key of ["weight", "content_type", "metadata", "parent_id", "branch_type", "domains"]) {
        if (args[key] !== undefined) options[key] = args[key];
      }
      const params = {
        content: args.content,
        scope: args.scope ?? defaults.scope,
        options,
      };
      return { action: "write", params: withProject(params, defaults) };
    }
    case "memoryhub_update": {
      const options: Record<string, unknown> = {};
      for (const key of ["weight", "metadata", "domains"]) {
        if (args[key] !== undefined) options[key] = args[key];
      }
      const params: Record<string, unknown> = {
        memory_id: args.memory_id,
        options,
      };
      if (args.content) params.content = args.content;
      return { action: "update", params };
    }
    case "memoryhub_delete":
      return { action: "delete", params: { memory_id: args.memory_id } };
  }
}
