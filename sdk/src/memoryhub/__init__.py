"""MemoryHub — Centralized, governed memory for AI agents."""

from memoryhub.client import MemoryHubClient
from memoryhub.exceptions import (
    AuthenticationError,
    ConnectionFailedError,
    MemoryHubError,
    NotFoundError,
    ToolError,
)

__version__ = "0.1.0"

__all__ = [
    "MemoryHubClient",
    "MemoryHubError",
    "AuthenticationError",
    "NotFoundError",
    "ToolError",
    "ConnectionFailedError",
    "__version__",
]
