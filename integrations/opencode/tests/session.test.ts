import { describe, it, expect, vi } from "vitest";
import { createSessionManager, isAuthError } from "../src/session.js";
import { McpClientError } from "../src/mcp-client.js";
import { createMockMcpClient, createMockLogger } from "./helpers.js";

const API_KEY = "mh-dev-0123456789abcdef";

describe("isAuthError", () => {
  it.each([
    "Authentication required. Call register_session first.",
    "session not found",
    "Session expired, please re-register",
  ])("matches %s", (msg) => {
    expect(isAuthError(new Error(msg))).toBe(true);
  });

  it("does not match unrelated errors or non-errors", () => {
    expect(isAuthError(new Error("connection refused"))).toBe(false);
    expect(isAuthError("session expired")).toBe(false);
    expect(isAuthError(undefined)).toBe(false);
  });
});

describe("createSessionManager", () => {
  it("registers lazily and only once", async () => {
    const client = createMockMcpClient({
      isConnected: vi.fn().mockReturnValue(false),
    });
    const manager = createSessionManager(client, API_KEY, createMockLogger());

    await manager.withSession(async () => "a");
    await manager.withSession(async () => "b");

    expect(client.connect).toHaveBeenCalledTimes(1);
    expect(client.registerSession).toHaveBeenCalledTimes(1);
    expect(client.registerSession).toHaveBeenCalledWith(API_KEY);
  });

  it("skips registration without an api key", async () => {
    const client = createMockMcpClient();
    const manager = createSessionManager(client, undefined, createMockLogger());
    await manager.withSession(async () => "x");
    expect(client.registerSession).not.toHaveBeenCalled();
  });

  it("re-registers once and retries on session expiry", async () => {
    const client = createMockMcpClient();
    const manager = createSessionManager(client, API_KEY, createMockLogger());

    const fn = vi
      .fn()
      .mockRejectedValueOnce(new McpClientError("Session expired", true))
      .mockResolvedValueOnce("recovered");

    const result = await manager.withSession(fn);

    expect(result).toBe("recovered");
    expect(fn).toHaveBeenCalledTimes(2);
    expect(client.resetSession).toHaveBeenCalledTimes(1);
    expect(client.registerSession).toHaveBeenCalledTimes(2);
  });

  it("retries only once — a second auth failure propagates", async () => {
    const client = createMockMcpClient();
    const manager = createSessionManager(client, API_KEY, createMockLogger());

    const fn = vi
      .fn()
      .mockRejectedValue(new McpClientError("session not found", true));

    await expect(manager.withSession(fn)).rejects.toThrow("session not found");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("concurrent first calls register only once (single-flight)", async () => {
    let resolveRegister!: (v: unknown) => void;
    const registerSession = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRegister = resolve;
        }),
    );
    const client = createMockMcpClient({
      isConnected: vi.fn().mockReturnValue(false),
      registerSession,
    });
    const manager = createSessionManager(client, API_KEY, createMockLogger());

    const a = manager.withSession(async () => "a");
    const b = manager.withSession(async () => "b");
    // let the shared ensureSession reach the registerSession await
    await vi.waitFor(() => expect(registerSession).toHaveBeenCalled());
    resolveRegister({
      sessionId: "s",
      userId: "u",
      name: "n",
      scopes: [],
      projectMemberships: [],
    });
    expect(await Promise.all([a, b])).toEqual(["a", "b"]);
    expect(client.connect).toHaveBeenCalledTimes(1);
    expect(registerSession).toHaveBeenCalledTimes(1);
  });

  it("concurrent auth failures reset the session only once", async () => {
    const client = createMockMcpClient();
    const manager = createSessionManager(client, API_KEY, createMockLogger());

    let failures = 0;
    const failingOnce = () =>
      vi.fn().mockImplementation(async () => {
        if (failures < 2) {
          failures++;
          throw new McpClientError("session expired", true);
        }
        return "recovered";
      });

    // Two in-flight calls that both fail with session expiry: only the
    // first may reset (a second reset would close the fresh transport the
    // first caller's retry is using).
    const fnA = failingOnce();
    const fnB = failingOnce();
    const [a, b] = await Promise.all([
      manager.withSession(fnA),
      manager.withSession(fnB),
    ]);

    expect(a).toBe("recovered");
    expect(b).toBe("recovered");
    expect(client.resetSession).toHaveBeenCalledTimes(1);
  });

  it("propagates non-auth errors without retrying", async () => {
    const client = createMockMcpClient();
    const manager = createSessionManager(client, API_KEY, createMockLogger());

    const fn = vi.fn().mockRejectedValue(new Error("connection refused"));

    await expect(manager.withSession(fn)).rejects.toThrow(
      "connection refused",
    );
    expect(fn).toHaveBeenCalledTimes(1);
    expect(client.resetSession).not.toHaveBeenCalled();
  });
});
