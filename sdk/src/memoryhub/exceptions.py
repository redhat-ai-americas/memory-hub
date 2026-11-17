"""MemoryHub SDK exceptions."""


class MemoryHubError(Exception):
    """Base exception for all MemoryHub SDK errors."""

    def __init__(self, message: str, *, next_action: str | None = None):
        self.next_action = next_action
        super().__init__(message)


class AuthenticationError(MemoryHubError):
    """Failed to authenticate with the MemoryHub auth service.

    Raised when client_credentials grant fails, token refresh fails,
    or the server rejects a token with 401/403.
    """


class NotFoundError(MemoryHubError):
    """The requested memory or resource was not found (404 equivalent)."""

    def __init__(
        self,
        memory_id: str,
        message: str | None = None,
        *,
        next_action: str | None = None,
    ):
        self.memory_id = memory_id
        super().__init__(
            message or f"Memory not found: {memory_id}",
            next_action=next_action,
        )


class ToolError(MemoryHubError):
    """An MCP tool call returned an error response.

    Attributes:
        tool_name: The MCP tool that failed.
        detail: The error detail from the server.
    """

    def __init__(self, tool_name: str, detail: str, *, next_action: str | None = None):
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"{tool_name}: {detail}", next_action=next_action)


class PermissionDeniedError(ToolError):
    """The caller is not authorized to perform this operation."""


class ValidationError(ToolError):
    """Invalid parameter or request shape."""


class ConflictError(ToolError):
    """Conflict with existing state (e.g., already exists, already deleted)."""


class CurationVetoError(ToolError):
    """A curation rule blocked the operation."""


class ConnectionFailedError(MemoryHubError):
    """Failed to connect to the MemoryHub MCP server."""
