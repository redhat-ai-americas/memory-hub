import { describe, it, expect, vi } from "vitest";
import {
  createRecallEngine,
  createSystemTransform,
  formatMemoriesXml,
  extractTextFromParts,
  MEMORY_BLOCK_MARKER,
  type LooseMessage,
  type LoosePart,
} from "../src/hooks.js";
import {
  createMockMcpClient,
  createMockLogger,
  testConfig,
  passthroughSession,
} from "./helpers.js";

function userParts(text: string): LoosePart[] {
  return [
    {
      id: "prt_1",
      sessionID: "ses_1",
      messageID: "msg_1",
      type: "text",
      text,
    },
  ];
}

function userMessage(text: string): LooseMessage {
  return { info: { role: "user" }, parts: userParts(text) };
}

function makeEngine(
  clientOverrides?: Parameters<typeof createMockMcpClient>[0],
  configOverrides?: Parameters<typeof testConfig>[0],
) {
  const client = createMockMcpClient(clientOverrides);
  const logger = createMockLogger();
  const engine = createRecallEngine(
    client,
    testConfig(configOverrides),
    logger,
    passthroughSession,
  );
  return { client, logger, engine };
}

describe("extractTextFromParts", () => {
  it("joins text parts and skips non-text, synthetic, and memory-block parts", () => {
    const parts: LoosePart[] = [
      { type: "text", text: "hello" },
      { type: "file", text: "ignored" },
      { type: "text", text: "injected", synthetic: true },
      { type: "text", text: `${MEMORY_BLOCK_MARKER}\nold block` },
      { type: "text", text: "world" },
    ];
    expect(extractTextFromParts(parts)).toBe("hello\nworld");
  });
});

describe("formatMemoriesXml", () => {
  it("renders numbered entries with scope, weight, and score", () => {
    const xml = formatMemoriesXml([
      { content: "User prefers dark mode", scope: "user", weight: 0.9, relevance_score: 0.92 },
      { stub: "A stub memory", scope: "project" },
    ]);
    expect(xml).toContain(MEMORY_BLOCK_MARKER);
    expect(xml).toContain("untrusted historical data");
    expect(xml).toContain(
      "1. [scope:user, weight:0.9] User prefers dark mode (92%)",
    );
    expect(xml).toContain("2. [scope:project, weight:?] A stub memory");
    expect(xml).toContain("</relevant-memories>");
  });

  it("returns empty string for no results", () => {
    expect(formatMemoriesXml([])).toBe("");
  });
});

