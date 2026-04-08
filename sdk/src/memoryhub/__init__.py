"""MemoryHub — Centralized, governed memory for AI agents."""

from memoryhub.client import MemoryHubClient, MemoryUpdatedCallback
from memoryhub.config import (
    CONFIG_FILENAME,
    ConfigError,
    MemoryLoadingConfig,
    ProjectConfig,
    RetrievalDefaults,
    find_project_config,
    load_project_config,
)
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
    "MemoryUpdatedCallback",
    "MemoryHubError",
    "AuthenticationError",
    "NotFoundError",
    "ToolError",
    "ConnectionFailedError",
    # Project configuration
    "CONFIG_FILENAME",
    "ConfigError",
    "MemoryLoadingConfig",
    "ProjectConfig",
    "RetrievalDefaults",
    "find_project_config",
    "load_project_config",
    "__version__",
]
