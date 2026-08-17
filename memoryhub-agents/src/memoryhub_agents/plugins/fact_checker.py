DAYS_BEFORE_EXPIRY = 7SEARCH_RESULTS_LIMIT = 50"""Fact Checker Agent plugin.

Processes temporal expiry and runs verification plugins against
memories with factual claims.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta

from memoryhub_agents.config import AgentConfig
from memoryhub_agents.lifecycle import AgentPlugin
from memoryhub_agents.mcp_client import MCPSession

logger = logging.getLogger(__name__)


class VerificationResult:
    """Result of a verification check."""

    def __init__(self, verified: bool, reason: str, plugin_name: str):
        self.verified = verified
        self.reason = reason
        self.plugin_name = plugin_name


class VerificationPlugin(ABC):
    """Base class for domain-specific verification backends."""

    @abstractmethod
    def can_verify(self, memory: dict) -> bool:
        """Return True if this plugin can verify the given memory."""

    @abstractmethod
    async def verify(self, memory: dict) -> VerificationResult:
        """Verify a memory's claims. Returns a VerificationResult."""


class CalendarPlugin(VerificationPlugin):
    """Verifies temporal claims by checking against current date.

    Handles memories with relevant_until timestamps:
    - Past relevant_until -> mark as expired
    - Within DAYS_BEFORE_EXPIRY days of relevant_until -> mark as expiring_soon
    """

    def can_verify(self, memory: dict) -> bool:
        return memory.get("relevant_until") is not None

    async def verify(self, memory: dict) -> VerificationResult:
        relevant_until_str = memory.get("relevant_until")
        if not relevant_until_str:
            return VerificationResult(True, "no temporal claim", "calendar")

        try:
            if isinstance(relevant_until_str, str):
                relevant_until = datetime.fromisoformat(relevant_until_str)
            else:
                relevant_until = relevant_until_str

            # Ensure timezone-aware comparison
            if relevant_until.tzinfo is None:
                relevant_until = relevant_until.replace(tzinfo=UTC)

            now = datetime.now(UTC)
            if relevant_until < now:
                return VerificationResult(
                    False,
                    f"expired on {relevant_until.isoformat()}",
                    "calendar",
                )
            if relevant_until < now + timedelta(days=7):
                return VerificationResult(
                    True,
                    f"expiring soon ({relevant_until.isoformat()})",
                    "calendar",
                )
            return VerificationResult(True, "current", "calendar")
        except (ValueError, TypeError) as exc:
            return VerificationResult(True, f"unparseable date: {exc}", "calendar")


class FactCheckerPlugin(AgentPlugin):
    """Fact Checker agent plugin for the shared framework."""

    def __init__(
        self, verification_plugins: list[VerificationPlugin] | None = None
    ):
        self._plugins = verification_plugins or [CalendarPlugin()]
        self._stats = {
            "checked": 0,
            "expired": 0,
            "expiring_soon": 0,
            "verified": 0,
        }

    async def on_start(self, config: AgentConfig, mcp: MCPSession) -> None:
        logger.info(
            "fact checker started with %d verification plugins: %s",
            len(self._plugins),
            [type(p).__name__ for p in self._plugins],
        )

    async def process(self, item: dict, mcp: MCPSession) -> dict:
        """Process a single memory for verification.

        Work item payload::

            {
                "memory_id": "uuid",
                "action": "verify"  # or "scan_expiry"
            }
        """
        action = item.get("action", "verify")

        if action == "scan_expiry":
            return await self._scan_expiry(mcp)

        memory_id = item.get("memory_id")
        if not memory_id:
            return {"status": "error", "reason": "missing memory_id"}

        return await self._verify_memory(memory_id, mcp)

    async def _verify_memory(self, memory_id: str, mcp: MCPSession) -> dict:
        """Run all applicable verification plugins against a memory."""
        try:
            memory = await mcp.call_tool("read", memory_id=memory_id)
        except Exception as exc:
            return {"status": "error", "reason": f"failed to read memory: {exc}"}

        if isinstance(memory, dict) and "memory" in memory:
            memory_data = memory["memory"]
        else:
            memory_data = memory

        self._stats["checked"] += 1
        results = []

        for plugin in self._plugins:
            if plugin.can_verify(memory_data):
                result = await plugin.verify(memory_data)
                results.append(
                    {
                        "plugin": result.plugin_name,
                        "verified": result.verified,
                        "reason": result.reason,
                    }
                )

                if not result.verified:
                    self._stats["expired"] += 1
                    try:
                        await mcp.call_tool(
                            "report",
                            memory_id=memory_id,
                            options={
                                "observed_behavior": (
                                    f"Fact check failed: {result.reason}"
                                )
                            },
                        )
                    except Exception:
                        logger.exception(
                            "failed to report contradiction for %s", memory_id
                        )
                elif "expiring soon" in result.reason:
                    self._stats["expiring_soon"] += 1
                else:
                    self._stats["verified"] += 1

        return {"status": "ok", "memory_id": memory_id, "results": results}

    async def _scan_expiry(self, mcp: MCPSession) -> dict:
        """Scan for memories approaching or past expiry."""
        expired = []
        expiring_soon = []

        try:
            result = await mcp.call_tool(
                "search",
                query="*",
                options={"temporal_status": "expired", "max_results": 50},
            )
            if isinstance(result, dict):
                expired = result.get("results", [])
        except Exception:
            logger.exception("failed to search for expired memories")

        try:
            result = await mcp.call_tool(
                "search",
                query="*",
                options={"temporal_status": "expiring_soon", "max_results": 50},
            )
            if isinstance(result, dict):
                expiring_soon = result.get("results", [])
        except Exception:
            logger.exception("failed to search for expiring memories")

        return {
            "status": "ok",
            "expired_count": len(expired),
            "expiring_soon_count": len(expiring_soon),
        }

    async def on_stop(self) -> None:
        logger.info("fact checker stats: %s", self._stats)

    @property
    def stats(self) -> dict:
        return dict(self._stats)
