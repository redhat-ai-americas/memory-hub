"""Trace Reviewer Agent plugin.

Reviews conversation content to extract memories that working agents
missed during sessions. Writes extracted memories with OBO ownership.

Operates in degraded mode when conversation persistence (#168) is
unavailable: expects thread content in the work item payload.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from memoryhub_agents.config import AgentConfig
from memoryhub_agents.lifecycle import AgentPlugin
from memoryhub_agents.mcp_client import MCPSession

logger = logging.getLogger(__name__)

# Phrases that signal memory-worthy content in assistant messages.
_SIGNAL_PHRASES = (
    "we decided",
    "the decision is",
    "going forward",
    "lesson learned",
    "remember that",
    "important:",
    "always use",
    "never use",
    "prefer",
    "convention is",
    "the rule is",
    "from now on",
    "note to self",
    "key takeaway",
    "turns out that",
)


@dataclass
class ExtractedMemory:
    """A memory extracted from a conversation thread."""

    content: str
    scope: str
    weight: float
    domains: list[str] | None = None


class TraceReviewerPlugin(AgentPlugin):
    """Trace Reviewer agent plugin for the shared framework.

    Work item payload (degraded mode)::

        {
            "thread_id": "uuid",
            "owner_id": "user who owns the thread",
            "messages": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ],
            "project_id": "optional project context"
        }

    Work item payload (full mode, requires #168)::

        {
            "thread_id": "uuid",
            "action": "review"
        }
    """

    def __init__(self) -> None:
        self._stats: dict[str, int] = {
            "reviewed": 0,
            "extracted": 0,
            "skipped": 0,
            "errors": 0,
        }

    async def on_start(self, config: AgentConfig, mcp: MCPSession) -> None:
        logger.info("trace reviewer started for tenant %s", config.tenant_id)

    async def process(self, item: dict, mcp: MCPSession) -> dict:
        """Process a single trace-review work item.

        Validates the payload, extracts candidate memories via heuristic
        signal-phrase matching, deduplicates against existing memories,
        and writes new ones with OBO ownership.
        """
        thread_id = item.get("thread_id")
        if not thread_id:
            return {"status": "error", "reason": "missing thread_id"}

        owner_id = item.get("owner_id")
        if not owner_id:
            return {"status": "error", "reason": "missing owner_id"}

        messages = item.get("messages")
        if not messages:
            return {
                "status": "error",
                "reason": "missing messages (degraded mode requires messages in payload)",
            }

        self._stats["reviewed"] += 1

        extracted = _extract_memories(messages)
        if not extracted:
            self._stats["skipped"] += 1
            return {
                "status": "ok",
                "thread_id": thread_id,
                "extracted": 0,
                "reason": "no extractable memories",
            }

        written = await self._write_new_memories(extracted, item, mcp)
        self._stats["extracted"] += written
        return {
            "status": "ok",
            "thread_id": thread_id,
            "extracted": written,
            "candidates": len(extracted),
        }

    async def _write_new_memories(
        self,
        candidates: list[ExtractedMemory],
        item: dict,
        mcp: MCPSession,
    ) -> int:
        """Deduplicate candidates and write genuinely new memories."""
        owner_id = item["owner_id"]
        thread_id = item["thread_id"]
        written = 0

        for memory in candidates:
            try:
                search_result = await mcp.call_tool(
                    "search",
                    query=memory.content,
                    options={"max_results": 3, "owner_id": owner_id},
                )
                results = []
                if isinstance(search_result, dict):
                    results = search_result.get("results", [])

                if _has_near_duplicate(results, memory.content):
                    continue

                write_opts: dict = {
                    "weight": memory.weight,
                    "owner_id": owner_id,
                    "driver_id": owner_id,
                }
                if memory.domains:
                    write_opts["domains"] = memory.domains
                if item.get("project_id"):
                    write_opts["project_id"] = item["project_id"]

                await mcp.call_tool(
                    "write",
                    content=memory.content,
                    scope=memory.scope,
                    options=write_opts,
                )
                written += 1

            except Exception:
                self._stats["errors"] += 1
                logger.exception(
                    "failed to write extracted memory from thread %s", thread_id
                )

        return written

    async def on_stop(self) -> None:
        logger.info("trace reviewer stats: %s", self._stats)

    @property
    def stats(self) -> dict[str, int]:
        """Current processing statistics."""
        return dict(self._stats)


# ---------------------------------------------------------------------------
# Extraction helpers (module-level, easily testable)
# ---------------------------------------------------------------------------


def _extract_memories(messages: list[dict]) -> list[ExtractedMemory]:
    """Extract potential memories from conversation messages.

    Uses heuristic signal-phrase matching on assistant messages.
    Deliberately conservative -- only extracts when a signal phrase
    is present and the surrounding sentence is long enough to be
    meaningful. One extraction per message to avoid noise.
    """
    extracted: list[ExtractedMemory] = []

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if not content or len(content) < 50:
            continue

        content_lower = content.lower()
        for phrase in _SIGNAL_PHRASES:
            if phrase in content_lower:
                memory_content = _extract_around_phrase(content, phrase)
                if memory_content and len(memory_content) >= 30:
                    extracted.append(
                        ExtractedMemory(
                            content=memory_content,
                            scope="user",
                            weight=0.7,
                        )
                    )
                break  # one extraction per message

    return extracted


def _extract_around_phrase(text: str, phrase: str) -> str | None:
    """Extract the sentence containing a signal phrase.

    Finds the nearest sentence boundaries (periods) around the phrase
    and returns that slice, capped at 500 characters.
    """
    lower = text.lower()
    idx = lower.find(phrase)
    if idx < 0:
        return None

    # Find sentence boundaries
    start = text.rfind(".", 0, idx)
    start = start + 1 if start >= 0 else 0

    end = text.find(".", idx + len(phrase))
    end = end + 1 if end >= 0 else len(text)

    result = text[start:end].strip()
    if len(result) > 500:
        result = result[:500]
    return result


def _has_near_duplicate(search_results: list, content: str) -> bool:
    """Check if any search result is a near-duplicate of the content.

    Uses token-level Jaccard similarity as a cheap heuristic.
    Production would use embedding similarity from search scores.
    """
    for result in search_results:
        if isinstance(result, dict):
            existing = result.get("content", "")
            if existing and _jaccard_similarity(existing, content) > 0.7:
                return True
    return False


def _jaccard_similarity(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
