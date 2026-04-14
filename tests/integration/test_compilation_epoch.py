"""Integration test for compilation epoch end-to-end (#175).

Verifies that the compile -> store -> apply -> reorder pipeline works
correctly against real PostgreSQL and Valkey.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryScope
from memoryhub_core.services.compilation import (
    CompilationEpoch,
    apply_compilation,
    compile_memory_set,
)
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.memory import (
    create_memory as _svc_create_memory,
)
from memoryhub_core.services.memory import (
    search_memories as _svc_search_memories,
)
from memoryhub_core.services.valkey_client import ValkeyClient

pytestmark = pytest.mark.integration

_TEST_TENANT_ID = "default"
_TEST_OWNER = "compilation-test-user"


# -- Wrapper functions with default tenant_id --------------------------------


async def create_memory(
    data, session, embedding_service, skip_curation=False, *, tenant_id=_TEST_TENANT_ID
):
    """Test wrapper around the service create_memory with a default tenant."""
    return await _svc_create_memory(
        data, session, embedding_service, tenant_id=tenant_id, skip_curation=skip_curation,
    )


async def search_memories(
    query, session, embedding_service, *, tenant_id=_TEST_TENANT_ID, **kwargs
):
    """Test wrapper around search_memories with a default tenant."""
    return await _svc_search_memories(
        query, session, embedding_service, tenant_id=tenant_id, **kwargs,
    )


# -- Helpers -----------------------------------------------------------------


def _make(
    content: str,
    *,
    owner_id: str = _TEST_OWNER,
    scope: MemoryScope = MemoryScope.USER,
    weight: float = 0.9,
) -> MemoryNodeCreate:
    return MemoryNodeCreate(
        content=content,
        scope=scope,
        weight=weight,
        owner_id=owner_id,
    )


def _ids_from_results(results: list) -> list[str]:
    """Extract ordered list of string IDs from results."""
    return [str(node.id) for node, _ in results]


# ---------------------------------------------------------------------------
# 1. Compile and store epoch
# ---------------------------------------------------------------------------


async def test_compile_and_store_epoch(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    valkey_client: ValkeyClient,
) -> None:
    """Create memories, compile them, store in Valkey, read back, verify ordering.

    The canonical ordering is weight DESC -> created_at ASC -> id ASC,
    so memories with higher weights should appear first in the epoch.
    """
    # Create memories with different weights. The compilation sorts by
    # weight descending, so high_mem should come first.
    high_mem, _ = await create_memory(
        _make("high weight compilation test memory", weight=1.0),
        async_session, embedding_service, skip_curation=True,
    )
    mid_mem, _ = await create_memory(
        _make("medium weight compilation test memory", weight=0.7),
        async_session, embedding_service, skip_curation=True,
    )
    low_mem, _ = await create_memory(
        _make("low weight compilation test memory", weight=0.3),
        async_session, embedding_service, skip_curation=True,
    )

    # Search to get the (node, score) tuples that compile_memory_set expects.
    results = await search_memories(
        "compilation test memory",
        async_session, embedding_service,
        weight_threshold=0.0,  # include all weights
        max_results=10,
    )

    assert len(results) >= 3, (
        f"Expected at least 3 results, got {len(results)}: "
        f"{[n.content if hasattr(n, 'content') else n.stub for n, _ in results]}"
    )

    # Compile the memory set into an epoch.
    epoch = compile_memory_set(results, epoch=1)

    assert isinstance(epoch, CompilationEpoch)
    assert epoch.epoch == 1
    assert len(epoch.ordered_ids) == len(results)
    assert epoch.compilation_hash, "compilation_hash should be non-empty"

    # The canonical order is weight DESC, so high_mem should be first.
    assert epoch.ordered_ids[0] == str(high_mem.id), (
        f"Expected high-weight memory first, got {epoch.ordered_ids[0]}"
    )

    # Store the epoch in Valkey.
    await valkey_client.write_compilation(
        _TEST_TENANT_ID, _TEST_OWNER, epoch.to_dict(),
    )

    # Read it back from Valkey.
    raw = await valkey_client.read_compilation(_TEST_TENANT_ID, _TEST_OWNER)
    assert raw is not None, "Compilation not found in Valkey after write"

    restored = CompilationEpoch.from_dict(raw)
    assert restored.epoch == epoch.epoch
    assert restored.ordered_ids == epoch.ordered_ids
    assert restored.compilation_hash == epoch.compilation_hash
    assert restored.compiled_at == epoch.compiled_at


# ---------------------------------------------------------------------------
# 2. Apply compilation reorders search results
# ---------------------------------------------------------------------------


async def test_apply_compilation_reorders_search_results(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    valkey_client: ValkeyClient,
) -> None:
    """Search results should follow epoch order after apply_compilation, not similarity order.

    Creates memories with different weights, searches them (returns in
    similarity order), compiles an epoch (canonical weight-based order),
    stores it, then applies it to search results and verifies the output
    follows the epoch ordering.
    """
    # Create memories with varied weights but similar content so
    # similarity search may not match weight order.
    heavy, _ = await create_memory(
        _make("kubernetes pod scheduling affinity rules", weight=1.0),
        async_session, embedding_service, skip_curation=True,
    )
    medium, _ = await create_memory(
        _make("kubernetes service mesh istio configuration", weight=0.6),
        async_session, embedding_service, skip_curation=True,
    )
    light, _ = await create_memory(
        _make("kubernetes container runtime interface", weight=0.3),
        async_session, embedding_service, skip_curation=True,
    )

    # Search to get similarity-ordered results.
    search_results = await search_memories(
        "kubernetes pod scheduling",
        async_session, embedding_service,
        weight_threshold=0.0,
        max_results=10,
    )

    assert len(search_results) >= 3, (
        f"Expected at least 3 search results, got {len(search_results)}"
    )

    # Compile: canonical order is weight DESC.
    epoch = compile_memory_set(search_results, epoch=1)

    # Store and read back to exercise the full round-trip.
    await valkey_client.write_compilation(
        _TEST_TENANT_ID, _TEST_OWNER, epoch.to_dict(),
    )
    raw = await valkey_client.read_compilation(_TEST_TENANT_ID, _TEST_OWNER)
    restored_epoch = CompilationEpoch.from_dict(raw)

    # Apply compilation to the search results.
    compiled, appendix = apply_compilation(search_results, restored_epoch)

    assert len(appendix) == 0, (
        f"Expected empty appendix (all memories are in the epoch), "
        f"got {len(appendix)} items"
    )
    assert len(compiled) == len(search_results), (
        f"Compiled count {len(compiled)} != search count {len(search_results)}"
    )

    # The compiled order should match epoch order (weight DESC).
    compiled_ids = [str(node.id) for node, _ in compiled]
    assert compiled_ids == restored_epoch.ordered_ids, (
        f"Compiled IDs don't match epoch order.\n"
        f"  compiled: {compiled_ids}\n"
        f"  epoch:    {restored_epoch.ordered_ids}"
    )

    # Verify heavy-weight memory is first in the compiled output.
    assert str(compiled[0][0].id) == str(heavy.id), (
        f"Expected heavy-weight memory first after apply_compilation, "
        f"got {compiled[0][0].id}"
    )


# ---------------------------------------------------------------------------
# 3. New memory appears in appendix
# ---------------------------------------------------------------------------


async def test_new_memory_appears_in_appendix(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    valkey_client: ValkeyClient,
) -> None:
    """Memories created after compilation should appear in the appendix.

    Workflow: create A, B -> compile -> create C -> search all three ->
    apply compilation -> A, B in compiled section, C in appendix.
    """
    mem_a, _ = await create_memory(
        _make("docker container networking bridge mode", weight=0.9),
        async_session, embedding_service, skip_curation=True,
    )
    mem_b, _ = await create_memory(
        _make("docker image layer caching optimization", weight=0.8),
        async_session, embedding_service, skip_curation=True,
    )

    # Search and compile with only A and B.
    initial_results = await search_memories(
        "docker container image",
        async_session, embedding_service,
        weight_threshold=0.0,
        max_results=10,
    )
    initial_ids = {str(node.id) for node, _ in initial_results}
    assert str(mem_a.id) in initial_ids, "mem_a missing from initial search"
    assert str(mem_b.id) in initial_ids, "mem_b missing from initial search"

    epoch = compile_memory_set(initial_results, epoch=1)

    # Store the epoch.
    await valkey_client.write_compilation(
        _TEST_TENANT_ID, _TEST_OWNER, epoch.to_dict(),
    )

    # Create memory C AFTER compilation.
    mem_c, _ = await create_memory(
        _make("docker compose multi-service orchestration", weight=0.85),
        async_session, embedding_service, skip_curation=True,
    )

    # Search again — now includes A, B, and C.
    all_results = await search_memories(
        "docker container image compose",
        async_session, embedding_service,
        weight_threshold=0.0,
        max_results=10,
    )
    all_ids = {str(node.id) for node, _ in all_results}
    assert str(mem_c.id) in all_ids, "mem_c missing from second search"

    # Read back the stored epoch and apply.
    raw = await valkey_client.read_compilation(_TEST_TENANT_ID, _TEST_OWNER)
    restored_epoch = CompilationEpoch.from_dict(raw)

    compiled, appendix = apply_compilation(all_results, restored_epoch)

    # A and B should be in the compiled section.
    compiled_ids = {str(node.id) for node, _ in compiled}
    assert str(mem_a.id) in compiled_ids, "mem_a should be in compiled section"
    assert str(mem_b.id) in compiled_ids, "mem_b should be in compiled section"

    # C should be in the appendix (it was created after the epoch).
    appendix_ids = {str(node.id) for node, _ in appendix}
    assert str(mem_c.id) in appendix_ids, (
        f"mem_c should be in appendix but found in: "
        f"compiled={compiled_ids}, appendix={appendix_ids}"
    )

    # C should NOT be in the compiled section.
    assert str(mem_c.id) not in compiled_ids, (
        "mem_c should not be in compiled section — it was created after the epoch"
    )


# ---------------------------------------------------------------------------
# 4. Compilation survives Valkey round-trip
# ---------------------------------------------------------------------------


async def test_compilation_survives_valkey_roundtrip(
    valkey_client: ValkeyClient,
) -> None:
    """Store a compilation epoch in Valkey and read it back with full fidelity.

    This is a basic round-trip through real Valkey (not fakeredis) to verify
    that serialization, storage, and deserialization preserve all epoch fields.
    """
    original = CompilationEpoch(
        epoch=42,
        ordered_ids=["id-alpha", "id-bravo", "id-charlie", "id-delta"],
        compilation_hash="abc123def456",
        compiled_at="2026-04-13T12:00:00+00:00",
    )

    tenant = "roundtrip-tenant"
    owner = "roundtrip-owner"

    await valkey_client.write_compilation(tenant, owner, original.to_dict())

    raw = await valkey_client.read_compilation(tenant, owner)
    assert raw is not None, "Compilation not found after write"

    restored = CompilationEpoch.from_dict(raw)

    assert restored.epoch == original.epoch, (
        f"epoch mismatch: {restored.epoch} != {original.epoch}"
    )
    assert restored.ordered_ids == original.ordered_ids, (
        f"ordered_ids mismatch: {restored.ordered_ids} != {original.ordered_ids}"
    )
    assert restored.compilation_hash == original.compilation_hash, (
        f"hash mismatch: {restored.compilation_hash} != {original.compilation_hash}"
    )
    assert restored.compiled_at == original.compiled_at, (
        f"compiled_at mismatch: {restored.compiled_at} != {original.compiled_at}"
    )


async def test_compilation_delete_clears_state(
    valkey_client: ValkeyClient,
) -> None:
    """delete_compilation should remove the key so read_compilation returns None."""
    epoch = CompilationEpoch(
        epoch=1,
        ordered_ids=["id-one", "id-two"],
        compilation_hash="deadbeef",
        compiled_at="2026-04-13T13:00:00+00:00",
    )

    tenant = "delete-tenant"
    owner = "delete-owner"

    await valkey_client.write_compilation(tenant, owner, epoch.to_dict())

    # Verify it exists.
    raw = await valkey_client.read_compilation(tenant, owner)
    assert raw is not None, "Compilation should exist before delete"

    # Delete.
    await valkey_client.delete_compilation(tenant, owner)

    # Verify it's gone.
    raw = await valkey_client.read_compilation(tenant, owner)
    assert raw is None, "Compilation should be None after delete"


async def test_compilation_empty_ordered_ids_roundtrip(
    valkey_client: ValkeyClient,
) -> None:
    """An epoch with an empty ordered_ids list should survive the round-trip.

    The pipe-delimited serialization must handle the empty case correctly
    (empty string split on '|' could produce [''] if not handled).
    """
    original = CompilationEpoch(
        epoch=0,
        ordered_ids=[],
        compilation_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        compiled_at="2026-04-13T14:00:00+00:00",
    )

    tenant = "empty-epoch-tenant"
    owner = "empty-epoch-owner"

    await valkey_client.write_compilation(tenant, owner, original.to_dict())

    raw = await valkey_client.read_compilation(tenant, owner)
    assert raw is not None

    restored = CompilationEpoch.from_dict(raw)
    assert restored.ordered_ids == [], (
        f"Expected empty list, got {restored.ordered_ids!r}"
    )
    assert restored.epoch == 0
