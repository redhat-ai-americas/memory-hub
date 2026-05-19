"""Entity extraction pipeline -- spaCy NER with POLE+O type mapping.

Stage 1 of the multi-stage extraction cascade (#170 Phase 2). Extracts
named entities from memory content using spaCy, creates entity nodes
via find_or_create_entity, and links them to the source memory via
MENTIONS relationships. Designed for async background execution after
write commits.
"""

import logging
import uuid
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.entity import (
    create_mentions_relationship,
    find_or_create_entity,
)

logger = logging.getLogger(__name__)

# spaCy label -> POLE+O type mapping.  Unmapped labels (DATE, TIME, MONEY,
# PERCENT, QUANTITY, ORDINAL, CARDINAL, NORP, PRODUCT, WORK_OF_ART, LAW,
# LANGUAGE) are skipped -- they don't map to the POLE+O entity model.
# Stage 2 (GLiNER2) will handle OBJECT entities not covered by spaCy.
_SPACY_LABEL_MAP: dict[str, str] = {
    "PERSON": "person",
    "ORG": "organization",
    "GPE": "location",
    "LOC": "location",
    "FAC": "location",
    "EVENT": "event",
}

# Module-level spaCy model cache (lazy-loaded on first call)
_nlp = None


def _get_nlp():
    """Lazy-load the spaCy model. Cached at module level."""
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def run_spacy_ner(text: str) -> list[dict[str, Any]]:
    """Run spaCy NER and return extracted entities.

    Returns a list of dicts with keys: name, type, label, start, end.
    Deduplicates by (lowered name, type) within a single text, keeping
    the first occurrence.
    """
    if not text or not text.strip():
        return []

    nlp = _get_nlp()
    doc = nlp(text)

    seen: set[tuple[str, str]] = set()
    entities: list[dict[str, Any]] = []

    for ent in doc.ents:
        pole_type = _SPACY_LABEL_MAP.get(ent.label_)
        if pole_type is None:
            continue

        key = (ent.text.strip().lower(), pole_type)
        if key in seen:
            continue
        seen.add(key)

        entities.append({
            "name": ent.text.strip(),
            "type": pole_type,
            "label": ent.label_,
            "start": ent.start_char,
            "end": ent.end_char,
        })

    return entities


async def extract_entities_from_memory(
    memory_id: uuid.UUID,
    content: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    owner_id: str,
) -> dict[str, Any]:
    """Extract entities from memory content and create entity nodes + MENTIONS edges.

    Returns a summary dict with extracted entity info for logging.
    """
    raw_entities = run_spacy_ner(content)
    if not raw_entities:
        return {"memory_id": str(memory_id), "entities": [], "count": 0}

    created_entities: list[dict[str, Any]] = []

    for raw in raw_entities:
        try:
            entity_node, was_created = await find_or_create_entity(
                name=raw["name"],
                entity_type=raw["type"],
                session=session,
                embedding_service=embedding_service,
                tenant_id=tenant_id,
                owner_id=owner_id,
                confidence=1.0,
                extractor="spacy",
            )

            await create_mentions_relationship(
                memory_id=memory_id,
                entity_id=entity_node.id,
                session=session,
                tenant_id=tenant_id,
                metadata={"extractor": "spacy", "label": raw["label"]},
            )

            created_entities.append({
                "name": raw["name"],
                "type": raw["type"],
                "entity_id": str(entity_node.id),
                "was_created": was_created,
            })
        except Exception:
            logger.warning(
                "Failed to process entity '%s' (type=%s) for memory %s",
                raw["name"], raw["type"], memory_id,
                exc_info=True,
            )

    return {
        "memory_id": str(memory_id),
        "entities": created_entities,
        "count": len(created_entities),
    }
