"""Persistence and inheritance guards for ``upstream_trust_level`` (#559, #574).

Every assertion here reloads the row from the database rather than reading
the ``MemoryNodeRead`` the service hands back. That distinction is the whole
point of the module: the response object carries whatever the service set in
Python, so a test written against it passes even when the column never
reaches a database row. The gap these tests close was exactly that shape --
the field existed on the model and the schema, four of the five
``MemoryNode(...)`` construction sites omitted it, and nothing noticed.

The inheritance rule under test comes from docs/design/trust-provenance.md:
an extraction pipeline is a transform, not an endorsement, so the trust of
the output cannot exceed the trust of the input. A new version, a chunk, an
extracted fact, and a deep-copied branch are all transforms of something
upstream, and each one is a place where resetting the field to its column
default would silently launder untrusted content into trusted content.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select as sa_select

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeUpdate,
    MemoryScope,
    UpstreamTrustLevel,
)
from memoryhub_core.services.memory import create_fact_children
from memoryhub_core.services.memory import create_memory as _svc_create_memory
from memoryhub_core.services.memory import update_memory as _svc_update_memory

_TENANT_ID = "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_data(**overrides) -> MemoryNodeCreate:
    defaults = {
        "content": "scraped from an unauthenticated wiki",
        "scope": MemoryScope.USER,
        "weight": 0.5,
        "owner_id": "user-123",
    }
    defaults.update(overrides)
    return MemoryNodeCreate(**defaults)


def _oversized(prefix: str = "Paragraph") -> str:
    """Content past both the embedding limit and the S3 threshold.

    Paragraph boundaries matter: the semantic chunker splits on them first,
    so single-blob content of the same length yields one chunk and the
    chunk-inheritance tests would have nothing to assert against.
    """
    return "\n\n".join(f"{prefix} {i}: " + "x" * 2000 for i in range(60))


async def create_memory(data, session, embedding_service, *, s3_adapter=None):
    return await _svc_create_memory(
        data, session, embedding_service, tenant_id=_TENANT_ID, s3_adapter=s3_adapter
    )


async def update_memory(memory_id, data, session, embedding_service):
    return await _svc_update_memory(memory_id, data, session, embedding_service, s3_adapter=None)


async def _reload(session, node_id) -> MemoryNode:
    """Re-read one node's columns from the database.

    ``expire_all`` is the reason this helper exists. A bare ``select`` is
    served out of the identity map and returns the same Python object the
    service just built, so it reports the attribute rather than the stored
    value. Expiring first forces a fresh SELECT.
    """
    await session.flush()
    session.expire_all()
    return (await session.execute(sa_select(MemoryNode).where(MemoryNode.id == node_id))).scalar_one()


async def _reload_children(session, parent_id, branch_type: str) -> list[MemoryNode]:
    await session.flush()
    session.expire_all()
    stmt = sa_select(MemoryNode).where(
        MemoryNode.parent_id == parent_id,
        MemoryNode.branch_type == branch_type,
        MemoryNode.deleted_at.is_(None),
    )
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# The column is actually written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "requested",
    [UpstreamTrustLevel.UNTRUSTED, UpstreamTrustLevel.MIXED, UpstreamTrustLevel.TRUSTED],
)
async def test_create_persists_requested_trust_level(async_session, embedding_service, requested):
    created, _ = await create_memory(
        _create_data(upstream_trust_level=requested), async_session, embedding_service
    )

    row = await _reload(async_session, created.id)
    assert row.upstream_trust_level == requested.value


async def test_create_defaults_to_trusted(async_session, embedding_service):
    created, _ = await create_memory(_create_data(), async_session, embedding_service)

    row = await _reload(async_session, created.id)
    assert row.upstream_trust_level == "trusted"


# ---------------------------------------------------------------------------
# Inheritance: a transform cannot raise trust
# ---------------------------------------------------------------------------


async def test_new_version_inherits_untrusted(async_session, embedding_service):
    """A version bump is a transform of the previous version, not a re-source."""
    created, _ = await create_memory(
        _create_data(upstream_trust_level=UpstreamTrustLevel.UNTRUSTED),
        async_session,
        embedding_service,
    )

    updated = await update_memory(
        created.id,
        MemoryNodeUpdate(content="revised, still from the same unauthenticated wiki"),
        async_session,
        embedding_service,
    )

    assert updated.id != created.id, "update should mint a new version row"
    row = await _reload(async_session, updated.id)
    assert row.upstream_trust_level == "untrusted", (
        "version bump reset trust to the column default, which launders "
        "untrusted content into trusted content"
    )


async def test_metadata_only_update_inherits_untrusted(async_session, embedding_service):
    """Trust survives an update that does not touch content."""
    created, _ = await create_memory(
        _create_data(upstream_trust_level=UpstreamTrustLevel.MIXED),
        async_session,
        embedding_service,
    )

    updated = await update_memory(
        created.id, MemoryNodeUpdate(weight=0.9), async_session, embedding_service
    )

    row = await _reload(async_session, updated.id)
    assert row.upstream_trust_level == "mixed"


async def test_chunk_children_inherit_untrusted(async_session, embedding_service):
    """Chunks are slices of the parent and carry the parent's trust."""
    created, _ = await create_memory(
        _create_data(content=_oversized(), upstream_trust_level=UpstreamTrustLevel.UNTRUSTED),
        async_session,
        embedding_service,
        s3_adapter=None,
    )

    chunks = await _reload_children(async_session, created.id, "chunk")

    assert len(chunks) >= 2, f"expected multiple chunks, got {len(chunks)}"
    laundered = [c.id for c in chunks if c.upstream_trust_level != "untrusted"]
    assert not laundered, f"{len(laundered)}/{len(chunks)} chunks lost the parent's trust level: {laundered}"


