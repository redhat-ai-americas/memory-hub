"""Tests for the entity extraction pipeline."""

import json
import os
import uuid
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.extraction import (
    _ExtractionResult,
    _merge_entities,
    _parse_json_best_effort,
    _should_run_stage2,
    _should_run_stage3,
    _strip_code_fences,
    _tag_extractor,
    extract_entities_from_memory,
    run_gliner_ner,
    run_llm_ner,
    run_spacy_ner,
)

# ── spaCy mock helpers ──────────────────────────────────────────────────────

SpacyEntity = namedtuple("SpacyEntity", ["text", "label_", "start_char", "end_char"])


class FakeDoc:
    def __init__(self, ents):
        self.ents = ents


class FakeNlp:
    def __init__(self, ents=None):
        self._ents = ents or []

    def __call__(self, text):
        return FakeDoc(self._ents)


# ── run_spacy_ner tests ─────────────────────────────────────────────────────


def test_run_spacy_ner_extracts_entities():
    fake = FakeNlp([
        SpacyEntity("Alice", "PERSON", 0, 5),
        SpacyEntity("New York", "GPE", 13, 21),
    ])
    with patch("memoryhub_core.services.extraction._get_nlp", return_value=fake):
        result = run_spacy_ner("Alice went to New York.")

    assert len(result) == 2
    assert result[0] == {"name": "Alice", "type": "person", "label": "PERSON", "start": 0, "end": 5, "confidence": 1.0}
    assert result[1] == {
        "name": "New York", "type": "location", "label": "GPE", "start": 13, "end": 21, "confidence": 1.0,
    }


def test_run_spacy_ner_empty_text():
    with patch("memoryhub_core.services.extraction._get_nlp", return_value=FakeNlp()):
        assert run_spacy_ner("") == []
        assert run_spacy_ner("   ") == []


def test_run_spacy_ner_no_recognized_entities():
    fake = FakeNlp([SpacyEntity("42", "CARDINAL", 0, 2)])
    with patch("memoryhub_core.services.extraction._get_nlp", return_value=fake):
        result = run_spacy_ner("The answer is 42.")
    assert result == []


def test_run_spacy_ner_deduplicates_within_text():
    fake = FakeNlp([
        SpacyEntity("Alice", "PERSON", 0, 5),
        SpacyEntity("Alice", "PERSON", 20, 25),
    ])
    with patch("memoryhub_core.services.extraction._get_nlp", return_value=fake):
        result = run_spacy_ner("Alice met someone. Alice left.")
    assert len(result) == 1


def test_run_spacy_ner_maps_all_supported_labels():
    ents = [
        SpacyEntity("Bob", "PERSON", 0, 3),
        SpacyEntity("Acme", "ORG", 4, 8),
        SpacyEntity("Paris", "GPE", 9, 14),
        SpacyEntity("Central Park", "LOC", 15, 27),
        SpacyEntity("the Tower", "FAC", 28, 37),
        SpacyEntity("the summit", "EVENT", 38, 48),
    ]
    fake = FakeNlp(ents)
    with patch("memoryhub_core.services.extraction._get_nlp", return_value=fake):
        result = run_spacy_ner("Bob Acme Paris Central Park the Tower the summit")

    types = [e["type"] for e in result]
    assert types == ["person", "organization", "location", "location", "location", "event"]


def test_run_spacy_ner_discounts_acronym_confidence():
    """Acronym-pattern entities get discounted confidence (#267)."""
    fake = FakeNlp([
        SpacyEntity("Alice", "PERSON", 0, 5),
        SpacyEntity("ORM", "ORG", 10, 13),
        SpacyEntity("NER", "ORG", 15, 18),
    ])
    with patch("memoryhub_core.services.extraction._get_nlp", return_value=fake):
        result = run_spacy_ner("Alice uses ORM and NER tools.")

    assert len(result) == 3
    alice = next(e for e in result if e["name"] == "Alice")
    orm = next(e for e in result if e["name"] == "ORM")
    ner_ent = next(e for e in result if e["name"] == "NER")

    assert alice["confidence"] == 1.0, "Mixed case should keep full confidence"
    assert orm["confidence"] == 0.5, "Acronym should get discounted confidence"
    assert ner_ent["confidence"] == 0.5, "Acronym should get discounted confidence"


