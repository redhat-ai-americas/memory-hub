export interface MemoryDefaults {
  scope: string;
  projectId?: string;
  domains: string[];
}

export interface MemoryOperation<Action extends string = string> {
  action: Action;
  params: Record<string, unknown>;
}

export interface MemoryToolContract<Action extends string = string> {
  readonly description: string;
  readonly buildOperation: (
    args: Record<string, unknown>,
    defaults: MemoryDefaults,
  ) => MemoryOperation<Action>;
}

export type MemoryToolCatalog = Readonly<Record<string, MemoryToolContract>>;

function withProject(
  params: Record<string, unknown>,
  defaults: MemoryDefaults,
): Record<string, unknown> {
  return defaults.projectId
    ? { ...params, project_id: defaults.projectId }
    : params;
}

const CORE_MEMORY_TOOL_CATALOG = {
  memoryhub_search: {
    description:
      "Search through long-term memories. Use when you need context about past decisions, preferences, learned facts, or previously discussed topics.",
    buildOperation: (args, defaults) => {
      const options: Record<string, unknown> = {};
      if (args.limit) options.max_results = args.limit;
      if (args.content_type) options.content_type = args.content_type;
      const domains = args.domains ?? (defaults.domains.length ? defaults.domains : undefined);
      if (domains) options.domains = domains;
      const params: Record<string, unknown> = { query: args.query, options };
      if (args.scope) params.scope = args.scope;
      return { action: "search", params: withProject(params, defaults) };
    },
  },
  memoryhub_read: {
    description:
      "Retrieve a specific memory by its ID, optionally including its version history.",
    buildOperation: (args) => {
      const options: Record<string, unknown> = {};
      if (args.include_versions) options.include_versions = true;
      if (args.hydrate) options.hydrate = true;
      return {
        action: "read",
        params: { memory_id: args.memory_id, options },
      };
    },
  },
  memoryhub_list: {
    description:
      "List memories without semantic ranking, ordered by creation time. Use for browsing or auditing what has been stored.",
    buildOperation: (args, defaults) => {
      const options: Record<string, unknown> = {};
      if (args.limit) options.max_results = args.limit;
      if (args.content_type) options.content_type = args.content_type;
      if (args.cursor) options.cursor = args.cursor;
      const params: Record<string, unknown> = { options };
      if (args.scope) params.scope = args.scope;
      return { action: "list", params: withProject(params, defaults) };
    },
  },
  memoryhub_write: {
    description:
      "Save information to long-term memory. Use for preferences, decisions, facts, and important context.",
    buildOperation: (args, defaults) => {
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
    },
  },
  memoryhub_update: {
    description:
      "Update an existing memory, creating a new version. The old version is preserved in the version chain.",
    buildOperation: (args) => {
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
    },
  },
  memoryhub_delete: {
    description:
      "Delete a memory. This is a soft-delete — the memory and its version chain are marked as deleted but not physically removed.",
    buildOperation: (args) => ({
      action: "delete",
      params: { memory_id: args.memory_id },
    }),
  },
} satisfies MemoryToolCatalog;

export type DefaultMemoryToolName = keyof typeof CORE_MEMORY_TOOL_CATALOG;

/** The host-neutral catalog. Adapters select which contracts to expose. */
export const MEMORY_TOOL_CATALOG: MemoryToolCatalog = Object.freeze({
  ...CORE_MEMORY_TOOL_CATALOG,
});

/** The default profile retained for the current OpenClaw/OpenCode behaviour. */
export const DEFAULT_MEMORY_TOOL_NAMES: readonly DefaultMemoryToolName[] = Object.freeze(
  Object.keys(CORE_MEMORY_TOOL_CATALOG) as DefaultMemoryToolName[],
);

/** Backward-compatible descriptions export for existing adapters. */
export const MEMORY_TOOL_DESCRIPTIONS: Readonly<Record<DefaultMemoryToolName, string>> =
  Object.freeze(
    Object.fromEntries(
      Object.entries(CORE_MEMORY_TOOL_CATALOG).map(([name, contract]) => [name, contract.description]),
    ) as Record<DefaultMemoryToolName, string>,
  );

export function extendMemoryToolCatalog(
  extensions: MemoryToolCatalog,
): MemoryToolCatalog {
  return Object.freeze({ ...MEMORY_TOOL_CATALOG, ...extensions });
}

export function buildMemoryOperation(
  tool: string,
  args: Record<string, unknown>,
  defaults: MemoryDefaults,
  catalog: MemoryToolCatalog = MEMORY_TOOL_CATALOG,
): MemoryOperation {
  const contract = catalog[tool];
  if (!contract) {
    throw new Error(`Unknown MemoryHub tool: ${tool}`);
  }
  return contract.buildOperation(args, defaults);
}
