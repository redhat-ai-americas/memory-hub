"""MemoryHub SDK client."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from fastmcp import Client

from memoryhub.auth import MemoryHubAuth
from memoryhub.exceptions import (
    ConnectionFailedError,
    MemoryHubError,
    NotFoundError,
    ToolError,
)
from memoryhub.models import (
    ContradictionResult,
    CurationRuleResult,
    DeleteResult,
    HistoryResult,
    Memory,
    RelationshipInfo,
    RelationshipsResult,
    SearchResult,
    WriteResult,
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
    ) -> None:
        self._url = url
        self._auth = MemoryHubAuth(
            auth_url=auth_url,
            client_id=client_id,
            client_secret=client_secret,
        )
        self._mcp: Client | None = None

    @classmethod
    def from_env(cls) -> MemoryHubClient:
        """Create a client from environment variables.

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

        return cls(
            url=url,
            auth_url=auth_url,
            client_id=client_id,
            client_secret=client_secret,
        )

    async def __aenter__(self) -> MemoryHubClient:
        self._mcp = Client(self._url, auth=self._auth)
        await self._mcp.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._mcp is not None:
            await self._mcp.__aexit__(exc_type, exc_val, exc_tb)
            self._mcp = None

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
            if "not found" in msg.lower():
                memory_id = args.get("memory_id", "unknown")
                raise NotFoundError(memory_id, msg)
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
        max_results: int = 10,
        weight_threshold: float = 0.0,
        current_only: bool = True,
    ) -> SearchResult:
        """Search memories using semantic similarity."""
        data = await self._call("search_memory", {
            "query": query,
            "scope": scope,
            "owner_id": owner_id,
            "max_results": max_results,
            "weight_threshold": weight_threshold,
            "current_only": current_only,
        })
        return SearchResult.model_validate(data)

    async def read(
        self,
        memory_id: str,
        *,
        depth: int = 0,
        include_versions: bool = False,
    ) -> Memory:
        """Read a memory by ID, optionally with branches and versions."""
        data = await self._call("read_memory", {
            "memory_id": memory_id,
            "depth": depth,
            "include_versions": include_versions,
        })
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
    ) -> WriteResult:
        """Write a new memory."""
        data = await self._call("write_memory", {
            "content": content,
            "scope": scope,
            "owner_id": owner_id,
            "weight": weight,
            "parent_id": parent_id,
            "branch_type": branch_type,
            "metadata": metadata,
        })
        return WriteResult.model_validate(data)

    async def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        weight: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        """Update an existing memory (creates a new version).

        At least one of content, weight, or metadata must be provided.
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
        })
        return Memory.model_validate(data)

    async def delete(self, memory_id: str) -> DeleteResult:
        """Soft-delete a memory and its entire version chain."""
        data = await self._call("delete_memory", {
            "memory_id": memory_id,
        })
        return DeleteResult.model_validate(data)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def get_history(
        self,
        memory_id: str,
        *,
        max_versions: int = 20,
        offset: int = 0,
    ) -> HistoryResult:
        """Get the version history of a memory."""
        data = await self._call("get_memory_history", {
            "memory_id": memory_id,
            "max_versions": max_versions,
            "offset": offset,
        })
        return HistoryResult.model_validate(data)

    async def report_contradiction(
        self,
        memory_id: str,
        observed_behavior: str,
        *,
        confidence: float = 0.7,
    ) -> ContradictionResult:
        """Report that a memory contradicts observed behavior."""
        data = await self._call("report_contradiction", {
            "memory_id": memory_id,
            "observed_behavior": observed_behavior,
            "confidence": confidence,
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
    ) -> list[Memory]:
        """Find memories similar to the given one."""
        data = await self._call("get_similar_memories", {
            "memory_id": memory_id,
            "threshold": threshold,
            "max_results": max_results,
            "offset": offset,
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
    ) -> RelationshipsResult:
        """Get relationships for a memory node."""
        data = await self._call("get_relationships", {
            "node_id": node_id,
            "relationship_type": relationship_type,
            "direction": direction,
            "include_provenance": include_provenance,
        })
        return RelationshipsResult.model_validate(data)

    async def create_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> RelationshipInfo:
        """Create a relationship between two memories."""
        data = await self._call("create_relationship", {
            "source_id": source_id,
            "target_id": target_id,
            "relationship_type": relationship_type,
            "metadata": metadata,
        })
        return RelationshipInfo.model_validate(data)

    # ── Curation ────────────────────────────────────────────────────

    async def suggest_merge(
        self,
        memory_a_id: str,
        memory_b_id: str,
        reasoning: str,
    ) -> dict[str, Any]:
        """Suggest that two memories should be merged."""
        return await self._call("suggest_merge", {
            "memory_a_id": memory_a_id,
            "memory_b_id": memory_b_id,
            "reasoning": reasoning,
        })

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