# ── extract_entities_from_memory tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_entities_creates_nodes_and_edges(async_session):
    """Full pipeline: spaCy -> entity nodes -> MENTIONS edges."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()
    tenant_id = "test-tenant"
    owner_id = "test-user"

    # Create a source memory node to reference
    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    source = MemoryNode(
        id=memory_id,
        content="Alice from Acme Corp visited New York for the AI Summit.",
        stub="Alice from Acme Corp...",
        scope="user",
        weight=0.9,
        owner_id=owner_id,
        tenant_id=tenant_id,
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    )
    async_session.add(source)
    await async_session.commit()

    fake = FakeNlp([
        SpacyEntity("Alice", "PERSON", 0, 5),
        SpacyEntity("Acme Corp", "ORG", 11, 20),
        SpacyEntity("New York", "GPE", 29, 37),
        SpacyEntity("AI Summit", "EVENT", 46, 55),
    ])

    with patch("memoryhub_core.services.extraction._get_nlp", return_value=fake):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content=source.content,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id=tenant_id,
            owner_id=owner_id,
        )

    assert result["count"] == 4
    assert len(result["entities"]) == 4
    entity_names = {e["name"] for e in result["entities"]}
    assert entity_names == {"Alice", "Acme Corp", "New York", "AI Summit"}

    # Verify entity nodes were created in the database
    from sqlalchemy import select

    stmt = select(MemoryNode).where(MemoryNode.scope == "entity")
    entities = (await async_session.execute(stmt)).scalars().all()
    assert len(entities) == 4

    # Check entity node properties
    alice = next(e for e in entities if e.content == "Alice")
    assert alice.branch_type == "entity:person"
    assert alice.tenant_id == tenant_id
    assert alice.owner_id == owner_id
    assert alice.metadata_["extracted_by"] == "spacy"

    # Verify MENTIONS relationships
    from memoryhub_core.models.memory import MemoryRelationship

    rel_stmt = select(MemoryRelationship).where(
        MemoryRelationship.source_id == memory_id,
        MemoryRelationship.relationship_type == "mentions",
    )
    rels = (await async_session.execute(rel_stmt)).scalars().all()
    assert len(rels) == 4


@pytest.mark.asyncio
async def test_extract_entities_deduplicates_across_memories(async_session):
    """Two memories mentioning 'Alice' should share one entity node."""
    embedding_service = MockEmbeddingService()
    tenant_id = "test-tenant"
    owner_id = "test-user"

    from datetime import UTC, datetime

    from sqlalchemy import select

    from memoryhub_core.models.memory import MemoryNode, MemoryRelationship

    now = datetime.now(UTC)
    mem_ids = [uuid.uuid4(), uuid.uuid4()]
    for mid in mem_ids:
        async_session.add(MemoryNode(
            id=mid,
            content="Alice did something",
            stub="Alice did something...",
            scope="user",
            weight=0.9,
            owner_id=owner_id,
            tenant_id=tenant_id,
            is_current=True,
            version=1,
            storage_type="inline",
            created_at=now,
            updated_at=now,
        ))
    await async_session.commit()

    fake = FakeNlp([SpacyEntity("Alice", "PERSON", 0, 5)])

    with patch("memoryhub_core.services.extraction._get_nlp", return_value=fake):
        for mid in mem_ids:
            await extract_entities_from_memory(
                memory_id=mid,
                content="Alice did something",
                session=async_session,
                embedding_service=embedding_service,
                tenant_id=tenant_id,
                owner_id=owner_id,
            )

    # Only one entity node for "Alice"
    entity_stmt = select(MemoryNode).where(MemoryNode.scope == "entity")
    entities = (await async_session.execute(entity_stmt)).scalars().all()
    assert len(entities) == 1

    # Two MENTIONS edges pointing to the same entity
    rel_stmt = select(MemoryRelationship).where(
        MemoryRelationship.relationship_type == "mentions",
    )
    rels = (await async_session.execute(rel_stmt)).scalars().all()
    assert len(rels) == 2
    assert rels[0].target_id == rels[1].target_id


@pytest.mark.asyncio
async def test_extract_entities_handles_no_entities(async_session):
    """Content with no recognized entities returns count=0."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="The weather is nice today.",
        stub="The weather...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake = FakeNlp([])

    with patch("memoryhub_core.services.extraction._get_nlp", return_value=fake):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="The weather is nice today.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 0
    assert result["entities"] == []


