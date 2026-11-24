"""Wire-level tests for actionable MCP tool errors."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from src.middleware.actionable_errors import ActionableToolErrorsMiddleware


@pytest.mark.asyncio
async def test_tool_error_returns_structured_error_and_next_action():
    server = FastMCP("test", mask_error_details=True)
    server.add_middleware(ActionableToolErrorsMiddleware())

    @server.tool
    async def fail_auth() -> str:
        raise ToolError("Authentication failed")

    async with Client(server) as client:
        result = await client.call_tool("fail_auth", {}, raise_on_error=False)

    assert result.is_error
    assert result.structured_content == {
        "error": "Authentication failed",
        "next_action": "Run 'memoryhub doctor' to verify the connection and credentials.",
    }
    assert "Next action:" in result.content[0].text


@pytest.mark.asyncio
async def test_unexpected_error_hides_internal_details_but_has_recovery_action():
    server = FastMCP("test", mask_error_details=True)
    server.add_middleware(ActionableToolErrorsMiddleware())

    @server.tool
    async def fail_unexpectedly() -> str:
        raise RuntimeError("database-password=do-not-leak")

    async with Client(server) as client:
        result = await client.call_tool("fail_unexpectedly", {}, raise_on_error=False)

    assert result.is_error
    assert result.structured_content["error"] == (
        "MemoryHub could not complete the tool request."
    )
    assert "memoryhub doctor" in result.structured_content["next_action"]
    assert "do-not-leak" not in result.content[0].text
