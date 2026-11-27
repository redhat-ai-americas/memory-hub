"""MCP maps common Core vetoes and never broadcasts a failed mutation."""

import importlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError

from memoryhub_core.queries.mutations import RelationshipBoundaryError
from memoryhub_core.services.exceptions import CurationBlockedError


def setup_tool(monkeypatch, name):
    module = importlib.import_module(f"src.tools.{name}")
    node = SimpleNamespace(id=uuid.uuid4(), scope="user", scope_id=None,
                           owner_id="alice", tenant_id="tenant-a", deleted_at=None)
    session, generator = AsyncMock(), object()
    monkeypatch.setattr(module, "get_claims_from_context", lambda: {
        "sub": "alice", "tenant_id": "tenant-a", "scopes": ["memory:write:user"],
    })
    monkeypatch.setattr(module, "get_db_session", AsyncMock(return_value=(session, generator)))
    monkeypatch.setattr(module, "_read_memory", AsyncMock(return_value=node))
    monkeypatch.setattr(module, "authorize_write", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "record_audit_event", AsyncMock())
    monkeypatch.setattr(module, "release_db_session", AsyncMock())
    monkeypatch.setattr(module, "get_s3_adapter", lambda: None)
    monkeypatch.setattr(module, "resolve_driver_id", lambda *_args: "alice")
    monkeypatch.setattr(module, "broadcast_after_write", AsyncMock())
    return module, node, generator


async def test_update_maps_core_veto_to_curation_error_without_broadcast(monkeypatch):
    module, node, generator = setup_tool(monkeypatch, "update_memory")
    monkeypatch.setattr(module, "get_embedding_service", lambda: object())
    monkeypatch.setattr(module, "svc_update_memory", AsyncMock(side_effect=CurationBlockedError("policy")))
    with pytest.raises(ToolError, match="^Curation rule blocked"):
        await module.update_memory(str(node.id), content="FORBIDDEN_CONTENT")
    module.broadcast_after_write.assert_not_awaited()
    module.release_db_session.assert_awaited_once_with(generator)


async def test_delete_skips_retired_authority_and_maps_common_integrity_failure(monkeypatch):
    module, node, generator = setup_tool(monkeypatch, "delete_memory")
    retired = SimpleNamespace(id=uuid.uuid4(), deleted_at=datetime.now(UTC), tenant_id="tenant-a")
    monkeypatch.setattr(module, "collect_delete_nodes", AsyncMock(return_value={node.id: node, retired.id: retired}))
    monkeypatch.setattr(module, "memory_object_access", AsyncMock(return_value=(True, True)))
    monkeypatch.setattr(module, "svc_delete_memory", AsyncMock(side_effect=RelationshipBoundaryError("invalid edge")))
    with pytest.raises(ToolError, match="Invalid memory relationship boundary"):
        await module.delete_memory(str(node.id))
    module.memory_object_access.assert_awaited_once()
    module.broadcast_after_write.assert_not_awaited()
    module.release_db_session.assert_awaited_once_with(generator)