@pytest.mark.asyncio
async def test_extract_entities_survives_individual_failure(async_session):
    """If one entity fails, the others still get extracted."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Alice went to New York.",
        stub="Alice went...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    # First entity will succeed, second will have an invalid type triggering ValueError
    fake = FakeNlp([
        SpacyEntity("Alice", "PERSON", 0, 5),
        SpacyEntity("New York", "GPE", 14, 22),
    ])

    from memoryhub_core.services.entity import find_or_create_entity as orig_find

    call_count = 0

    async def flaky_find(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated failure")
        return await orig_find(*args, **kwargs)

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake),
        patch("memoryhub_core.services.extraction.find_or_create_entity", side_effect=flaky_find),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Alice went to New York.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    # One succeeded, one failed
    assert result["count"] == 1
    assert result["entities"][0]["name"] == "Alice"


# ── GLiNER Stage 2 tests ──────────────────────────────────────────────────


class FakeGLiNERModel:
    """Deterministic GLiNER model replacement for unit tests."""

    def __init__(self, entities=None):
        self._entities = entities or []

    def predict_entities(self, text, labels, threshold=0.5):
        return self._entities


class FakeLLMExtractor:
    """Deterministic LLM extractor replacement for unit tests."""

    def __init__(self, entities=None, relationships=None):
        self._entities = entities or []
        self._relationships = relationships or []

    async def extract(self, text):
        return self._entities, self._relationships


def test_run_gliner_ner_extracts_entities():
    fake_model = FakeGLiNERModel([
        {"text": "PostgreSQL", "label": "database", "score": 0.92, "start": 10, "end": 20},
        {"text": "FastAPI", "label": "framework", "score": 0.88, "start": 30, "end": 37},
    ])
    with patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_model):
        result = run_gliner_ner("Deployed PostgreSQL with FastAPI on OpenShift.")

    assert len(result) == 2
    assert result[0]["name"] == "PostgreSQL"
    assert result[0]["type"] == "object"
    assert result[0]["label"] == "database"
    assert result[0]["confidence"] == 0.92
    assert result[1]["name"] == "FastAPI"
    assert result[1]["type"] == "object"


def test_run_gliner_ner_empty_text():
    assert run_gliner_ner("") == []
    assert run_gliner_ner("   ") == []


def test_run_gliner_ner_whitespace_entity_filtered():
    fake_model = FakeGLiNERModel([
        {"text": "  ", "label": "technology", "score": 0.85, "start": 0, "end": 2},
        {"text": "Python", "label": "programming language", "score": 0.95, "start": 5, "end": 11},
    ])
    with patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_model):
        result = run_gliner_ner("  Python is great.")

    assert len(result) == 1
    assert result[0]["name"] == "Python"


def test_run_gliner_ner_deduplicates():
    fake_model = FakeGLiNERModel([
        {"text": "Python", "label": "programming language", "score": 0.95, "start": 0, "end": 6},
        {"text": "Python", "label": "programming language", "score": 0.90, "start": 20, "end": 26},
    ])
    with patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_model):
        result = run_gliner_ner("Python is great. Python is fast.")

    assert len(result) == 1
    assert result[0]["confidence"] == 0.95


def test_run_gliner_ner_maps_labels_to_pole():
    fake_model = FakeGLiNERModel([
        {"text": "Alice", "label": "person", "score": 0.99, "start": 0, "end": 5},
        {"text": "Kubernetes", "label": "technology", "score": 0.91, "start": 10, "end": 20},
        {"text": "TCP", "label": "protocol", "score": 0.85, "start": 25, "end": 28},
        {"text": "AI Summit", "label": "event", "score": 0.87, "start": 33, "end": 42},
    ])
    with patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_model):
        result = run_gliner_ner("Alice uses Kubernetes over TCP at AI Summit")

    types = {e["name"]: e["type"] for e in result}
    assert types["Alice"] == "person"
    assert types["Kubernetes"] == "object"
    assert types["TCP"] == "object"
    assert types["AI Summit"] == "event"


# ── Cascade logic tests ───────────────────────────────────────────────────


def test_should_run_stage2_with_no_entities():
    assert _should_run_stage2([]) is True


def test_should_run_stage2_with_low_coverage():
    entities = [
        {"name": "Alice", "type": "person", "confidence": 1.0},
    ]
    assert _should_run_stage2(entities) is True


def test_should_run_stage2_skipped_with_sufficient_coverage():
    entities = [
        {"name": "Alice", "type": "person", "confidence": 1.0},
        {"name": "Acme", "type": "organization", "confidence": 1.0},
    ]
    assert _should_run_stage2(entities) is False


def test_should_run_stage2_low_confidence_doesnt_count():
    entities = [
        {"name": "Alice", "type": "person", "confidence": 1.0},
        {"name": "maybe-entity", "type": "person", "confidence": 0.5},
    ]
    assert _should_run_stage2(entities) is True


def test_tag_extractor():
    entities = [{"name": "Alice"}, {"name": "Bob"}]
    result = _tag_extractor(entities, "spacy")
    assert all(e["extractor"] == "spacy" for e in result)


def test_merge_entities_drops_duplicates():
    stage1 = [
        {"name": "Alice", "type": "person", "label": "PERSON", "confidence": 1.0, "start": 0, "end": 5},
    ]
    stage2 = [
        {"name": "alice", "type": "person", "label": "person", "confidence": 0.95, "start": 0, "end": 5},
        {"name": "PostgreSQL", "type": "object", "label": "database", "confidence": 0.92, "start": 10, "end": 20},
    ]
    merged = _merge_entities(stage1, stage2)
    assert len(merged) == 2
    names = [e["name"] for e in merged]
    assert "Alice" in names
    assert "PostgreSQL" in names


# ── Full cascade integration tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_cascade_runs_stage2_when_spacy_coverage_low(async_session):
    """When spaCy finds < 2 high-confidence entities, GLiNER Stage 2 runs."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Deployed PostgreSQL 16 with pgvector on OpenShift.",
        stub="Deployed PostgreSQL...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    # Stage 1: spaCy finds nothing (no person/org/location/event)
    fake_nlp = FakeNlp([])
    # Stage 2: GLiNER finds technologies
    fake_gliner = FakeGLiNERModel([
        {"text": "PostgreSQL", "label": "database", "score": 0.92, "start": 9, "end": 19},
        {"text": "pgvector", "label": "technology", "score": 0.88, "start": 25, "end": 33},
        {"text": "OpenShift", "label": "technology", "score": 0.90, "start": 37, "end": 46},
    ])

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Deployed PostgreSQL 16 with pgvector on OpenShift.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 3
    extractors = {e["extractor"] for e in result["entities"]}
    assert "gliner" in extractors


