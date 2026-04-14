"""Project configuration schema and loader for MemoryHub.

Loads ``.memoryhub.yaml`` from the project root (or any parent directory)
and exposes a typed :class:`ProjectConfig`. The loader is used by
:class:`memoryhub.MemoryHubClient` to apply ``retrieval_defaults`` to
outbound ``search_memory`` calls automatically.

Schema reference: ``docs/agent-memory-ergonomics/design.md`` — see the
"Project Configuration" section. Pattern E fields (``live_subscription``
etc.) are accepted but not yet wired into the client; see the Phase 2
note on :class:`MemoryLoadingConfig`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from memoryhub.exceptions import MemoryHubError

CONFIG_FILENAME = ".memoryhub.yaml"


class MemoryLoadingConfig(BaseModel):
    """How memories should be loaded into agent context.

    The ``pattern`` field drives the rule file the ``memoryhub config init``
    CLI generates. The ``mode``/``focus_source``/``session_focus_weight``
    fields are consumed by session-focus retrieval (#58, Phase 2).

    Pattern E (real-time push) fields — ``live_subscription``,
    ``push_payload``, ``push_filter_weight``, ``push_transport`` — are
    accepted by the schema so that #62 can land without re-shipping
    ``.memoryhub.yaml``. The SDK does not yet consume them; they are
    forward-declared for the Phase 2 push implementation.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["focused", "broad"] = "focused"
    pattern: Literal["eager", "lazy", "lazy_with_rebias", "jit"] = "lazy_with_rebias"
    focus_source: Literal["auto", "declared", "directory", "first_turn"] = "auto"
    session_focus_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    on_topic_shift: Literal["rebias", "warn", "ignore"] = "rebias"
    cross_domain_contradiction_detection: bool = False

    # Campaign enrollment — projects can join campaigns for cross-project
    # knowledge sharing. Campaigns are identified by name (unique per tenant).
    campaigns: list[str] = Field(default_factory=list)

    # Pattern E (Phase 2 — schema accepted, not yet wired into the SDK).
    live_subscription: bool = False
    push_payload: Literal["uri_only", "full_content"] = "uri_only"
    push_filter_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    push_transport: Literal["queue", "pubsub"] = "queue"

    # Cache optimization (#175) — controls how memories are assembled into the
    # injection block and how the server maintains compilation stability.
    injection_position: Literal["user_message_prefix", "system_prompt_suffix"] = "user_message_prefix"
    sort_order: Literal["weight_desc", "relevance"] = "weight_desc"
    append_only_growth: bool = True
    include_metadata_in_injection: bool = False
    auto_recompile_threshold: float = Field(default=0.3, ge=0.0, le=1.0)


class RetrievalDefaults(BaseModel):
    """Default arguments applied to outbound ``search_memory`` calls.

    Resolved at call time: explicit caller arguments to
    :meth:`MemoryHubClient.search` always win over these defaults.
    """

    model_config = ConfigDict(extra="forbid")

    max_results: int = Field(default=10, ge=1, le=50)
    max_response_tokens: int = Field(default=4000, ge=100, le=20000)
    default_mode: Literal["full", "index", "full_only"] = "full"


class ProjectConfig(BaseModel):
    """Top-level project config loaded from ``.memoryhub.yaml``.

    Missing top-level sections fall back to per-section defaults.
    Unknown top-level keys are rejected so typos are surfaced early.
    """

    model_config = ConfigDict(extra="forbid")

    memory_loading: MemoryLoadingConfig = Field(default_factory=MemoryLoadingConfig)
    retrieval_defaults: RetrievalDefaults = Field(default_factory=RetrievalDefaults)


class ConfigError(MemoryHubError):
    """Raised when ``.memoryhub.yaml`` cannot be parsed or validated.

    Attributes:
        path: Absolute path to the offending file.
        detail: Human-readable description of the failure.
    """

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid {path}: {detail}")


def find_project_config(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (or cwd) looking for ``.memoryhub.yaml``.

    Args:
        start: Directory to begin the search. Defaults to the current
            working directory.

    Returns:
        Absolute path to the first ``.memoryhub.yaml`` found, or
        ``None`` if none is found before reaching the filesystem root.
    """
    cur = (start or Path.cwd()).resolve()
    while True:
        candidate = cur / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        if cur.parent == cur:
            return None
        cur = cur.parent


def load_project_config(path: Path | str | None = None) -> ProjectConfig:
    """Load project config from ``path`` or by auto-discovery.

    Args:
        path: Explicit path to a ``.memoryhub.yaml`` file. When ``None``,
            auto-discovery walks up from the current working directory.

    Returns:
        A :class:`ProjectConfig`. When no file is found (auto-discovery
        path only), returns :class:`ProjectConfig` with all defaults.

    Raises:
        ConfigError: If ``path`` is explicitly provided but the file is
            missing, or if any discovered file fails to parse or
            validate against the schema.
    """
    explicit = path is not None
    if explicit:
        resolved = Path(path)
        if not resolved.is_file():
            raise ConfigError(resolved, "File does not exist")
    else:
        found = find_project_config()
        if found is None:
            return ProjectConfig()
        resolved = found

    try:
        text = resolved.read_text()
    except OSError as exc:
        raise ConfigError(resolved, f"Cannot read file: {exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(resolved, f"YAML parse error: {exc}") from exc

    if raw is None:
        # Empty file is treated as "use defaults" rather than an error —
        # users commonly scaffold an empty file and fill in later.
        return ProjectConfig()
    if not isinstance(raw, dict):
        raise ConfigError(
            resolved,
            f"Top-level must be a mapping, got {type(raw).__name__}",
        )

    try:
        return ProjectConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(resolved, str(exc)) from exc


__all__ = [
    "CONFIG_FILENAME",
    "MemoryLoadingConfig",
    "RetrievalDefaults",
    "ProjectConfig",
    "ConfigError",
    "find_project_config",
    "load_project_config",
]
