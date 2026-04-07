"""Synthetic topic fixtures for the two-vector retrieval benchmark.

200 memories total across 4 topics (50 each), plus per-topic focus strings
that the benchmark embeds into session focus vectors. Content mimics real
memory-hub project memories (decisions, lessons, configuration choices).
"""

from tests.perf.fixtures.topics import auth, deployment, mcp_tools, ui

TOPICS = ["deployment", "mcp_tools", "ui", "auth"]

TOPIC_MODULES = {
    "deployment": deployment,
    "mcp_tools": mcp_tools,
    "ui": ui,
    "auth": auth,
}

FOCUS_STRINGS = {topic: TOPIC_MODULES[topic].FOCUS_STRING for topic in TOPICS}


def all_memories() -> list[dict]:
    """Return every fixture memory tagged with its ground-truth topic."""
    out: list[dict] = []
    for topic in TOPICS:
        for idx, mem in enumerate(TOPIC_MODULES[topic].MEMORIES):
            out.append(
                {
                    "id": f"{topic}-{idx:03d}",
                    "topic": topic,
                    "content": mem["content"],
                    "weight": mem["weight"],
                }
            )
    return out


__all__ = ["TOPICS", "TOPIC_MODULES", "FOCUS_STRINGS", "all_memories"]