@pytest.mark.asyncio
async def test_cascade_always_runs_gliner_alongside_spacy(async_session):
    """GLiNER Stage 2 always runs regardless of spaCy coverage (#267)."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Alice from Acme Corp visited New York.",
        stub="Alice from Acme...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake_nlp = FakeNlp([
        SpacyEntity("Alice", "PERSON", 0, 5),
        SpacyEntity("Acme Corp", "ORG", 11, 20),
        SpacyEntity("New York", "GPE", 29, 37),
    ])

    gliner_called = False

    def mock_get_gliner():
        nonlocal gliner_called
        gliner_called = True
        return FakeGLiNERModel([])

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", side_effect=mock_get_gliner),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Alice from Acme Corp visited New York.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 3
    assert gliner_called, "GLiNER should always run alongside spaCy (#267)"
    extractors = {e["extractor"] for e in result["entities"]}
    assert extractors == {"spacy"}


@pytest.mark.asyncio
async def test_cascade_gliner_runs_despite_spacy_false_positives(async_session):
    """GLiNER runs even when spaCy produces false-positive ORG entities (#267).

    Reproduces the documented issue where spaCy tags technical terms as
    ORG/GPE with confidence 1.0 (now discounted to 0.5 for acronyms).
    """
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Deployed PostgreSQL with ORM on OpenShift.",
        stub="Deployed PostgreSQL...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake_nlp = FakeNlp([
        SpacyEntity("PostgreSQL", "GPE", 9, 19),
        SpacyEntity("ORM", "ORG", 25, 28),
    ])
    fake_gliner = FakeGLiNERModel([
        {"text": "PostgreSQL", "label": "database", "score": 0.92, "start": 9, "end": 19},
        {"text": "OpenShift", "label": "technology", "score": 0.90, "start": 36, "end": 45},
    ])

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Deployed PostgreSQL with ORM on OpenShift.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    extractors = {e["extractor"] for e in result["entities"]}
    assert "gliner" in extractors, "GLiNER entities should appear in results"
    names = {e["name"] for e in result["entities"]}
    assert "OpenShift" in names, "GLiNER-only entity should be in results"


@pytest.mark.asyncio
async def test_cascade_stage2_failure_falls_back_to_stage1(async_session):
    """If GLiNER fails, Stage 1 results are still used."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Alice went somewhere.",
        stub="Alice went...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake_nlp = FakeNlp([SpacyEntity("Alice", "PERSON", 0, 5)])

    def broken_gliner():
        raise RuntimeError("model load failed")

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction.run_gliner_ner", side_effect=RuntimeError("model load failed")),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Alice went somewhere.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 1
    assert result["entities"][0]["name"] == "Alice"
    assert result["entities"][0]["extractor"] == "spacy"


@pytest.mark.asyncio
async def test_cascade_dedup_between_stages(async_session):
    """When both stages find the same entity, only one entity node is created."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Alice went to New York to deploy PostgreSQL.",
        stub="Alice went to New York...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    # Stage 1: finds Alice (1 entity, triggers Stage 2)
    fake_nlp = FakeNlp([SpacyEntity("Alice", "PERSON", 0, 5)])
    # Stage 2: also finds Alice (person) + PostgreSQL (database)
    fake_gliner = FakeGLiNERModel([
        {"text": "Alice", "label": "person", "score": 0.95, "start": 0, "end": 5},
        {"text": "PostgreSQL", "label": "database", "score": 0.92, "start": 34, "end": 44},
    ])

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Alice went to New York to deploy PostgreSQL.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    # Alice from Stage 1 + PostgreSQL from Stage 2 (Alice duplicate from Stage 2 dropped)
    assert result["count"] == 2
    names = {e["name"] for e in result["entities"]}
    assert names == {"Alice", "PostgreSQL"}

    # Verify extractors are correctly tagged
    extractor_map = {e["name"]: e["extractor"] for e in result["entities"]}
    assert extractor_map["Alice"] == "spacy"
    assert extractor_map["PostgreSQL"] == "gliner"


# ── Stage 3 trigger logic tests ──────────────────────────────────────────


def test_should_run_stage3_no_url_configured():
    """Stage 3 never fires when no LLM URL is configured."""
    with patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": ""}, clear=False):
        assert _should_run_stage3([]) is False


def test_should_run_stage3_with_no_entities():
    """Stage 3 fires when URL is configured and no entities exist."""
    with patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False):
        assert _should_run_stage3([]) is True


def test_should_run_stage3_with_low_coverage():
    """Stage 3 fires when only 1 high-confidence entity (below trigger_count=2)."""
    entities = [{"name": "Alice", "type": "person", "confidence": 0.8}]
    with patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False):
        assert _should_run_stage3(entities) is True


def test_should_run_stage3_skipped_with_sufficient_coverage():
    """Stage 3 is skipped when >= 2 high-confidence entities exist."""
    entities = [
        {"name": "Alice", "type": "person", "confidence": 0.9},
        {"name": "Acme", "type": "organization", "confidence": 0.8},
    ]
    with patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False):
        assert _should_run_stage3(entities) is False


def test_should_run_stage3_low_confidence_doesnt_count():
    """Entities below llm_stage3_trigger_confidence (0.7) don't count toward threshold."""
    entities = [
        {"name": "Alice", "type": "person", "confidence": 0.8},
        {"name": "maybe", "type": "object", "confidence": 0.5},
    ]
    with patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False):
        assert _should_run_stage3(entities) is True


# ── LLM Stage 3 NER tests ───────────────────────────────────────────────


def _make_llm_response(entities, relationships=None):
    """Create a mock httpx.Response with vLLM-format JSON content."""
    content = json.dumps({
        "entities": entities,
        "relationships": relationships or [],
    })
    # httpx.Response.raise_for_status() requires a request to be set
    request = httpx.Request("POST", "http://llm:8000/v1/chat/completions")
    return httpx.Response(200, json={
        "choices": [{"message": {"content": content}}],
    }, request=request)


@pytest.mark.asyncio
async def test_run_llm_ner_extracts_entities_and_relationships():
    """LLM stage returns both entities and relationships."""
    import memoryhub_core.services.extraction as ext

    old = ext._llm_extractor
    ext._llm_extractor = None

    response = _make_llm_response(
        entities=[
            {"name": "MemoryHub", "type": "object", "confidence": 0.95},
            {"name": "PostgreSQL", "type": "object", "confidence": 0.92},
            {"name": "Wes", "type": "person", "confidence": 0.99},
        ],
        relationships=[
            {"source_name": "MemoryHub", "target_name": "PostgreSQL", "relationship_type": "uses"},
            {"source_name": "Wes", "target_name": "MemoryHub", "relationship_type": "uses"},
        ],
    )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract entities."}),
        patch("builtins.open", MagicMock()),
    ):
        entities, rels = await run_llm_ner("Wes built MemoryHub on PostgreSQL")

    ext._llm_extractor = old

    assert len(entities) == 3
    names = {e["name"] for e in entities}
    assert names == {"MemoryHub", "PostgreSQL", "Wes"}

    assert len(rels) == 2
    rel_types = {(r["source_name"], r["target_name"]): r["relationship_type"] for r in rels}
    assert rel_types[("MemoryHub", "PostgreSQL")] == "uses"
    assert rel_types[("Wes", "MemoryHub")] == "uses"


