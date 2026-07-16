"""Tests for extract_facts parameter forwarding and dispatch."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from src.tools.memory import _WRITE_OPTS, _forward


class TestExtractFactsForwarding:
    """Verify extract_facts is whitelisted and forwarded to write_memory."""

    def test_write_opts_contains_extract_facts(self):
        assert "extract_facts" in _WRITE_OPTS

    def test_forward_passes_extract_facts(self):
        opts = {"extract_facts": "eager", "weight": 0.9}
        result = _forward(opts, _WRITE_OPTS)
        assert result["extract_facts"] == "eager"
        assert result["weight"] == 0.9

    def test_forward_passes_extract_facts_off(self):
        opts = {"extract_facts": "off"}
        result = _forward(opts, _WRITE_OPTS)
        assert result["extract_facts"] == "off"

    @pytest.mark.asyncio
    @patch("src.tools.write_memory.write_memory", new_callable=AsyncMock)
    async def test_write_dispatch_forwards_extract_facts(self, mock_write):
        from src.tools.memory import memory

        mock_write.return_value = {"memory": {"id": "new"}}
        await memory(
            action="write", content="test content", scope="user",
            options={"extract_facts": "off"},
        )
        mock_write.assert_called_once()
        kw = mock_write.call_args[1]
        assert kw["extract_facts"] == "off"

    @pytest.mark.asyncio
    @patch("src.tools.write_memory.write_memory", new_callable=AsyncMock)
    async def test_write_dispatch_omits_extract_facts_when_not_set(self, mock_write):
        from src.tools.memory import memory

        mock_write.return_value = {"memory": {"id": "new"}}
        await memory(
            action="write", content="test content", scope="user",
        )
        mock_write.assert_called_once()
        kw = mock_write.call_args[1]
        assert "extract_facts" not in kw


class TestExtractFactsValidation:
    """Verify invalid extract_facts values are rejected."""

    @pytest.mark.asyncio
    @patch("src.tools.write_memory.write_memory", new_callable=AsyncMock)
    async def test_invalid_extract_facts_raises_tool_error(self, mock_write):
        from src.tools.memory import memory

        mock_write.side_effect = ToolError("Invalid extract_facts value 'bogus'")
        with pytest.raises(ToolError, match="Invalid extract_facts value"):
            await memory(
                action="write", content="test content", scope="user",
                options={"extract_facts": "bogus"},
            )
