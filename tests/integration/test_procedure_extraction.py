"""Procedural graph extraction against real PostgreSQL + pgvector (#554).

Exercises the transactional writer, matching over pgvector-stored
embeddings, refinement, rollback and the #553 retrieval path on a real
database. The LLMs are scripted; nothing leaves the process.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from memoryhub_core.models.conversation import ConversationExtraction
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services import procedure_extraction as pe
from memoryhub_core.services.graph import resolve_procedure_entry
from memoryhub_core.services.procedural_guidance import localized_guidance
from memoryhub_core.services.procedure_evolution import load_graph
from memoryhub_core.services.reconciliation import rollback_extraction_run
from tests.test_services.test_procedure_extraction import (
    OWNER,
    SUCCESS,
    TENANT,
    VARIANT,
    FakeLLM,
    make_thread,
    roots,
    run,
    success_proposal,
    variant_proposal,
)


@pytest.fixture(autouse=True)
def _fresh_curation_seed(monkeypatch):
    # Integration tables are truncated between tests; re-seed curation rules.
    monkeypatch.setattr("memoryhub_core.services.curation.pipeline._seeded_tenants", set())


class _Guidance:
    def __init__(self):
        self.seen = None

    async def generate(self, subgraph):
        self.seen = subgraph
        return "Build the image first, then run the smoke tests."


@pytest.mark.asyncio
async def test_dreaming_builds_a_graph_that_553_retrieval_returns(async_session, embedding_service, monkeypatch):
    from memoryhub_core.services import dreaming

    monkeypatch.setenv("MEMORYHUB_CONV_EXTRACTION_MODEL", "m")
    monkeypatch.setenv("MEMORYHUB_CONV_EXTRACTION_MODEL_URL", "http://llm.test")
    monkeypatch.setenv("MEMORYHUB_PROCEDURAL_EXTRACTION_MODE", "apply")
    thread = await make_thread(async_session, SUCCESS)
    with patch.object(dreaming, "_call_extraction_llm", new=AsyncMock(return_value=[])), \
            patch.object(pe, "ProceduralLLM", return_value=FakeLLM(success_proposal())):
        result = await dreaming.extract_from_thread(
            async_session, thread_id=thread.id, tenant_id=TENANT, owner_id=OWNER,
            embedding_service=embedding_service,
        )
    assert result["procedures"]["created"] == 1, result
    root_id = uuid.UUID(result["procedures"]["procedure_ids"][0])

    entry = await resolve_procedure_entry(root_id, async_session, tenant_id=TENANT)
    from memoryhub_core.services.exceptions import ProcedureNotEstablishedError

    with pytest.raises(ProcedureNotEstablishedError):  # one session: still a candidate
        await localized_guidance(entry, async_session, tenant_id=TENANT, generator=_Guidance())
    monkeypatch.setenv("MEMORYHUB_PROCEDURAL_SERVE_CANDIDATES", "true")
    generator = _Guidance()
    guidance = await localized_guidance(entry, async_session, tenant_id=TENANT, generator=generator)
    assert guidance.guidance_text.startswith("Build")
    assert generator.seen.current.id == entry and len(generator.seen.neighbors) == 2
    prov = (await async_session.execute(select(ConversationExtraction))).scalars().all()
    assert [p.extraction_prompt_hash for p in prov] == [pe.load_prompts()[2]]
    root = await async_session.get(MemoryNode, root_id)
    assert root.embedding is not None and root.metadata_["procedure"]["entry_step_id"] == str(entry)


@pytest.mark.asyncio
async def test_matching_and_refinement_on_postgres(async_session, embedding_service):
    seed = await make_thread(async_session, SUCCESS)
    first = await run(async_session, embedding_service, seed, FakeLLM(success_proposal()))
    root_id = uuid.UUID(first["procedure_ids"][0])
    for _ in range(2):
        t = await make_thread(async_session, VARIANT)
        report = await run(async_session, embedding_service, t, FakeLLM(variant_proposal()))
        assert report["matched"] == 1 and report["created"] == 0, report
    assert len(await roots(async_session)) == 1
    graph = await load_graph(async_session, root_id=root_id, tenant_id=TENANT)
    assert len(graph.steps) == 5
    assert await resolve_procedure_entry(root_id, async_session, tenant_id=TENANT)
    assert graph.root.metadata_["procedure"]["status"] == "established"

    # Rolling back the run that added the step removes it and restores the ledger.
    result = await rollback_extraction_run(report["run_id"], async_session)
    assert result["procedural"]["rolled_back"] >= 1
    graph = await load_graph(async_session, root_id=root_id, tenant_id=TENANT)
    assert len(graph.steps) == 4
    assert len(graph.root.metadata_["procedure"]["evidence"]["sessions"]) == 2


@pytest.mark.asyncio
async def test_failure_injection_is_atomic_on_postgres(async_session, embedding_service):
    thread = await make_thread(async_session, SUCCESS)
    real = pe.create_procedural_edge
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("injected after root, all steps and one edge")
        return await real(*args, **kwargs)

    with patch.object(pe, "create_procedural_edge", side_effect=flaky):
        report = await run(async_session, embedding_service, thread, FakeLLM(success_proposal()))
    assert "injected" in report["error"]
    for model in (MemoryNode, MemoryRelationship, ConversationExtraction):
        count = (await async_session.execute(select(func.count()).select_from(model))).scalar_one()
        assert count == 0, model.__name__


# ---------------------------------------------------------------------------
# Concurrency (review of #554, item 2): two sessions, two connections.
# ---------------------------------------------------------------------------


class _SlowLLM(FakeLLM):
    """Delays every answer so the two runs overlap in phase A."""

    async def complete(self, messages):
        import asyncio

        await asyncio.sleep(0.3)
        return await super().complete(messages)


@pytest.fixture
async def second_session(async_session):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from tests.integration.conftest import _build_db_url

    engine = create_async_engine(_build_db_url())
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_refinements_keep_both_sessions_evidence(async_session, second_session, embedding_service):
    import asyncio

    seed = await make_thread(async_session, SUCCESS)
    first = await run(async_session, embedding_service, seed, FakeLLM(success_proposal()))
    root_id = uuid.UUID(first["procedure_ids"][0])
    t1 = await make_thread(async_session, SUCCESS)
    t2 = await make_thread(async_session, SUCCESS)
    t2_other = await second_session.get(type(t2), t2.id)

    r1, r2 = await asyncio.gather(
        run(async_session, embedding_service, t1, _SlowLLM(success_proposal())),
        run(second_session, embedding_service, t2_other, _SlowLLM(success_proposal())),
    )
    assert r1["matched"] == 1 and r2["matched"] == 1, (r1, r2)
    expected = {str(seed.id), str(t1.id), str(t2.id)}
    async_session.expire_all()
    graph = await load_graph(async_session, root_id=root_id, tenant_id=TENANT, lock=False)
    await async_session.refresh(graph.root)
    sessions = graph.root.metadata_["procedure"]["evidence"]["sessions"]
    assert expected <= set(sessions), sorted(sessions)
    for step in graph.steps.values():
        await async_session.refresh(step)
        assert step.metadata_["procedure"]["evidence"]["success_count"] == 3


@pytest.mark.asyncio
async def test_concurrent_creation_makes_one_root(async_session, second_session, embedding_service):
    import asyncio

    t1 = await make_thread(async_session, SUCCESS)
    t2 = await make_thread(async_session, SUCCESS)
    t2_other = await second_session.get(type(t2), t2.id)
    r1, r2 = await asyncio.gather(
        run(async_session, embedding_service, t1, _SlowLLM(success_proposal())),
        run(second_session, embedding_service, t2_other, _SlowLLM(success_proposal())),
    )
    assert sorted([r1["created"], r2["created"]]) == [0, 1], (r1, r2)
    assert sorted([r1["matched"], r2["matched"]]) == [0, 1]
    async_session.expire_all()
    assert len(await roots(async_session)) == 1


@pytest.mark.asyncio
async def test_project_members_share_candidates_on_postgres(async_session, embedding_service):
    """pgvector candidate query: same project across owners, never across projects or tenants."""
    alice = await make_thread(async_session, SUCCESS, owner="alice", scope="project", scope_id="proj-pg")
    created = await run(async_session, embedding_service, alice, FakeLLM(success_proposal()))
    root_id = created["procedure_ids"][0]

    bob = await make_thread(async_session, VARIANT, owner="bob", scope="project", scope_id="proj-pg")
    report = await run(async_session, embedding_service, bob, FakeLLM(variant_proposal()))
    assert report["matched"] == 1 and report["foreign"] is True
    assert report["procedure_ids"] == [root_id]

    other_tenant = await make_thread(async_session, SUCCESS, owner="bob", scope="project",
                                     scope_id="proj-pg", tenant="tenant-b")
    report = await run(async_session, embedding_service, other_tenant, FakeLLM(success_proposal()))
    assert report["created"] == 1  # alice's procedure is invisible to another tenant
    assert len(await roots(async_session)) == 1
    assert len(await roots(async_session, tenant="tenant-b")) == 1


@pytest.mark.asyncio
async def test_validation_gate_on_postgres(async_session, embedding_service):
    from tests.test_services.test_procedure_extraction import FakeValidator

    validator = FakeValidator(async_session, answer="reject")
    seed = await make_thread(async_session, SUCCESS)
    first = await run(async_session, embedding_service, seed, FakeLLM(success_proposal()))
    root_id = uuid.UUID(first["procedure_ids"][0])
    for _ in range(2):
        t = await make_thread(async_session, VARIANT)
        await run(async_session, embedding_service, t, FakeLLM(variant_proposal()), validator=validator)
    graph = await load_graph(async_session, root_id=root_id, tenant_id=TENANT)
    assert len(graph.steps) == 4
    assert validator.in_transaction == [False]
    assert any(p["reason"] == "validation_rejected"
               for p in graph.root.metadata_["procedure"]["pending_edits"])