@pytest.mark.asyncio
async def test_run_llm_ner_empty_text():
    """Empty text returns empty entities and relationships without calling LLM."""
    entities, rels = await run_llm_ner("")
    assert entities == []
    assert rels == []


@pytest.mark.asyncio
async def test_run_llm_ner_whitespace_text():
    """Whitespace-only text returns empty entities and relationships."""
    entities, rels = await run_llm_ner("   ")
    assert entities == []
    assert rels == []


@pytest.mark.asyncio
async def test_run_llm_ner_filters_invalid_types():
    """Entities with types outside POLE+O vocabulary are dropped."""
    import memoryhub_core.services.extraction as ext

    old = ext._llm_extractor
    ext._llm_extractor = None

    response = _make_llm_response(
        entities=[
            {"name": "Alice", "type": "person", "confidence": 0.9},
            {"name": "Flux", "type": "INVALID_TYPE", "confidence": 0.9},
        ],
    )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract entities."}),
        patch("builtins.open", MagicMock()),
    ):
        entities, rels = await run_llm_ner("Alice uses Flux capacitor")

    ext._llm_extractor = old

    assert len(entities) == 1
    assert entities[0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_run_llm_ner_filters_low_confidence():
    """Entities below 0.5 confidence floor are dropped."""
    import memoryhub_core.services.extraction as ext

    old = ext._llm_extractor
    ext._llm_extractor = None

    response = _make_llm_response(
        entities=[
            {"name": "Alice", "type": "person", "confidence": 0.9},
            {"name": "Maybe", "type": "object", "confidence": 0.3},
        ],
    )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract entities."}),
        patch("builtins.open", MagicMock()),
    ):
        entities, rels = await run_llm_ner("Alice uses Maybe thing")

    ext._llm_extractor = old

    assert len(entities) == 1
    assert entities[0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_run_llm_ner_deduplicates():
    """Duplicate entities (same name+type) are deduplicated, keeping first."""
    import memoryhub_core.services.extraction as ext

    old = ext._llm_extractor
    ext._llm_extractor = None

    response = _make_llm_response(
        entities=[
            {"name": "Alice", "type": "person", "confidence": 0.95},
            {"name": "alice", "type": "person", "confidence": 0.80},
        ],
    )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract entities."}),
        patch("builtins.open", MagicMock()),
    ):
        entities, rels = await run_llm_ner("Alice met alice again")

    ext._llm_extractor = old

    assert len(entities) == 1
    assert entities[0]["name"] == "Alice"
    assert entities[0]["confidence"] == 0.95


# ── Full cascade tests including Stage 3 ─────────────────────────────────


@pytest.mark.asyncio
async def test_cascade_runs_stage3_when_coverage_low(async_session):
    """When Stages 1+2 produce no entities, Stage 3 LLM fires."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="MemoryHub uses PostgreSQL for storage.",
        stub="MemoryHub uses...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake_nlp = FakeNlp([])
    fake_gliner = FakeGLiNERModel([])

    llm_entities = [
        {"name": "MemoryHub", "type": "object", "label": "object", "start": -1, "end": -1, "confidence": 0.95},
        {"name": "PostgreSQL", "type": "object", "label": "object", "start": -1, "end": -1, "confidence": 0.92},
    ]

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
        patch(
            "memoryhub_core.services.extraction.run_llm_ner",
            new_callable=AsyncMock, return_value=(llm_entities, []),
        ),
        patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="MemoryHub uses PostgreSQL for storage.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 2
    extractors = {e["extractor"] for e in result["entities"]}
    assert "llm" in extractors


@pytest.mark.asyncio
async def test_cascade_skips_stage3_when_coverage_sufficient(async_session):
    """When Stage 1 finds enough entities, Stage 3 is not called."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Alice from Acme Corp visited New York.",
        stub="Alice from Acme...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake_nlp = FakeNlp([
        SpacyEntity("Alice", "PERSON", 0, 5),
        SpacyEntity("Acme Corp", "ORG", 11, 20),
        SpacyEntity("New York", "GPE", 29, 37),
    ])

    llm_called = False
    original_run_llm_ner = run_llm_ner

    async def tracking_run_llm_ner(text):
        nonlocal llm_called
        llm_called = True
        return await original_run_llm_ner(text)

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction.run_llm_ner", side_effect=tracking_run_llm_ner),
        patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Alice from Acme Corp visited New York.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 3
    assert not llm_called, "LLM Stage 3 should not have been called when coverage is sufficient"
    extractors = {e["extractor"] for e in result["entities"]}
    assert extractors == {"spacy"}