async def test_rechunk_on_update_inherits_untrusted(async_session, embedding_service):
    """The chunks minted during an update inherit from the new version."""
    created, _ = await create_memory(
        _create_data(content=_oversized(), upstream_trust_level=UpstreamTrustLevel.UNTRUSTED),
        async_session,
        embedding_service,
        s3_adapter=None,
    )

    updated = await update_memory(
        created.id,
        MemoryNodeUpdate(content=_oversized(prefix="Revised paragraph")),
        async_session,
        embedding_service,
    )

    chunks = await _reload_children(async_session, updated.id, "chunk")

    assert len(chunks) >= 2, f"expected multiple chunks on the new version, got {len(chunks)}"
    laundered = [c.id for c in chunks if c.upstream_trust_level != "untrusted"]
    assert not laundered, f"{len(laundered)}/{len(chunks)} re-chunked children lost trust: {laundered}"


async def test_fact_children_inherit_untrusted(async_session, embedding_service):
    """Extraction is a transform. Facts pulled from untrusted prose stay untrusted."""
    parent, _ = await create_memory(
        _create_data(upstream_trust_level=UpstreamTrustLevel.UNTRUSTED),
        async_session,
        embedding_service,
    )

    count = await create_fact_children(
        facts=[{"content": "the wiki claims X"}, {"content": "the wiki claims Y"}],
        parent_id=parent.id,
        scope=parent.scope,
        scope_id=None,
        owner_id=parent.owner_id,
        tenant_id=_TENANT_ID,
        domains=None,
        extraction_run_id="test-trust-run",
        session=async_session,
        embedding_service=embedding_service,
        upstream_trust_level="untrusted",
    )
    assert count == 2

    facts = await _reload_children(async_session, parent.id, "fact")
    assert len(facts) == 2
    laundered = [f.id for f in facts if f.upstream_trust_level != "untrusted"]
    assert not laundered, f"{len(laundered)}/2 extracted facts lost the source's trust level: {laundered}"


async def test_fact_children_default_to_trusted(async_session, embedding_service):
    """Callers that never set a trust level keep the documented default."""
    parent, _ = await create_memory(_create_data(), async_session, embedding_service)

    await create_fact_children(
        facts=[{"content": "user prefers dark mode"}],
        parent_id=parent.id,
        scope=parent.scope,
        scope_id=None,
        owner_id=parent.owner_id,
        tenant_id=_TENANT_ID,
        domains=None,
        extraction_run_id="test-trust-run-default",
        session=async_session,
        embedding_service=embedding_service,
    )

    facts = await _reload_children(async_session, parent.id, "fact")
    assert [f.upstream_trust_level for f in facts] == ["trusted"]


async def test_copied_branches_inherit_untrusted(async_session, embedding_service):
    """Deep-copied non-chunk branches keep the trust of the child they copy.

    On a content update the service retires chunk branches and deep-copies
    everything else onto the new version. The copy is a fresh row, so it is
    one more place the column default could overwrite an inherited value.
    """
    parent, _ = await create_memory(
        _create_data(content=_oversized(), upstream_trust_level=UpstreamTrustLevel.UNTRUSTED),
        async_session,
        embedding_service,
        s3_adapter=None,
    )
    await create_memory(
        _create_data(
            content="Rationale: the wiki page had no author attribution",
            parent_id=parent.id,
            branch_type="rationale",
            upstream_trust_level=UpstreamTrustLevel.UNTRUSTED,
        ),
        async_session,
        embedding_service,
    )

    updated = await update_memory(
        parent.id,
        MemoryNodeUpdate(content=_oversized(prefix="Revised paragraph")),
        async_session,
        embedding_service,
    )

    copied = await _reload_children(async_session, updated.id, "rationale")

    assert len(copied) == 1, f"expected the rationale branch to be deep-copied, got {len(copied)}"
    assert copied[0].upstream_trust_level == "untrusted", (
        "deep-copied branch reset trust to the column default"
    )
