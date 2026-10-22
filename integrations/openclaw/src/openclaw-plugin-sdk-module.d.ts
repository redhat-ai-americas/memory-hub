declare module "openclaw/plugin-sdk/plugin-entry" {
  export interface OpenClawPluginApi {
    id: string;
    name: string;
    config: Record<string, unknown>;
    pluginConfig?: Record<string, unknown>;
    logger: import("./openclaw-plugin-sdk.js").PluginLogger;
    registerTool(
      tool: import("./openclaw-plugin-sdk.js").AnyAgentTool,
      opts?: { name?: string; names?: string[] },
    ): void;
    on<K extends string>(
      hookName: K,
      handler: (...args: unknown[]) => unknown,
      opts?: { priority?: number; timeoutMs?: number },
    ): void;
    registerMemoryCapability(
      capability: import("./openclaw-plugin-sdk.js").MemoryPluginCapability,
    ): void;
    registerService(
      service: import("./openclaw-plugin-sdk.js").OpenClawPluginService,
    ): void;
  }

  export interface DefinePluginEntryOptions {
    id: string;
    name: string;
    description: string;
    kind?: "memory" | "context-engine";
    register: (api: OpenClawPluginApi) => void;
  }

  export interface DefinedPluginEntry {
    id: string;
    name: string;
    description: string;
  }

  export function definePluginEntry(
    options: DefinePluginEntryOptions,
  ): DefinedPluginEntry;
}