@pytest.mark.asyncio
async def test_cascade_skips_stage3_when_no_url(async_session):
    """Stage 3 is skipped when MEMORYHUB_LLM_EXTRACTION_URL is empty."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Something without entities.",
        stub="Something...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake_nlp = FakeNlp([])
    fake_gliner = FakeGLiNERModel([])

    llm_called = False

    async def tracking_run_llm_ner(text):
        nonlocal llm_called
        llm_called = True
        return [], []

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
        patch("memoryhub_core.services.extraction.run_llm_ner", side_effect=tracking_run_llm_ner),
        patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": ""}, clear=False),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Something without entities.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 0
    assert not llm_called, "LLM Stage 3 should not be called when no URL is configured"


@pytest.mark.asyncio
async def test_cascade_stage3_failure_falls_back(async_session):
    """If LLM fails, Stage 1+2 results are still used."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="Alice went somewhere.",
        stub="Alice went...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    # Stage 1: finds Alice (1 entity, triggers all stages)
    fake_nlp = FakeNlp([SpacyEntity("Alice", "PERSON", 0, 5)])
    # Stage 2: finds nothing
    fake_gliner = FakeGLiNERModel([])

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
        patch(
            "memoryhub_core.services.extraction.run_llm_ner",
            new_callable=AsyncMock, side_effect=RuntimeError("LLM unreachable"),
        ),
        patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="Alice went somewhere.",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 1
    assert result["entities"][0]["name"] == "Alice"
    assert result["entities"][0]["extractor"] == "spacy"