describe("recall engine — onChatMessage", () => {
  it("searches with configured options and stores a pending block", async () => {
    const { client, engine } = makeEngine(
      {
        callMemory: vi.fn().mockResolvedValue({
          results: [{ content: "fact", scope: "user", weight: 0.8 }],
        }),
      },
      {
        autoRecall: { enabled: true, maxResults: 7, maxResponseTokens: 2000 },
        defaults: { scope: "user", projectId: "proj-1", domains: ["k8s"] },
      },
    );

    await engine.onChatMessage({ parts: userParts("how do we deploy?") });

    expect(client.callMemory).toHaveBeenCalledWith("search", {
      query: "how do we deploy?",
      project_id: "proj-1",
      options: {
        max_results: 7,
        max_response_tokens: 2000,
        domains: ["k8s"],
      },
    });
    expect(engine.pendingBlock()).toContain("fact");
  });

  it("skips short queries", async () => {
    const { client, engine } = makeEngine();
    await engine.onChatMessage({ parts: userParts("hi") });
    expect(client.callMemory).not.toHaveBeenCalled();
    expect(engine.pendingBlock()).toBeNull();
  });

  it("does nothing when autoRecall is disabled", async () => {
    const { client, engine } = makeEngine(undefined, {
      autoRecall: { enabled: false, maxResults: 10, maxResponseTokens: 4000 },
    });
    await engine.onChatMessage({ parts: userParts("a long enough query") });
    expect(client.callMemory).not.toHaveBeenCalled();
  });

  it("clears pending block when search returns nothing", async () => {
    const { engine } = makeEngine({
      callMemory: vi
        .fn()
        .mockResolvedValueOnce({
          results: [{ content: "old", scope: "user" }],
        })
        .mockResolvedValueOnce({ results: [] }),
    });
    await engine.onChatMessage({ parts: userParts("first query here") });
    expect(engine.pendingBlock()).not.toBeNull();
    await engine.onChatMessage({ parts: userParts("second query here") });
    expect(engine.pendingBlock()).toBeNull();
  });

  it("swallows search errors and warns", async () => {
    const { logger, engine } = makeEngine({
      callMemory: vi.fn().mockRejectedValue(new Error("server down")),
    });
    await expect(
      engine.onChatMessage({ parts: userParts("a long enough query") }),
    ).resolves.toBeUndefined();
    expect(logger.warn).toHaveBeenCalledWith(
      expect.stringContaining("server down"),
    );
    expect(engine.pendingBlock()).toBeNull();
  });

  it("clears the timeout timer when the search wins the race", async () => {
    vi.useFakeTimers();
    try {
      const { engine } = makeEngine({
        callMemory: vi.fn().mockResolvedValue({
          results: [{ content: "fast", scope: "user" }],
        }),
      });
      await engine.onChatMessage({ parts: userParts("a long enough query") });
      // if the 15s timer were still pending, this would be > 0
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("times out slow searches", async () => {
    vi.useFakeTimers();
    try {
      const { logger, engine } = makeEngine({
        callMemory: vi.fn().mockImplementation(
          () => new Promise(() => {}), // never resolves
        ),
      });
      const promise = engine.onChatMessage({
        parts: userParts("a long enough query"),
      });
      await vi.advanceTimersByTimeAsync(15_001);
      await promise;
      expect(logger.warn).toHaveBeenCalledWith(
        expect.stringContaining("timeout"),
      );
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("recall engine — onMessagesTransform", () => {
  async function primedEngine() {
    const { engine } = makeEngine({
      callMemory: vi.fn().mockResolvedValue({
        results: [{ content: "recalled fact", scope: "user", weight: 0.8 }],
      }),
    });
    await engine.onChatMessage({ parts: userParts("what did we decide?") });
    expect(engine.pendingBlock()).not.toBeNull();
    return engine;
  }

  it("unshifts a synthetic text part into the last user message", async () => {
    const engine = await primedEngine();
    const last = userMessage("what did we decide?");
    const output = {
      messages: [
        userMessage("earlier message"),
        { info: { role: "assistant" }, parts: [{ type: "text", text: "reply" }] },
        last,
      ],
    };

    engine.onMessagesTransform(output);

    expect(last.parts).toHaveLength(2);
    const injected = last.parts[0];
    expect(injected.type).toBe("text");
    expect(injected.synthetic).toBe(true);
    expect(injected.text).toContain("recalled fact");
    // host-required identity fields inherited from the cloned sibling part
    expect(injected.id).toBe("prt_1");
    expect(injected.sessionID).toBe("ses_1");
    expect(injected.messageID).toBe("msg_1");
    // earlier messages untouched
    expect(output.messages[0].parts).toHaveLength(1);
  });

  it("is idempotent when the marker is already present", async () => {
    const engine = await primedEngine();
    const last = userMessage("what did we decide?");
    const output = { messages: [last] };
    engine.onMessagesTransform(output);
    engine.onMessagesTransform(output);
    expect(last.parts).toHaveLength(2);
  });

  it("re-injects on a fresh request copy of the same turn", async () => {
    const engine = await primedEngine();
    const first = { messages: [userMessage("what did we decide?")] };
    engine.onMessagesTransform(first);
    expect(first.messages[0].parts).toHaveLength(2);
    // The transform output is per-request; a later request in the same turn
    // rebuilds messages from the session store without our injected part.
    const second = { messages: [userMessage("what did we decide?")] };
    engine.onMessagesTransform(second);
    expect(second.messages[0].parts).toHaveLength(2);
  });

  it("does nothing without a pending block", () => {
    const { engine } = makeEngine();
    const last = userMessage("hello there");
    engine.onMessagesTransform({ messages: [last] });
    expect(last.parts).toHaveLength(1);
  });

  it("does nothing when there is no user message", async () => {
    const engine = await primedEngine();
    const output = {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "text", text: "x" }] },
      ],
    };
    engine.onMessagesTransform(output);
    expect(output.messages[0].parts).toHaveLength(1);
  });
});

describe("createSystemTransform", () => {
  it("appends the protocol once", () => {
    const transform = createSystemTransform("PROTOCOL CONTENT");
    const output = { system: ["base prompt"] };
    transform(output);
    transform(output);
    expect(output.system).toEqual(["base prompt", "PROTOCOL CONTENT"]);
  });
});
