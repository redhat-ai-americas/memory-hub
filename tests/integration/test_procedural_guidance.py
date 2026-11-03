"""PostgreSQL checks for localized procedural guidance (#553).

The search_memory response envelope is covered by the MCP unit tests.
This file checks the neighborhood those tests assume: a real Postgres
graph, a 2-hop bound, procedural edges only, recorded conditions and
pitfalls in the text the generator receives, and a cross-tenant node
that the walk cannot see.

Requires the integration compose stack. Not run in the local unit suite.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.schemas import (
    ContentType,
    MemoryNodeCreate,
    MemoryScope,
    RelationshipCreate,
    RelationshipType,
)
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import create_relationship
from memoryhub_core.services.memory import create_memory as _svc_create_memory
from memoryhub_core.services.procedural_guidance import (
    localized_guidance,
    render_subgraph_context,
)

pytestmark = pytest.mark.integration

_TENANT_A = "tenant_guidance_a"
_TENANT_B = "tenant_guidance_b"


async def _node(session, embedding_service, *, tenant_id, content, metadata=None):
    node, _ = await _svc_create_memory(
        MemoryNodeCreate(
            content=content,
            scope=MemoryScope.USER,
            owner_id="guidance-user",
            content_type=ContentType.PROCEDURAL,
            metadata=metadata,
        ),
        session,
        embedding_service,
        tenant_id=tenant_id,
        skip_curation=True,
    )
    return node


def _rel(source_id, target_id, rel_type, metadata=None) -> RelationshipCreate:
    return RelationshipCreate(
        source_id=source_id,
        target_id=target_id,
        relationship_type=rel_type,
        created_by="guidance-test",
        metadata=metadata,
    )


class _CapturingGenerator:
    def __init__(self) -> None:
        self.rendered = ""

    async def generate(self, subgraph):
        self.rendered = render_subgraph_context(subgraph)
        return "Apply the canary, then promote."

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_postgres_neighborhood_is_bounded_and_reaches_the_generator(
    async_session: AsyncSession,
    embedding_service,
):
    """From B, a 2-hop walk includes A, C, and D, and excludes E and a related_to aside."""
    steps = []
    for label in ("A", "B", "C", "D", "E"):
        pitfalls = ["image tag drifts"] if label == "C" else None
        metadata = {"procedure": {"action": f"step {label}"}}
        if pitfalls:
            metadata["procedure"]["pitfalls"] = pitfalls
        steps.append(
            await _node(
                async_session,
                embedding_service,
                tenant_id=_TENANT_A,
                content=f"step {label}",
                metadata=metadata,
            )
        )
    a, b, c, d, e = steps
    aside = await _node(
        async_session,
        embedding_service,
        tenant_id=_TENANT_A,
        content="unrelated cheese note",
    )
    await create_relationship(_rel(a.id, b.id, RelationshipType.precedes), async_session)
    await create_relationship(
        _rel(b.id, c.id, RelationshipType.precedes, metadata={"condition": "canary is healthy"}),
        async_session,
    )
    await create_relationship(_rel(c.id, d.id, RelationshipType.precedes), async_session)
    await create_relationship(_rel(d.id, e.id, RelationshipType.precedes), async_session)
    await create_relationship(_rel(b.id, aside.id, RelationshipType.related_to), async_session)

    other = await _node(
        async_session,
        embedding_service,
        tenant_id=_TENANT_B,
        content="other tenant step",
    )

    fake = _CapturingGenerator()
    result = await localized_guidance(
        b.id,
        async_session,
        tenant_id=_TENANT_A,
        max_hops=2,
        generator=fake,
    )
    neighbor_ids = {item["node"].id for item in result.subgraph.neighbors}
    assert neighbor_ids == {a.id, c.id, d.id}
    assert e.id not in neighbor_ids
    assert aside.id not in neighbor_ids
    assert other.id not in neighbor_ids
    assert result.guidance_text == "Apply the canary, then promote."
    assert result.subgraph.current.id == b.id
    assert "image tag drifts" in fake.rendered
    assert "canary is healthy" in fake.rendered
    assert "step E" not in fake.rendered
    assert "unrelated cheese note" not in fake.rendered
    assert "other tenant step" not in fake.rendered
    assert result.to_payload()["hop_count"] == 2

    with pytest.raises(MemoryNotFoundError):
        await localized_guidance(
            other.id,
            async_session,
            tenant_id=_TENANT_A,
            generator=fake,
        )


@pytest.mark.asyncio
async def test_postgres_cross_tenant_edge_does_not_enter_the_neighborhood(
    async_session: AsyncSession,
    embedding_service,
):
    """An edge stored under another tenant is invisible even if it names a local node."""
    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryRelationship

    local = await _node(
        async_session,
        embedding_service,
        tenant_id=_TENANT_A,
        content="local step",
    )
    foreign = await _node(
        async_session,
        embedding_service,
        tenant_id=_TENANT_B,
        content="foreign step",
    )
    now = datetime.now(UTC)
    async_session.add(
        MemoryRelationship(
            id=uuid.uuid4(),
            source_id=local.id,
            target_id=foreign.id,
            relationship_type="precedes",
            created_by="guidance-test",
            tenant_id=_TENANT_B,
            metadata_={},
            valid_from=now,
            created_at=now,
        )
    )
    await async_session.commit()

    fake = _CapturingGenerator()
    result = await localized_guidance(
        local.id,
        async_session,
        tenant_id=_TENANT_A,
        generator=fake,
    )
    assert result.subgraph.neighbors == []
    assert "foreign step" not in fake.rendered