# ── Inter-entity relationship tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_stage3_creates_inter_entity_relationships(async_session):
    """Stage 3 creates related_to edges between entities with LLM type in metadata."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from sqlalchemy import select

    from memoryhub_core.models.memory import MemoryNode, MemoryRelationship

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="MemoryHub uses PostgreSQL",
        stub="MemoryHub uses...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake_nlp = FakeNlp([])
    fake_gliner = FakeGLiNERModel([])

    llm_entities = [
        {"name": "MemoryHub", "type": "object", "label": "object", "start": -1, "end": -1, "confidence": 0.95},
        {"name": "PostgreSQL", "type": "object", "label": "object", "start": -1, "end": -1, "confidence": 0.92},
    ]
    llm_relationships = [
        {"source_name": "MemoryHub", "target_name": "PostgreSQL", "relationship_type": "uses"},
    ]

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
        patch(
            "memoryhub_core.services.extraction.run_llm_ner",
            new_callable=AsyncMock,
            return_value=(llm_entities, llm_relationships),
        ),
        patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="MemoryHub uses PostgreSQL",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 2

    # Verify inter-entity relationship was created
    rel_stmt = select(MemoryRelationship).where(
        MemoryRelationship.relationship_type == "related_to",
    )
    rels = (await async_session.execute(rel_stmt)).scalars().all()
    assert len(rels) == 1
    assert rels[0].metadata_["llm_relationship_type"] == "uses"
    assert rels[0].metadata_["extractor"] == "llm"
    assert rels[0].created_by == "system:entity_extraction"


@pytest.mark.asyncio
async def test_stage3_skips_relationship_when_entity_missing(async_session):
    """Relationships referencing non-existent entities are silently skipped."""
    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from sqlalchemy import select

    from memoryhub_core.models.memory import MemoryNode, MemoryRelationship

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content="MemoryHub uses something",
        stub="MemoryHub...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    fake_nlp = FakeNlp([])
    fake_gliner = FakeGLiNERModel([])

    # LLM returns 1 entity but relationship references a non-extracted entity
    llm_entities = [
        {"name": "MemoryHub", "type": "object", "label": "object", "start": -1, "end": -1, "confidence": 0.95},
    ]
    llm_relationships = [
        {"source_name": "MemoryHub", "target_name": "NonExistent", "relationship_type": "uses"},
    ]

    with (
        patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
        patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
        patch(
            "memoryhub_core.services.extraction.run_llm_ner",
            new_callable=AsyncMock,
            return_value=(llm_entities, llm_relationships),
        ),
        patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000"}, clear=False),
    ):
        result = await extract_entities_from_memory(
            memory_id=memory_id,
            content="MemoryHub uses something",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="test-user",
        )

    assert result["count"] == 1

    # No related_to relationships should be created
    rel_stmt = select(MemoryRelationship).where(
        MemoryRelationship.relationship_type == "related_to",
    )
    rels = (await async_session.execute(rel_stmt)).scalars().all()
    assert len(rels) == 0


# ── Best-effort JSON parsing tests ──────────────────────────────────────


def test_strip_code_fences_json_block():
    raw = '```json\n{"entities": []}\n```'
    assert _strip_code_fences(raw) == '{"entities": []}'


def test_strip_code_fences_plain_block():
    raw = '```\n{"entities": []}\n```'
    assert _strip_code_fences(raw) == '{"entities": []}'


def test_strip_code_fences_no_fences():
    raw = '{"entities": []}'
    assert _strip_code_fences(raw) == '{"entities": []}'


def test_parse_json_best_effort_direct():
    result = _parse_json_best_effort('{"entities": []}')
    assert result == {"entities": []}


def test_parse_json_best_effort_code_fenced():
    result = _parse_json_best_effort('```json\n{"score": 5}\n```')
    assert result == {"score": 5}


def test_parse_json_best_effort_embedded_in_prose():
    text = 'Here is the result: {"entities": [{"name": "Alice"}]} hope that helps'
    result = _parse_json_best_effort(text)
    assert result == {"entities": [{"name": "Alice"}]}


def test_parse_json_best_effort_garbage():
    assert _parse_json_best_effort("not json at all") is None


def test_parse_json_best_effort_empty():
    assert _parse_json_best_effort("") is None


# ── Pydantic validation model tests ─────────────────────────────────────


def test_extraction_result_valid():
    data = {
        "entities": [
            {"name": "Alice", "type": "person", "confidence": 0.9},
        ],
        "relationships": [
            {
                "source_name": "Alice",
                "target_name": "Acme",
                "relationship_type": "works_at",
            },
        ],
    }
    result = _ExtractionResult.model_validate(data)
    assert len(result.entities) == 1
    assert result.entities[0].name == "Alice"
    assert len(result.relationships) == 1


def test_extraction_result_empty_arrays():
    result = _ExtractionResult.model_validate({"entities": [], "relationships": []})
    assert result.entities == []
    assert result.relationships == []


def test_extraction_result_missing_arrays_defaults():
    result = _ExtractionResult.model_validate({})
    assert result.entities == []
    assert result.relationships == []


def test_extraction_result_normalizes_type():
    data = {"entities": [{"name": "X", "type": "PERSON", "confidence": 0.9}]}
    result = _ExtractionResult.model_validate(data)
    assert result.entities[0].type == "person"


def test_extraction_result_rejects_empty_name():
    data = {"entities": [{"name": "", "type": "person", "confidence": 0.9}]}
    with pytest.raises(ValueError):
        _ExtractionResult.model_validate(data)


def test_extraction_result_rejects_bad_confidence():
    data = {"entities": [{"name": "X", "type": "person", "confidence": 1.5}]}
    with pytest.raises(ValueError):
        _ExtractionResult.model_validate(data)


# ── Retry-with-correction tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_retries_on_invalid_json_then_succeeds():
    """LLM returns garbage on first try, valid JSON on second."""
    import memoryhub_core.services.extraction as ext

    old = ext._llm_extractor
    ext._llm_extractor = None

    good_json = json.dumps({
        "entities": [{"name": "Alice", "type": "person", "confidence": 0.9}],
        "relationships": [],
    })

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            body = json.dumps({
                "choices": [{"message": {"content": "not valid json"}}],
            }).encode()
        else:
            body = json.dumps({
                "choices": [{"message": {"content": good_json}}],
            }).encode()
        return httpx.Response(
            200, content=body,
            request=httpx.Request("POST", "http://llm:8000"),
        )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract."}),
        patch("builtins.open", MagicMock()),
    ):
        entities, rels = await run_llm_ner("Alice is here")

    ext._llm_extractor = old

    assert call_count == 2
    assert len(entities) == 1
    assert entities[0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_llm_retries_on_schema_failure_then_succeeds():
    """LLM returns wrong schema on first try, correct on second."""
    import memoryhub_core.services.extraction as ext

    old = ext._llm_extractor
    ext._llm_extractor = None

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Valid JSON but confidence out of range
            bad = json.dumps({
                "entities": [
                    {"name": "X", "type": "person", "confidence": 5.0},
                ],
            })
        else:
            bad = json.dumps({
                "entities": [
                    {"name": "Alice", "type": "person", "confidence": 0.9},
                ],
                "relationships": [],
            })
        body = json.dumps({
            "choices": [{"message": {"content": bad}}],
        }).encode()
        return httpx.Response(
            200, content=body,
            request=httpx.Request("POST", "http://llm:8000"),
        )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract."}),
        patch("builtins.open", MagicMock()),
    ):
        entities, rels = await run_llm_ner("Alice is here")

    ext._llm_extractor = old

    assert call_count == 2
    assert len(entities) == 1


@pytest.mark.asyncio
async def test_llm_exhausts_retries_on_persistent_bad_format():
    """All retries fail with bad format -> raises LLMExtractionServiceError."""
    import memoryhub_core.services.extraction as ext
    from memoryhub_core.services.exceptions import LLMExtractionServiceError

    old = ext._llm_extractor
    ext._llm_extractor = None

    async def mock_post(*args, **kwargs):
        body = json.dumps({
            "choices": [{"message": {"content": "not json"}}],
        }).encode()
        return httpx.Response(
            200, content=body,
            request=httpx.Request("POST", "http://llm:8000"),
        )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract."}),
        patch("builtins.open", MagicMock()),
        pytest.raises(LLMExtractionServiceError, match="not valid JSON"),
    ):
        await run_llm_ner("some text")

    ext._llm_extractor = old


@pytest.mark.asyncio
async def test_llm_correction_message_includes_bad_response():
    """Verify the correction flow appends the bad response to messages."""
    import memoryhub_core.services.extraction as ext

    old = ext._llm_extractor
    ext._llm_extractor = None

    captured_messages = []

    async def mock_post(*args, **kwargs):
        payload = kwargs.get("json") or args[1]
        captured_messages.append(payload["messages"])
        good = json.dumps({
            "entities": [{"name": "A", "type": "person", "confidence": 0.9}],
            "relationships": [],
        })
        content = "garbage" if len(captured_messages) == 1 else good
        body = json.dumps({
            "choices": [{"message": {"content": content}}],
        }).encode()
        return httpx.Response(
            200, content=body,
            request=httpx.Request("POST", "http://llm:8000"),
        )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract."}),
        patch("builtins.open", MagicMock()),
    ):
        await run_llm_ner("test text")

    ext._llm_extractor = old

    # Second call should have correction messages
    assert len(captured_messages) == 2
    retry_msgs = captured_messages[1]
    # Should have: system, user, assistant (bad), user (correction)
    assert len(retry_msgs) == 4
    assert retry_msgs[2]["role"] == "assistant"
    assert retry_msgs[2]["content"] == "garbage"
    assert retry_msgs[3]["role"] == "user"
    assert "did not match the required schema" in retry_msgs[3]["content"]


@pytest.mark.asyncio
async def test_llm_service_error_retries_on_503():
    """503 from vLLM triggers service-level retry."""
    import memoryhub_core.services.extraction as ext
    from memoryhub_core.services.exceptions import (
        LLMExtractionServiceUnavailableError,
    )

    old = ext._llm_extractor
    ext._llm_extractor = None

    async def mock_post(*args, **kwargs):
        return httpx.Response(
            503, content=b"Service Unavailable",
            request=httpx.Request("POST", "http://llm:8000"),
        )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract."}),
        patch("builtins.open", MagicMock()),
        pytest.raises(LLMExtractionServiceUnavailableError, match="503"),
    ):
        await run_llm_ner("test text")

    ext._llm_extractor = old


@pytest.mark.asyncio
async def test_llm_service_error_does_not_retry_on_400():
    """Non-retryable HTTP errors (400) raise immediately without retry."""
    import memoryhub_core.services.extraction as ext
    from memoryhub_core.services.exceptions import LLMExtractionServiceError

    old = ext._llm_extractor
    ext._llm_extractor = None

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            400, content=b"Bad Request",
            request=httpx.Request("POST", "http://llm:8000"),
        )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract."}),
        patch("builtins.open", MagicMock()),
        pytest.raises(LLMExtractionServiceError, match="400"),
    ):
        await run_llm_ner("test text")

    ext._llm_extractor = old
    assert call_count == 1  # no retry on 400


@pytest.mark.asyncio
async def test_llm_handles_code_fenced_response():
    """LLM wraps JSON in code fences -> best-effort parser handles it."""
    import memoryhub_core.services.extraction as ext

    old = ext._llm_extractor
    ext._llm_extractor = None

    fenced = '```json\n{"entities": [{"name": "Bob", "type": "person", "confidence": 0.95}], "relationships": []}\n```'

    async def mock_post(*args, **kwargs):
        body = json.dumps({
            "choices": [{"message": {"content": fenced}}],
        }).encode()
        return httpx.Response(
            200, content=body,
            request=httpx.Request("POST", "http://llm:8000"),
        )

    with (
        patch.dict("os.environ", {
            "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm:8000",
            "MEMORYHUB_LLM_EXTRACTION_MODEL": "test-model",
        }),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post),
        patch("yaml.safe_load", return_value={"system_prompt": "Extract."}),
        patch("builtins.open", MagicMock()),
    ):
        entities, rels = await run_llm_ner("Bob is here")

    ext._llm_extractor = old

    assert len(entities) == 1
    assert entities[0]["name"] == "Bob"


# ── Integration: acronym discount triggers Stage 3 with real LLM ──────────

_LLM_URL = os.environ.get("MEMORYHUB_LLM_EXTRACTION_URL", "")
_LLM_MODEL = os.environ.get(
    "MEMORYHUB_LLM_EXTRACTION_MODEL", "RedHatAI/gpt-oss-20b",
)

_skip_no_llm = pytest.mark.skipif(
    not _LLM_URL,
    reason="MEMORYHUB_LLM_EXTRACTION_URL not set; skipping live LLM test",
)


@_skip_no_llm
@pytest.mark.integration
@pytest.mark.asyncio
async def test_acronym_discount_triggers_stage3_live_llm(async_session):
    """End-to-end: acronym discount causes Stage 3 to fire against real LLM.

    Scenario: spaCy produces only acronym entities (ORM, NER) which get
    discounted to 0.5 confidence. GLiNER finds nothing additional. The
    combined high-confidence count (0) is below the Stage 3 threshold (2),
    so Stage 3 fires against the real GPT-OSS 20B endpoint and extracts
    entities that spaCy and GLiNER missed.

    Requires MEMORYHUB_LLM_EXTRACTION_URL to be set (e.g., via port-forward
    or cluster route).
    """
    import memoryhub_core.services.extraction as ext
    from memoryhub_core.services.extraction import extract_entities_from_memory

    embedding_service = MockEmbeddingService()
    memory_id = uuid.uuid4()

    from datetime import UTC, datetime

    from memoryhub_core.models.memory import MemoryNode

    content = (
        "Alice Johnson deployed PostgreSQL and Redis on OpenShift. "
        "She configured ORM and NER pipelines for the project."
    )

    now = datetime.now(UTC)
    async_session.add(MemoryNode(
        id=memory_id,
        content=content,
        stub=content[:40] + "...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    # Stage 1: spaCy finds only acronyms (discounted to 0.5) and maybe
    # "Alice Johnson" (1.0). We mock spaCy to return ONLY the acronyms
    # so that spaCy alone doesn't meet the threshold.
    fake_nlp = FakeNlp([
        SpacyEntity("ORM", "ORG", 67, 70),
        SpacyEntity("NER", "ORG", 75, 78),
    ])

    # Stage 2: GLiNER returns nothing (simulates domain gap)
    fake_gliner = FakeGLiNERModel([])

    # Reset the singleton so it picks up test env vars
    old_extractor = ext._llm_extractor
    ext._llm_extractor = None

    try:
        with (
            patch("memoryhub_core.services.extraction._get_nlp", return_value=fake_nlp),
            patch("memoryhub_core.services.extraction._get_gliner", return_value=fake_gliner),
            patch.dict("os.environ", {
                "MEMORYHUB_LLM_EXTRACTION_URL": _LLM_URL,
                "MEMORYHUB_LLM_EXTRACTION_MODEL": _LLM_MODEL,
            }),
        ):
            result = await extract_entities_from_memory(
                memory_id=memory_id,
                content=content,
                session=async_session,
                embedding_service=embedding_service,
                tenant_id="test-tenant",
                owner_id="test-user",
            )
    finally:
        ext._llm_extractor = old_extractor

    # Stage 3 should have fired and found entities
    extractors = {e["extractor"] for e in result["entities"]}
    assert "llm" in extractors, (
        f"Stage 3 should have fired (acronym discount -> low confidence). "
        f"Got extractors: {extractors}, entities: {result['entities']}"
    )

    # The LLM should have found real entities from the text
    assert len(result["entities"]) >= 3, (
        f"Expected LLM to find multiple entities. Got: {result['entities']}"
    )
