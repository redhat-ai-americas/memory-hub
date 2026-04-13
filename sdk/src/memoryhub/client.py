"""MemoryHub SDK client."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import mcp.types as mt
from fastmcp import Client
from fastmcp.client.messages import MessageHandler

from memoryhub.auth import MemoryHubAuth
from memoryhub.config import ProjectConfig, load_project_config
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
from memoryhub.models import (
    ContradictionResult,
    CurationRuleResult,
    DeleteResult,
    Memory,
    RelationshipInfo,
    RelationshipsResult,
    SearchResult,
    WriteResult,
)

logger = logging.getLogger(__name__)


# Type alias for memory-update callbacks. Receives the URI string of the
# updated memory; the callback is responsible for any follow-up read.
MemoryUpdatedCallback = Callable[[str], Awaitable[None]]


class _MemoryHubMessageHandler(MessageHandler):
    """FastMCP MessageHandler routing ``ResourceUpdatedNotification`` to SDK callbacks.

    The MCP spec's ``notifications/resources/updated`` carries only the
    resource URI; this handler filters for the ``memoryhub://memory/<id>``
    URI scheme and forwards matching notifications to every registered
    :data:`MemoryUpdatedCallback`. Notifications for other URI schemes
    (e.g., ``file://`` from another MCP server in the same process) are
    ignored.

    Custom ``notifications/memoryhub/memory_written`` (full-content) is
    intentionally not handled here: the underlying MCP Python SDK
    deserializes incoming notifications against the closed
    ``ServerNotification`` union, which has no slot for vendor-prefixed
    methods. Receiving full-content notifications will require either an
    SDK upgrade or a transport-level subscriber and is tracked as a
    follow-up to #62.
    """

    def __init__(self) -> None:
        self._callbacks: list[MemoryUpdatedCallback] = []

    def register(self, callback: MemoryUpdatedCallback) -> None:
        self._callbacks.append(callback)

    async def on_resource_updated(
        self, message: mt.ResourceUpdatedNotification
    ) -> None:
        uri = str(message.params.uri)
        if not uri.startswith("memoryhub://memory/"):
            return
        for callback in self._callbacks:
            try:
                await callback(uri)
            except Exception as exc:
                logger.warning(
                    "memory-update callback raised; continuing: %s", exc
                )


class MemoryHubClient:
    """Typed Python client for MemoryHub.

    Wraps MemoryHub's MCP tools as async Python methods with transparent
    OAuth 2.1 authentication. The developer never sees MCP protocol,
    JWT tokens, or transport details.

    Usage::

        client = MemoryHubClient(
            url="https://mcp-server.apps.example.com/mcp/",
            auth_url="https://auth-server.apps.example.com",
            client_id="my-client",
            client_secret="my-secret",
        )

        async with client:
            results = await client.search("deployment patterns")
    """

    def __init__(
        self,
        url: str,
        auth_url: str,
        client_id: str,
        client_secret: str,
        *,
        project_config: ProjectConfig | None = None,
    ) -> None:
        """Construct a MemoryHubClient.

        Args:
            url: Streamable-HTTP endpoint of the MemoryHub MCP server.
            auth_url: Base URL of the OAuth 2.1 auth service.
            client_id: OAuth client ID.
            client_secret: OAuth client secret.
            project_config: Optional project-level config. When omitted,
                all-defaults :class:`ProjectConfig` is used; the
                ``retrieval_defaults`` section is applied to outbound
                ``search_memory`` calls when callers do not pass an
                explicit value. Use :func:`memoryhub.load_project_config`
                or :meth:`from_env` to auto-discover ``.memoryhub.yaml``.
        """
        self._url = url
        self._auth = MemoryHubAuth(
            auth_url=auth_url,
            client_id=client_id,
            client_secret=client_secret,
        )
        self._mcp: Client | None = None
        self._project_config = project_config or ProjectConfig()
        # #62 push pipeline state. The handler is constructed lazily in
        # __aenter__ when live_subscription is enabled, so the SDK adds zero
        # overhead for projects that haven't opted into push. Callbacks
        # registered before connect are buffered here and replayed onto the
        # handler at __aenter__ time.
        self._message_handler: _MemoryHubMessageHandler | None = None
        self._pending_callbacks: list[MemoryUpdatedCallback] = []

    @classmethod
    def from_env(
        cls,
        *,
        config_path: str | None = None,
        auto_discover_config: bool = True,
    ) -> MemoryHubClient:
        """Create a client from environment variables.

        Args:
            config_path: Explicit path to a ``.memoryhub.yaml`` file. When
                set, ``auto_discover_config`` is ignored and the file
                must exist.
            auto_discover_config: When True (default), walk up from the
                current working directory looking for ``.memoryhub.yaml``
                and apply its ``retrieval_defaults`` to outbound search
                calls. Set False to skip discovery entirely.

        Reads: MEMORYHUB_URL, MEMORYHUB_AUTH_URL, MEMORYHUB_CLIENT_ID,
        MEMORYHUB_CLIENT_SECRET.
        """
        missing = []
        url = os.environ.get("MEMORYHUB_URL", "")
        auth_url = os.environ.get("MEMORYHUB_AUTH_URL", "")
        client_id = os.environ.get("MEMORYHUB_CLIENT_ID", "")
        client_secret = os.environ.get("MEMORYHUB_CLIENT_SECRET", "")

        if not url:
            missing.append("MEMORYHUB_URL")
        if not auth_url:
            missing.append("MEMORYHUB_AUTH_URL")
        if not client_id:
            missing.append("MEMORYHUB_CLIENT_ID")
        if not client_secret:
            missing.append("MEMORYHUB_CLIENT_SECRET")

        if missing:
            raise MemoryHubError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        project_config: ProjectConfig | None = None
        if config_path is not None:
            project_config = load_project_config(config_path)
        elif auto_discover_config:
            project_config = load_project_config()

        return cls(
            url=url,
            auth_url=auth_url,
            client_id=client_id,
            client_secret=client_secret,
            project_config=project_config,
        )

    async def __aenter__(self) -> MemoryHubClient:
        # Construct the FastMCP client with an optional notification message
        # handler when the project config opts into Pattern E live subscription.
        # The server-side push pipeline (#62) only delivers notifications to
        # sessions whose subscriber loop is running, which is started by
        # ``register_session``; the client-side handler here is what actually
        # routes the inbound notification to user-registered callbacks.
        message_handler: MessageHandler | None = None
        if self._project_config.memory_loading.live_subscription:
            self._message_handler = _MemoryHubMessageHandler()
            for cb in self._pending_callbacks:
                self._message_handler.register(cb)
            message_handler = self._message_handler

        self._mcp = Client(
            self._url, auth=self._auth, message_handler=message_handler
        )
        await self._mcp.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._mcp is not None:
            await self._mcp.__aexit__(exc_type, exc_val, exc_tb)
            self._mcp = None
        self._message_handler = None

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool and return the parsed response dict.

        Raises ToolError if the tool returns an error, or NotFoundError
        for memory-not-found errors.
        """
        if self._mcp is None:
            raise ConnectionFailedError(
                "Client is not connected. Use 'async with client:' context manager."
            )

        # Strip None values — MCP tools don't expect explicit nulls
        args = {k: v for k, v in arguments.items() if v is not None}

        result = await self._mcp.call_tool(tool_name, args, raise_on_error=False)

        if result.is_error:
            msg = ""
            if result.content:
                item = result.content[0]
                msg = item.text if hasattr(item, "text") else str(item)
            msg_lower = msg.lower()
            # Classify by message prefix — order matters (most specific first)
            if "invalid api key" in msg_lower or "no authenticated session" in msg_lower:
                raise AuthenticationError(msg)
            if msg_lower.startswith("curation rule blocked"):
                raise CurationVetoError(tool_name, msg)
            if "not found" in msg_lower:
                memory_id = args.get("memory_id", "unknown")
                raise NotFoundError(memory_id, msg)
            if "not authorized" in msg_lower or msg_lower.startswith("access denied:"):
                raise PermissionDeniedError(tool_name, msg)
            if "already exists" in msg_lower or "already deleted" in msg_lower:
                raise ConflictError(tool_name, msg)
            if (msg_lower.startswith("invalid ") or " must be " in msg_lower
                    or "cannot be empty" in msg_lower):
                raise ValidationError(tool_name, msg)
            raise ToolError(tool_name, msg or "Unknown error (empty response)")

        # Prefer structured_content (parsed JSON dict)
        if result.structured_content is not None:
            return result.structured_content

        # Fallback: parse text content as the full response
        if result.data is not None:
            if isinstance(result.data, dict):
                return result.data

        # Last resort: return content as-is wrapped in a dict
        if result.content:
            item = result.content[0]
            text = item.text if hasattr(item, "text") else str(item)
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"content": text}

        return {}

    # ── Core operations ─────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        scope: str | None = None,
        owner_id: str | None = None,
        max_results: int | None = None,
        weight_threshold: float = 0.0,
        current_only: bool = True,
        mode: Literal["full", "index", "full_only"] | None = None,
        max_response_tokens: int | None = None,
        include_branches: bool = False,
        focus: str | None = None,
        session_focus_weight: float | None = None,
        project_id: str | None = None,
        domains: list[str] | None = None,
        domain_boost_weight: float | None = None,
    ) -> SearchResult:
        """Search memories using semantic similarity.

        Args:
            query: Natural language search query.
            scope: Filter to a specific scope, or None for all accessible scopes.
            owner_id: Filter to a specific owner. None defaults to the
                authenticated user; pass an empty string to search across all
                accessible owners.
            max_results: Maximum results to return (1-50). When omitted, falls
                back to the project config's ``retrieval_defaults.max_results``
                (default 10).
            weight_threshold: Memories with weight below this return as stubs
                in mode='full'. Ignored when mode='full_only'.
            current_only: If True, return only current versions.
            mode: Result detail mode. ``"full"`` returns full content for
                weight >= weight_threshold and stubs below it. ``"index"``
                returns stubs for everything regardless of weight.
                ``"full_only"`` ignores weight_threshold. When omitted, falls
                back to the project config's
                ``retrieval_defaults.default_mode`` (default ``"full"``).
                Token budget may still degrade entries to stubs in any mode.
            max_response_tokens: Soft cap on the total response token cost.
                Results are packed in similarity order; once the cap is hit,
                remaining matches degrade to stubs. When omitted, falls back
                to the project config's
                ``retrieval_defaults.max_response_tokens`` (default 4000).
            include_branches: If True, branches whose parent is also in the
                result set are nested under the parent in a ``"branches"``
                field. Default False drops them; the agent can drill in via
                ``read_memory`` using ``has_rationale``/``has_children`` flags.
                Branches whose parent is not in the result set are always
                returned as top-level entries regardless of this flag.
            focus: Optional session focus string (#58, two-vector retrieval).
                When set, retrieval biases toward memories matching the focus
                in addition to the query. Pass per call (stateless); the SDK
                does not yet read ``focus_source`` from project config since
                inference belongs in the consumer code (Q3 resolution).
            session_focus_weight: Strength of the focus bias (0.0-1.0).
                Ignored when focus is None. Defaults to the project config's
                ``memory_loading.session_focus_weight`` when omitted (schema
                default 0.4).
            project_id: Project identifier for campaign enrollment verification.
            domains: Domain tags to boost in results. Non-matching results still appear.
            domain_boost_weight: Strength of domain boost (0.0-1.0). Server default 0.3.
        """
        defaults = self._project_config.retrieval_defaults
        loading = self._project_config.memory_loading
        if max_results is None:
            max_results = defaults.max_results
        if mode is None:
            mode = defaults.default_mode
        if max_response_tokens is None:
            max_response_tokens = defaults.max_response_tokens
        if session_focus_weight is None:
            session_focus_weight = loading.session_focus_weight

        payload: dict[str, Any] = {
            "query": query,
            "scope": scope,
            "owner_id": owner_id,
            "max_results": max_results,
            "weight_threshold": weight_threshold,
            "current_only": current_only,
            "mode": mode,
            "max_response_tokens": max_response_tokens,
            "include_branches": include_branches,
            "project_id": project_id,
            "domains": domains,
            "domain_boost_weight": domain_boost_weight,
        }
        # Only forward focus params when the caller actually supplied a
        # focus string. Sending session_focus_weight without focus would
        # be a no-op on the server but adds noise to the wire format.
        if focus is not None:
            payload["focus"] = focus
            payload["session_focus_weight"] = session_focus_weight

        data = await self._call("search_memory", payload)
        return SearchResult.model_validate(data)

    async def read(
        self,
        memory_id: str,
        *,
        include_versions: bool = False,
        history_offset: int = 0,
        history_max_versions: int = 10,
        project_id: str | None = None,
    ) -> Memory:
        """Read a memory by ID, optionally with paginated version history.

        Branch contents are no longer expanded inline; the returned Memory
        carries a branch_count summary. Inspect specific branches by issuing
        follow-up search_memory or read_memory calls.

        When include_versions is True, the returned Memory includes a
        ``version_history`` dict with ``versions``, ``total_versions``,
        ``has_more``, and ``offset`` keys. Paginate with history_offset
        and history_max_versions for long-lived memories.

        Args:
            memory_id: ID of the memory to read.
            include_versions: If True, include version history in the response.
            history_offset: Versions to skip from newest (default 0).
            history_max_versions: Max versions to return (1-100, default 10).
            project_id: Project identifier for campaign enrollment verification.
        """
        payload: dict[str, Any] = {
            "memory_id": memory_id,
            "include_versions": include_versions,
            "project_id": project_id,
        }
        if include_versions:
            payload["history_offset"] = history_offset
            payload["history_max_versions"] = history_max_versions
        data = await self._call("read_memory", payload)
        return Memory.model_validate(data)

    async def write(
        self,
        content: str,
        *,
        scope: str = "user",
        owner_id: str | None = None,
        weight: float = 0.7,
        parent_id: str | None = None,
        branch_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
        domains: list[str] | None = None,
    ) -> WriteResult:
        """Write a new memory.

        Args:
            content: The memory content to store.
            scope: Memory scope (default "user").
            owner_id: Owner override; defaults to the authenticated user.
            weight: Memory weight (0.0-1.0, default 0.7).
            parent_id: Parent memory ID for branching.
            branch_type: Branch type label (e.g., "rationale").
            metadata: Arbitrary metadata dict.
            project_id: Project identifier for campaign enrollment verification.
            domains: Domain tags for the memory, e.g. ['React', 'Spring Boot'].
        """
        data = await self._call("write_memory", {
            "content": content,
            "scope": scope,
            "owner_id": owner_id,
            "weight": weight,
            "parent_id": parent_id,
            "branch_type": branch_type,
            "metadata": metadata,
            "project_id": project_id,
            "domains": domains,
        })
        return WriteResult.model_validate(data)

    async def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        weight: float | None = None,
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
        domains: list[str] | None = None,
    ) -> Memory:
        """Update an existing memory (creates a new version).

        At least one of content, weight, or metadata must be provided.

        Args:
            memory_id: ID of the memory to update.
            content: Replacement content.
            weight: New weight (0.0-1.0).
            metadata: New metadata dict (replaces existing).
            project_id: Project identifier for campaign enrollment verification.
            domains: Domain tags for the memory, e.g. ['React', 'Spring Boot'].
        """
        if content is None and weight is None and metadata is None:
            raise ValueError(
                "update() requires at least one of: content, weight, metadata"
            )
        data = await self._call("update_memory", {
            "memory_id": memory_id,
            "content": content,
            "weight": weight,
            "metadata": metadata,
            "project_id": project_id,
            "domains": domains,
        })
        return Memory.model_validate(data)

    async def delete(self, memory_id: str, *, project_id: str | None = None) -> DeleteResult:
        """Soft-delete a memory and its entire version chain.

        Args:
            memory_id: ID of the memory to delete.
            project_id: Project identifier for campaign enrollment verification.
        """
        data = await self._call("delete_memory", {
            "memory_id": memory_id,
            "project_id": project_id,
        })
        return DeleteResult.model_validate(data)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def report_contradiction(
        self,
        memory_id: str,
        observed_behavior: str,
        *,
        confidence: float = 0.7,
        project_id: str | None = None,
    ) -> ContradictionResult:
        """Report that a memory contradicts observed behavior.

        Args:
            memory_id: ID of the memory that is contradicted.
            observed_behavior: Description of the behavior that contradicts the memory.
            confidence: Reporter's confidence in the contradiction (0.0-1.0, default 0.7).
            project_id: Project identifier for campaign enrollment verification.
        """
        data = await self._call("report_contradiction", {
            "memory_id": memory_id,
            "observed_behavior": observed_behavior,
            "confidence": confidence,
            "project_id": project_id,
        })
        return ContradictionResult.model_validate(data)

    # ── Similarity & relationships ──────────────────────────────────

    async def get_similar(
        self,
        memory_id: str,
        *,
        threshold: float = 0.80,
        max_results: int = 10,
        offset: int = 0,
        project_id: str | None = None,
    ) -> list[Memory]:
        """Find memories similar to the given one.

        Args:
            memory_id: ID of the reference memory.
            threshold: Minimum cosine similarity (0.0-1.0, default 0.80).
            max_results: Maximum number of results to return (default 10).
            offset: Pagination offset (default 0).
            project_id: Project identifier for campaign enrollment verification.
        """
        data = await self._call("get_similar_memories", {
            "memory_id": memory_id,
            "threshold": threshold,
            "max_results": max_results,
            "offset": offset,
            "project_id": project_id,
        })
        results = data.get("results", [])
        return [Memory.model_validate(r) for r in results]

    async def get_relationships(
        self,
        node_id: str,
        *,
        relationship_type: str | None = None,
        direction: str = "both",
        include_provenance: bool = False,
        project_id: str | None = None,
    ) -> RelationshipsResult:
        """Get relationships for a memory node.

        Args:
            node_id: ID of the memory node to query relationships for.
            relationship_type: Filter by relationship type (e.g., "related").
            direction: Edge direction to traverse: "both", "outgoing", or "incoming".
            include_provenance: If True, include provenance metadata on each edge.
            project_id: Project identifier for campaign enrollment verification.
        """
        data = await self._call("get_relationships", {
            "node_id": node_id,
            "relationship_type": relationship_type,
            "direction": direction,
            "include_provenance": include_provenance,
            "project_id": project_id,
        })
        return RelationshipsResult.model_validate(data)

    async def create_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        *,
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> RelationshipInfo:
        """Create a relationship between two memories.

        Args:
            source_id: ID of the source memory node.
            target_id: ID of the target memory node.
            relationship_type: Relationship label (e.g., "related", "supersedes").
            metadata: Arbitrary metadata for the relationship edge.
            project_id: Project identifier for campaign enrollment verification.
        """
        data = await self._call("create_relationship", {
            "source_id": source_id,
            "target_id": target_id,
            "relationship_type": relationship_type,
            "metadata": metadata,
            "project_id": project_id,
        })
        return RelationshipInfo.model_validate(data)

    # ── Curation ────────────────────────────────────────────────────

    async def set_curation_rule(
        self,
        name: str,
        *,
        tier: str = "embedding",
        action: str = "flag",
        config: dict[str, Any] | None = None,
        scope_filter: str | None = None,
        enabled: bool = True,
        priority: int = 10,
    ) -> CurationRuleResult:
        """Create or update a curation rule."""
        data = await self._call("set_curation_rule", {
            "name": name,
            "tier": tier,
            "action": action,
            "config": config,
            "scope_filter": scope_filter,
            "enabled": enabled,
            "priority": priority,
        })
        return CurationRuleResult.model_validate(data)

    # ── Session focus (#61) ─────────────────────────────────────────

    async def set_session_focus(
        self,
        focus: str,
        project: str,
    ) -> dict[str, Any]:
        """Declare the current session's focus topic for #61 history.

        Writes the focus string and its embedded vector to Valkey so both
        the per-project focus histogram (consumed via
        :meth:`get_focus_history`) and the #62 Pattern E broadcast filter
        can read it. The SDK normally infers the focus from the working
        directory or first user turn per ``.memoryhub.yaml``; agents can
        also declare it explicitly.

        Args:
            focus: A 5-10 word natural-language topic describing the session.
            project: The project identifier this session belongs to.
                Typically matches the ``project`` field of project-scope
                memories and the project name the agent is working in.

        Returns:
            A dict with ``session_id``, ``user_id``, ``project``, ``focus``,
            ``expires_at``, and ``message``.
        """
        return await self._call("set_session_focus", {
            "focus": focus,
            "project": project,
        })

    async def get_focus_history(
        self,
        project: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve the per-project session focus histogram for a date range.

        Advisory-only usage signal — the histogram answers "what has this
        project been working on recently?" but does not auto-tune memory
        weights or retrieval ranking.

        Args:
            project: The project identifier to query.
            start_date: Inclusive start in YYYY-MM-DD. Defaults server-side
                to 30 days before ``end_date``.
            end_date: Inclusive end in YYYY-MM-DD. Defaults server-side to
                today (UTC).

        Returns:
            A dict with ``project``, ``start_date``, ``end_date``,
            ``total_sessions``, and ``histogram`` (list of ``{focus, count}``
            sorted by count descending, ties alphabetical).
        """
        return await self._call("get_focus_history", {
            "project": project,
            "start_date": start_date,
            "end_date": end_date,
        })

    # ── Push notifications (#62, Pattern E) ─────────────────────────

    def on_memory_updated(self, callback: MemoryUpdatedCallback) -> None:
        """Register a callback fired when another agent writes a memory.

        Pattern E composes with the pull-based loading patterns described in
        ``docs/agent-memory-ergonomics``. When a different connected agent
        calls ``write_memory``, ``update_memory``, or ``delete_memory``,
        MemoryHub broadcasts a ``ResourceUpdatedNotification`` and the SDK
        invokes every registered callback with the memory's URI. The
        callback is responsible for any follow-up :meth:`read` to fetch
        content; the URI alone is the spec-compliant payload.

        Multiple callbacks can be registered. Each is invoked in
        registration order; an exception in one callback is logged and does
        not prevent the others from running. Registration is cumulative — there
        is no unregister API in v1; create a fresh client to reset.

        Pattern E only fires for sessions whose project config sets
        ``memory_loading.live_subscription: true``. With the default
        (``false``), this method is a no-op: the callback is recorded but
        no subscriber pipeline is wired up so it will never be invoked.
        Enable live subscription explicitly in ``.memoryhub.yaml`` or via
        a ``ProjectConfig`` constructor argument before connecting.

        The current SDK delivers only spec-compliant URI-only notifications.
        The custom full-content notification path
        (``push_payload: full_content``) ships server-side with #62 but is
        not yet receivable by the typed Python SDK because the underlying
        MCP client deserializes against a closed notification union. A
        follow-up will lift this restriction.

        Args:
            callback: Async callable taking a single ``str`` URI argument
                (e.g., ``"memoryhub://memory/abc-123"``).

        Example::

            async def on_update(uri: str) -> None:
                memory_id = uri.removeprefix("memoryhub://memory/")
                memory = await client.read(memory_id)
                print(f"Another agent wrote: {memory.content}")

            client.on_memory_updated(on_update)
        """
        if not self._project_config.memory_loading.live_subscription:
            logger.debug(
                "on_memory_updated callback registered but live_subscription "
                "is False in project config; callback will never fire. Set "
                "memory_loading.live_subscription=true in .memoryhub.yaml to "
                "enable Pattern E push delivery."
            )

        if self._message_handler is None:
            # Buffer the callback so it gets registered when __aenter__ runs.
            # If live_subscription is False the buffered callback is silently
            # dropped on __aenter__ — the user opted out.
            self._pending_callbacks.append(callback)
        else:
            self._message_handler.register(callback)

    # ── Sync wrappers ───────────────────────────────────────────────

    def _run_sync(self, coro):
        """Run an async coroutine synchronously."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            raise RuntimeError(
                "Cannot use sync methods from an async context. "
                "Use the async methods directly instead."
            )
        return asyncio.run(coro)

    def search_sync(self, query: str, **kwargs) -> SearchResult:
        """Synchronous wrapper for search()."""
        async def _do():
            async with self:
                return await self.search(query, **kwargs)
        return self._run_sync(_do())

    def read_sync(self, memory_id: str, **kwargs) -> Memory:
        """Synchronous wrapper for read()."""
        async def _do():
            async with self:
                return await self.read(memory_id, **kwargs)
        return self._run_sync(_do())

    def write_sync(self, content: str, **kwargs) -> WriteResult:
        """Synchronous wrapper for write()."""
        async def _do():
            async with self:
                return await self.write(content, **kwargs)
        return self._run_sync(_do())

    def update_sync(self, memory_id: str, **kwargs) -> Memory:
        """Synchronous wrapper for update()."""
        async def _do():
            async with self:
                return await self.update(memory_id, **kwargs)
        return self._run_sync(_do())

    def delete_sync(self, memory_id: str) -> DeleteResult:
        """Synchronous wrapper for delete()."""
        async def _do():
            async with self:
                return await self.delete(memory_id)
        return self._run_sync(_do())
