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
    ConflictError,
    ConnectionFailedError,
    CurationVetoError,
    MemoryHubError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)

__version__ = "0.5.0"

__all__ = [
    "MemoryHubClient",
    "MemoryUpdatedCallback",
    "MemoryHubError",
    "AuthenticationError",
    "ConflictError",
    "ConnectionFailedError",
    "CurationVetoError",
    "NotFoundError",
    "PermissionDeniedError",
    "ToolError",
    "ValidationError",
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
