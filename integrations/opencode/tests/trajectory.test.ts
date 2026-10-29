import { describe, it, expect, vi } from "vitest";
import { createTrajectoryRecorder, redactSecrets, clip } from "../src/trajectory.js";
import { resolveConfig } from "../src/config.js";
import {
  createMockMcpClient,
  createMockLogger,
  testConfig,
  passthroughSession,
} from "./helpers.js";

const on = (projectId?: string) =>
  testConfig({
    recordTrajectory: { enabled: true, maxToolOutputChars: 200 },
    defaults: { scope: "user", projectId, domains: [] },
  });

describe("trajectory recording", () => {
  it("is off by default and records nothing", async () => {
    const client = createMockMcpClient();
    const rec = createTrajectoryRecorder(client, testConfig(), createMockLogger(), passthroughSession);
    await rec.onUserMessage("s1", "deploy the api");
    await rec.onToolExecuted(
      { tool: "bash", sessionID: "s1", callID: "c1", args: { command: "ls" } },
      { title: "ls", output: "a b", metadata: {} },
    );
    expect(client.callThread).not.toHaveBeenCalled();
    expect(resolveConfig({}, { env: {}, home: "/nonexistent" }).recordTrajectory.enabled).toBe(false);
    expect(
      resolveConfig({}, { env: { MEMORYHUB_RECORD_TRAJECTORY: "1" }, home: "/nonexistent" }).recordTrajectory.enabled,
    ).toBe(true);
  });

  it("creates one thread per session and appends call/result pairs in order", async () => {
    const client = createMockMcpClient();
    vi.mocked(client.callThread).mockImplementation(async (action: string) =>
      action === "create" ? { id: "thread-1" } : {},
    );
    const rec = createTrajectoryRecorder(client, on("proj-1"), createMockLogger(), passthroughSession);
    await rec.onUserMessage("s1", "deploy the api");
    await rec.onToolExecuted(
      { tool: "bash", sessionID: "s1", callID: "c1", args: { command: "podman build ." } },
      { title: "build", output: "Successfully tagged", metadata: {} },
    );
    const calls = vi.mocked(client.callThread).mock.calls;
    expect(calls.filter(([a]) => a === "create")).toHaveLength(1);
    expect(calls[0][1]).toMatchObject({ scope: "project", options: { scope_id: "proj-1" } });
    const appends = calls.filter(([a]) => a === "append").map(([, p]) => p as Record<string, any>);
    expect(appends.map((p) => p.role)).toEqual(["user", "tool_call", "tool_result"]);
    expect(appends[1].options.tool_call_id).toBe("c1");
    expect(appends[2].options.tool_call_id).toBe("c1");
    expect(JSON.parse(appends[1].content)).toEqual({ tool: "bash", args: { command: "podman build ." } });
    expect(await rec.threadFor("s1")).toBe("thread-1");
  });

  it("skips MemoryHub's own tools", async () => {
    const client = createMockMcpClient();
    vi.mocked(client.callThread).mockResolvedValue({ id: "t" });
    const rec = createTrajectoryRecorder(client, on(), createMockLogger(), passthroughSession);
    await rec.onToolExecuted(
      { tool: "memoryhub_search", sessionID: "s1", callID: "c1", args: {} },
      { title: "", output: "[]", metadata: {} },
    );
    expect(client.callThread).not.toHaveBeenCalled();
  });

  it("redacts secret shapes and clips long output", async () => {
    const key = "AKIA" + "ABCDEFGHIJKLMNOP";
    const token = "ghp" + "_" + "x".repeat(36);
    expect(redactSecrets(`key ${key} and ${token}`)).toBe("key [REDACTED] and [REDACTED]");
    expect(redactSecrets("password=hunter2hunter2")).toBe("password=[REDACTED]");
    expect(redactSecrets("Authorization: Bearer abcdefghijklmnopqrstu")).toBe("Authorization: Bearer [REDACTED]");
    const long = clip("y".repeat(1000), 200);
    expect(long.length).toBeLessThan(260);
    expect(long).toContain("chars omitted");
  });

  it("never throws when MemoryHub is unreachable", async () => {
    const client = createMockMcpClient();
    vi.mocked(client.callThread).mockRejectedValue(new Error("down"));
    const logger = createMockLogger();
    const rec = createTrajectoryRecorder(client, on(), logger, passthroughSession);
    await expect(rec.onUserMessage("s1", "hello there")).resolves.toBeUndefined();
    expect(logger.warn).toHaveBeenCalled();
  });
});
