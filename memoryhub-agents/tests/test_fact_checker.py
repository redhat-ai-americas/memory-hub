"""Tests for memoryhub_agents.plugins.fact_checker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from memoryhub_agents.plugins.fact_checker import (
    CalendarPlugin,
    FactCheckerPlugin,
    VerificationResult,
)


class TestVerificationResult:
    def test_construction(self):
        r = VerificationResult(True, "ok", "calendar")
        assert r.verified is True
        assert r.reason == "ok"
        assert r.plugin_name == "calendar"

    def test_construction_failed(self):
        r = VerificationResult(False, "expired", "calendar")
        assert r.verified is False


class TestCalendarPlugin:
    def setup_method(self):
        self.plugin = CalendarPlugin()

    def test_can_verify_with_relevant_until(self):
        assert self.plugin.can_verify(
            {"relevant_until": "2026-12-31T00:00:00+00:00"}
        )

    def test_can_verify_without_relevant_until(self):
        assert not self.plugin.can_verify({"content": "evergreen fact"})

    def test_can_verify_with_none_value(self):
        assert not self.plugin.can_verify({"relevant_until": None})

    @pytest.mark.asyncio
    async def test_verify_expired_memory(self):
        past = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        result = await self.plugin.verify({"relevant_until": past})
        assert not result.verified
        assert "expired" in result.reason
        assert result.plugin_name == "calendar"

    @pytest.mark.asyncio
    async def test_verify_expiring_soon_memory(self):
        soon = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        result = await self.plugin.verify({"relevant_until": soon})
        assert result.verified
        assert "expiring soon" in result.reason

    @pytest.mark.asyncio
    async def test_verify_current_memory(self):
        future = (datetime.now(UTC) + timedelta(days=90)).isoformat()
        result = await self.plugin.verify({"relevant_until": future})
        assert result.verified
        assert result.reason == "current"

    @pytest.mark.asyncio
    async def test_verify_unparseable_date(self):
        result = await self.plugin.verify(
            {"relevant_until": "not-a-date"}
        )
        assert result.verified  # conservative: don't flag unparseable as expired
        assert "unparseable" in result.reason

    @pytest.mark.asyncio
    async def test_verify_empty_string(self):
        result = await self.plugin.verify({"relevant_until": ""})
        assert result.verified
        assert result.reason == "no temporal claim"

    @pytest.mark.asyncio
    async def test_verify_datetime_object(self):
        """Handles pre-parsed datetime objects, not just strings."""
        future_dt = datetime.now(UTC) + timedelta(days=60)
        result = await self.plugin.verify({"relevant_until": future_dt})
        assert result.verified
        assert result.reason == "current"

    @pytest.mark.asyncio
    async def test_verify_naive_datetime_string(self):
        """Handles naive datetime strings by assuming UTC."""
        future = (datetime.now(UTC) + timedelta(days=60)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        result = await self.plugin.verify({"relevant_until": future})
        assert result.verified
        assert result.reason == "current"


class TestFactCheckerPlugin:
    @pytest.mark.asyncio
    async def test_process_missing_memory_id(self):
        plugin = FactCheckerPlugin()
        result = await plugin.process({"action": "verify"}, AsyncMock())
        assert result["status"] == "error"
        assert "missing memory_id" in result["reason"]

    @pytest.mark.asyncio
    async def test_process_verify_current(self):
        mcp = AsyncMock()
        future = (datetime.now(UTC) + timedelta(days=90)).isoformat()
        mcp.call_tool = AsyncMock(
            return_value={
                "memory": {
                    "id": "abc",
                    "content": "test",
                    "relevant_until": future,
                }
            }
        )
        plugin = FactCheckerPlugin()
        result = await plugin.process(
            {"action": "verify", "memory_id": "abc"}, mcp
        )
        assert result["status"] == "ok"
        assert result["memory_id"] == "abc"
        assert len(result["results"]) == 1
        assert result["results"][0]["verified"] is True
        assert plugin.stats["checked"] == 1
        assert plugin.stats["verified"] == 1

    @pytest.mark.asyncio
    async def test_process_verify_expired(self):
        mcp = AsyncMock()
        past = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        mcp.call_tool = AsyncMock(
            return_value={
                "memory": {
                    "id": "abc",
                    "content": "old fact",
                    "relevant_until": past,
                }
            }
        )
        plugin = FactCheckerPlugin()
        result = await plugin.process(
            {"action": "verify", "memory_id": "abc"}, mcp
        )
        assert result["status"] == "ok"
        assert result["results"][0]["verified"] is False
        assert plugin.stats["expired"] == 1
        # Should have called report for the contradiction
        report_calls = [
            c for c in mcp.call_tool.call_args_list if c.args[0] == "report"
        ]
        assert len(report_calls) == 1

    @pytest.mark.asyncio
    async def test_process_verify_expiring_soon(self):
        mcp = AsyncMock()
        soon = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        mcp.call_tool = AsyncMock(
            return_value={
                "memory": {
                    "id": "abc",
                    "content": "soon fact",
                    "relevant_until": soon,
                }
            }
        )
        plugin = FactCheckerPlugin()
        result = await plugin.process(
            {"action": "verify", "memory_id": "abc"}, mcp
        )
        assert result["status"] == "ok"
        assert result["results"][0]["verified"] is True
        assert plugin.stats["expiring_soon"] == 1

    @pytest.mark.asyncio
    async def test_process_verify_no_temporal_claim(self):
        """Memories without relevant_until are not checked by CalendarPlugin."""
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(
            return_value={
                "memory": {"id": "abc", "content": "evergreen fact"}
            }
        )
        plugin = FactCheckerPlugin()
        result = await plugin.process(
            {"action": "verify", "memory_id": "abc"}, mcp
        )
        assert result["status"] == "ok"
        assert len(result["results"]) == 0  # CalendarPlugin skips it
        assert plugin.stats["checked"] == 1

    @pytest.mark.asyncio
    async def test_process_verify_read_failure(self):
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))
        plugin = FactCheckerPlugin()
        result = await plugin.process(
            {"action": "verify", "memory_id": "abc"}, mcp
        )
        assert result["status"] == "error"
        assert "failed to read memory" in result["reason"]

    @pytest.mark.asyncio
    async def test_process_scan_expiry(self):
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(return_value={"results": []})
        plugin = FactCheckerPlugin()
        result = await plugin.process({"action": "scan_expiry"}, mcp)
        assert result["status"] == "ok"
        assert result["expired_count"] == 0
        assert result["expiring_soon_count"] == 0

    @pytest.mark.asyncio
    async def test_process_scan_expiry_with_results(self):
        mcp = AsyncMock()
        call_count = 0

        async def mock_call_tool(action, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # expired search
                return {"results": [{"id": "m1"}, {"id": "m2"}]}
            return {"results": [{"id": "m3"}]}  # expiring_soon search

        mcp.call_tool = mock_call_tool
        plugin = FactCheckerPlugin()
        result = await plugin.process({"action": "scan_expiry"}, mcp)
        assert result["expired_count"] == 2
        assert result["expiring_soon_count"] == 1

    @pytest.mark.asyncio
    async def test_process_default_action_is_verify(self):
        """When no action is specified, defaults to verify."""
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(side_effect=RuntimeError("read failed"))
        plugin = FactCheckerPlugin()
        result = await plugin.process({"memory_id": "abc"}, mcp)
        # Confirms it took the verify path (error from read attempt)
        assert result["status"] == "error"
        assert "failed to read memory" in result["reason"]

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        plugin = FactCheckerPlugin()
        assert plugin.stats == {
            "checked": 0,
            "expired": 0,
            "expiring_soon": 0,
            "verified": 0,
        }

    @pytest.mark.asyncio
    async def test_on_start_logs(self, caplog):
        plugin = FactCheckerPlugin()
        config = AsyncMock()
        mcp = AsyncMock()
        with caplog.at_level("INFO"):
            await plugin.on_start(config, mcp)
        assert "fact checker started" in caplog.text
        assert "CalendarPlugin" in caplog.text

    @pytest.mark.asyncio
    async def test_on_stop_logs(self, caplog):
        plugin = FactCheckerPlugin()
        with caplog.at_level("INFO"):
            await plugin.on_stop()
        assert "fact checker stats" in caplog.text

    @pytest.mark.asyncio
    async def test_report_failure_does_not_crash(self):
        """If reporting a contradiction fails, the plugin logs and continues."""
        mcp = AsyncMock()
        past = (datetime.now(UTC) - timedelta(days=10)).isoformat()

        call_count = 0

        async def mock_call_tool(action, **kwargs):
            nonlocal call_count
            call_count += 1
            if action == "read":
                return {
                    "memory": {
                        "id": "abc",
                        "relevant_until": past,
                    }
                }
            if action == "report":
                raise RuntimeError("MCP down")
            return None

        mcp.call_tool = mock_call_tool
        plugin = FactCheckerPlugin()
        result = await plugin.process(
            {"action": "verify", "memory_id": "abc"}, mcp
        )
        # Should still return ok despite report failure
        assert result["status"] == "ok"
        assert result["results"][0]["verified"] is False
