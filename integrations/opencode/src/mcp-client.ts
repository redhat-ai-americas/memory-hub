import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import {
  createMcpClient as createSharedMcpClient,
  McpClientError,
} from "../../common/src/mcp-client.js";
import type {
  McpRuntime,
  McpTransport,
  MemoryHubMcpClient,
  SessionInfo,
} from "../../common/src/index.js";

const runtime: McpRuntime = {
  createTransport(url) {
    return new StreamableHTTPClientTransport(url);
  },
  createClient(name, version) {
    const client = new Client({ name, version });
    return {
      connect(transport: McpTransport) {
        return client.connect(transport as StreamableHTTPClientTransport);
      },
      callTool(request) {
        return client.callTool(
          request as Parameters<typeof client.callTool>[0],
        );
      },
    };
  },
};

export function createMcpClient(serverUrl: string): MemoryHubMcpClient {
  return createSharedMcpClient(serverUrl, runtime, "opencode-memoryhub");
}

export { McpClientError };
export type { MemoryHubMcpClient, SessionInfo };
