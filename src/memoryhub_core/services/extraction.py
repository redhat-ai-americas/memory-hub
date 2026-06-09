"""Entity extraction pipeline -- spaCy NER + GLiNER2 zero-shot + LLM fallback cascade.

Three-stage extraction cascade (#170 Phase 2, #248, #249):

- Stage 1 (spaCy) runs always for fast person/org/location/event extraction.
- Stage 2 (GLiNER2) runs always alongside Stage 1 for zero-shot extraction
  of objects, technologies, and domain terms.
- Stage 3 (LLM) fires when Stages 1+2 combined still have low coverage.
  This is the only stage that extracts inter-entity relationships (not just
  memory-to-entity MENTIONS edges).

Entities are created via find_or_create_entity and linked to the source
memory via MENTIONS relationships. Designed for async background execution
after write commits.
"""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.config import AppSettings
from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.entity import (
    create_mentions_relationship,
    find_or_create_entity,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage 1: spaCy NER
# ---------------------------------------------------------------------------

# spaCy label -> POLE+O type mapping.  Unmapped labels (DATE, TIME, MONEY,
# PERCENT, QUANTITY, ORDINAL, CARDINAL, NORP, PRODUCT, WORK_OF_ART, LAW,
# LANGUAGE) are skipped -- they don't map to the POLE+O entity model.
_SPACY_LABEL_MAP: dict[str, str] = {
    "PERSON": "person",
    "ORG": "organization",
    "GPE": "location",
    "LOC": "location",
    "FAC": "location",
    "EVENT": "event",
}

_ACRONYM_PATTERN = re.compile(r"^[A-Z]{2,}$")
_ACRONYM_CONFIDENCE_DISCOUNT = 0.5

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

    Returns a list of dicts with keys: name, type, label, start, end, confidence.
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

        name = ent.text.strip()
        key = (name.lower(), pole_type)
        if key in seen:
            continue
        seen.add(key)

        confidence = _ACRONYM_CONFIDENCE_DISCOUNT if _ACRONYM_PATTERN.match(name) else 1.0

        entities.append({
            "name": name,
            "type": pole_type,
            "label": ent.label_,
            "start": ent.start_char,
            "end": ent.end_char,
            "confidence": confidence,
        })

    return entities


# ---------------------------------------------------------------------------
# Stage 2: GLiNER2 zero-shot NER
# ---------------------------------------------------------------------------

_GLINER_LABELS = [
    "person", "organization", "location", "event",
    "technology", "programming language", "framework",
    "protocol", "database", "tool", "concept",
]

# Map GLiNER's fine-grained labels back to POLE+O types
_GLINER_LABEL_TO_POLE: dict[str, str] = {
    "person": "person",
    "organization": "organization",
    "location": "location",
    "event": "event",
    "technology": "object",
    "programming language": "object",
    "framework": "object",
    "protocol": "object",
    "database": "object",
    "tool": "object",
    "concept": "object",
}

_gliner_model = None


def _get_gliner():
    """Lazy-load the GLiNER model. Cached at module level (assumes gliner_model config is static)."""
    global _gliner_model
    if _gliner_model is None:
        from gliner import GLiNER
        settings = AppSettings()
        _gliner_model = GLiNER.from_pretrained(settings.gliner_model)
    return _gliner_model


def run_gliner_ner(text: str) -> list[dict[str, Any]]:
    """Run GLiNER zero-shot NER and return extracted entities.

    Returns a list of dicts with keys: name, type, label, start, end, confidence.
    Deduplicates by (lowered name, type) within a single text.
    """
    if not text or not text.strip():
        return []

    settings = AppSettings()
    model = _get_gliner()
    raw_entities = model.predict_entities(
        text,
        _GLINER_LABELS,
        threshold=settings.gliner_confidence_threshold,
    )

    seen: set[tuple[str, str]] = set()
    entities: list[dict[str, Any]] = []

    for ent in raw_entities:
        pole_type = _GLINER_LABEL_TO_POLE.get(ent["label"])
        if pole_type is None:
            continue

        name = ent["text"].strip()
        if not name:
            continue

        key = (name.lower(), pole_type)
        if key in seen:
            continue
        seen.add(key)

        entities.append({
            "name": name,
            "type": pole_type,
            "label": ent["label"],
            "start": ent["start"],
            "end": ent["end"],
            "confidence": ent["score"],
        })

    return entities


# ---------------------------------------------------------------------------
# Stage 3: LLM fallback NER + relationship extraction
# ---------------------------------------------------------------------------

_VALID_POLE_TYPES = {"person", "organization", "location", "event", "object"}
_LLM_CONFIDENCE_FLOOR = 0.5
_LLM_MAX_FORMAT_RETRIES = 3
_LLM_MAX_SERVICE_RETRIES = 2

# ---------------------------------------------------------------------------
# Pydantic validation models for LLM structured output
# ---------------------------------------------------------------------------


class _ExtractedEntity(BaseModel):
    name: str = Field(min_length=1)
    type: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("type")
    @classmethod
    def normalize_type(cls, v: str) -> str:
        return v.lower().strip()


class _ExtractedRelationship(BaseModel):
    source_name: str = Field(min_length=1)
    target_name: str = Field(min_length=1)
    relationship_type: str = "related_to"


class _ExtractionResult(BaseModel):
    entities: list[_ExtractedEntity] = []
    relationships: list[_ExtractedRelationship] = []


# ---------------------------------------------------------------------------
# Best-effort JSON parsing (fallback chain from CDC pipeline patterns)
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\n?```\s*$", "", text.strip()).strip()


def _parse_json_best_effort(text: str) -> dict[str, Any] | None:
    """Parse JSON with progressive fallbacks.

    Chain: direct parse -> strip code fences -> regex extraction -> None.
    """
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# LLM extractor with retry-with-correction and circuit breaker
# ---------------------------------------------------------------------------

_llm_extractor = None


class _LLMExtractor:
    """LLM-based entity and relationship extractor for Stage 3.

    Resilience layers (adapted from CDC data-acceptance-testing pipeline):
    - Best-effort JSON parsing (code fence stripping, regex extraction)
    - Pydantic schema validation via _ExtractionResult
    - Retry with correction: on format failure, inject the bad response
      and a correction message, then retry (the model responds well to
      seeing its own mistake)
    - Separate service-error handling with exponential backoff
    """

    def __init__(self) -> None:
        settings = AppSettings()
        self.url = settings.llm_extraction_url.rstrip("/")
        self.model = settings.llm_extraction_model
        self._client = httpx.AsyncClient(
            timeout=settings.llm_extraction_timeout,
            verify=False,  # cluster-internal TLS
        )
        self._system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load system prompt from prompts/entity_extraction.yaml."""
        prompt_path = (
            Path(__file__).resolve().parents[3]
            / "prompts" / "entity_extraction.yaml"
        )
        with open(prompt_path) as f:
            data = yaml.safe_load(f)
        return data["system_prompt"]

    async def extract(
        self, text: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract entities and relationships from text via LLM.

        Uses retry-with-correction on format/validation failures and
        exponential backoff on service errors.
        """
        from memoryhub_core.services.exceptions import LLMExtractionServiceError

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": text},
        ]
        last_error: Exception | None = None

        for attempt in range(_LLM_MAX_FORMAT_RETRIES):
            raw_content = await self._call_llm(messages)

            if raw_content is None:
                raw_content = ""

            parsed = _parse_json_best_effort(raw_content)
            if parsed is None:
                reason = "Response was not valid JSON"
                logger.warning(
                    "LLM extraction format error (attempt %d/%d): %s",
                    attempt + 1, _LLM_MAX_FORMAT_RETRIES, reason,
                )
                messages = self._inject_correction(
                    messages, raw_content, reason,
                )
                last_error = LLMExtractionServiceError(reason)
                if attempt < _LLM_MAX_FORMAT_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            try:
                result = _ExtractionResult.model_validate(parsed)
            except Exception as exc:
                reason = f"Schema validation failed: {exc}"
                logger.warning(
                    "LLM extraction validation error (attempt %d/%d): %s",
                    attempt + 1, _LLM_MAX_FORMAT_RETRIES, reason,
                )
                messages = self._inject_correction(
                    messages, raw_content, reason,
                )
                last_error = LLMExtractionServiceError(reason)
                if attempt < _LLM_MAX_FORMAT_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            entities = self._to_entity_dicts(result.entities)
            relationships = self._to_relationship_dicts(result.relationships)
            return entities, relationships

        raise last_error or LLMExtractionServiceError(
            "LLM extraction failed after all retries"
        )

    async def _call_llm(self, messages: list[dict[str, Any]]) -> str:
        """Make the HTTP call to vLLM with service-error retry."""
        from memoryhub_core.services.exceptions import (
            LLMExtractionServiceError,
            LLMExtractionServiceUnavailableError,
        )

        last_error: Exception | None = None

        for attempt in range(_LLM_MAX_SERVICE_RETRIES):
            try:
                response = await self._client.post(
                    f"{self.url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.0,
                        "max_tokens": 2000,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
            except httpx.ConnectError as exc:
                last_error = LLMExtractionServiceUnavailableError(
                    "Could not connect to LLM extraction service"
                )
                last_error.__cause__ = exc
            except httpx.TimeoutException as exc:
                last_error = LLMExtractionServiceUnavailableError(
                    "LLM extraction request timed out"
                )
                last_error.__cause__ = exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (429, 502, 503, 504):
                    last_error = LLMExtractionServiceUnavailableError(
                        f"LLM service returned {status}"
                    )
                    last_error.__cause__ = exc
                else:
                    raise LLMExtractionServiceError(
                        f"LLM extraction failed with status {status}"
                    ) from exc
            else:
                try:
                    return response.json()["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise LLMExtractionServiceError(
                        f"Unexpected response structure: {exc}"
                    ) from exc

            if attempt < _LLM_MAX_SERVICE_RETRIES - 1:
                delay = (2 ** attempt) * 2.0  # 2s, 4s
                logger.warning(
                    "LLM service error (attempt %d/%d): %s — retrying in %.0fs",
                    attempt + 1, _LLM_MAX_SERVICE_RETRIES,
                    last_error, delay,
                )
                await asyncio.sleep(delay)

        raise last_error or LLMExtractionServiceUnavailableError(
            "LLM service unavailable after all retries"
        )

    def _inject_correction(
        self,
        messages: list[dict[str, Any]],
        bad_response: str,
        reason: str,
    ) -> list[dict[str, Any]]:
        """Build a new message list with the bad response and correction."""
        return messages + [
            {"role": "assistant", "content": bad_response},
            {
                "role": "user",
                "content": (
                    f"That response did not match the required schema: "
                    f"{reason}. Return a JSON object with two arrays: "
                    f'"entities" (each with name, type, confidence) and '
                    f'"relationships" (each with source_name, target_name, '
                    f"relationship_type). Types must be one of: "
                    f"person, organization, location, event, object."
                ),
            },
        ]

    def _to_entity_dicts(
        self, entities: list[_ExtractedEntity],
    ) -> list[dict[str, Any]]:
        """Convert validated Pydantic entities to the stage dict format."""
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, Any]] = []
        for e in entities:
            if e.type not in _VALID_POLE_TYPES:
                continue
            if e.confidence < _LLM_CONFIDENCE_FLOOR:
                continue
            key = (e.name.lower(), e.type)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "name": e.name,
                "type": e.type,
                "label": e.type,
                "start": -1,
                "end": -1,
                "confidence": e.confidence,
            })
        return result

    def _to_relationship_dicts(
        self, relationships: list[_ExtractedRelationship],
    ) -> list[dict[str, Any]]:
        """Convert validated Pydantic relationships to the stage dict format."""
        return [
            {
                "source_name": r.source_name,
                "target_name": r.target_name,
                "relationship_type": r.relationship_type,
            }
            for r in relationships
        ]


def _get_llm_extractor() -> _LLMExtractor:
    """Lazy-initialize and return the module-level LLM extractor."""
    global _llm_extractor
    if _llm_extractor is None:
        _llm_extractor = _LLMExtractor()
    return _llm_extractor


async def run_llm_ner(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run LLM extraction and return (entities, relationships).

    Unlike Stages 1/2 which return only entities, Stage 3 also extracts
    inter-entity relationships.
    """
    if not text or not text.strip():
        return [], []
    extractor = _get_llm_extractor()
    return await extractor.extract(text)


# ---------------------------------------------------------------------------
# Cascade: Stage 1 + Stage 2 (always) -> Stage 3 (conditional)
# ---------------------------------------------------------------------------

def _should_run_stage2(stage1_entities: list[dict[str, Any]]) -> bool:
    """Return True if Stage 1 coverage is too low and Stage 2 should run.

    .. deprecated::
        GLiNER now runs unconditionally alongside spaCy (#267).
        Retained for backward compatibility with tests.
    """
    settings = AppSettings()
    high_confidence = sum(
        1 for e in stage1_entities
        if e.get("confidence", 0) >= settings.gliner_stage2_trigger_confidence
    )
    return high_confidence < settings.gliner_stage2_trigger_count


def _tag_extractor(entities: list[dict[str, Any]], extractor: str) -> list[dict[str, Any]]:
    """Return a copy of each entity dict tagged with its source extractor name."""
    return [{**e, "extractor": extractor} for e in entities]


def _should_run_stage3(all_entities: list[dict[str, Any]]) -> bool:
    """Return True if combined Stage 1+2 coverage is too low and Stage 3 should run."""
    settings = AppSettings()
    if not settings.llm_extraction_url:
        return False
    high_confidence = sum(
        1 for e in all_entities
        if e.get("confidence", 0) >= settings.llm_stage3_trigger_confidence
    )
    return high_confidence < settings.llm_stage3_trigger_count


def _merge_entities(
    stage1: list[dict[str, Any]],
    stage2: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge Stage 2 entities into Stage 1, dropping duplicates by (name, type)."""
    seen = {(e["name"].lower(), e["type"]) for e in stage1}
    merged = list(stage1)
    for ent in stage2:
        key = (ent["name"].lower(), ent["type"])
        if key not in seen:
            seen.add(key)
            merged.append(ent)
    return merged


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

    Runs the three-stage cascade: Stages 1 (spaCy) and 2 (GLiNER2) run
    unconditionally; Stage 3 (LLM) fires when Stages 1+2 combined produce
    fewer than 2 high-confidence entities. Stage 3 is the only stage that
    also extracts inter-entity relationships. Returns a summary dict with
    extracted entity info for logging.
    """
    stage1_entities = _tag_extractor(run_spacy_ner(content), "spacy")

    # Stage 2: GLiNER always runs alongside spaCy (#267)
    try:
        stage2_entities = _tag_extractor(run_gliner_ner(content), "gliner")
        all_entities = _merge_entities(stage1_entities, stage2_entities)
        logger.debug(
            "Stage 2 (GLiNER) added %d entities for memory %s",
            len(all_entities) - len(stage1_entities), memory_id,
        )
    except Exception:
        logger.warning(
            "GLiNER Stage 2 failed for memory %s; using Stage 1 results only",
            memory_id,
            exc_info=True,
        )
        all_entities = stage1_entities

    # Stage 3: LLM fallback (conditional)
    llm_relationships: list[dict[str, Any]] = []
    if _should_run_stage3(all_entities):
        try:
            stage3_entities, llm_relationships = await run_llm_ner(content)
            stage3_tagged = _tag_extractor(stage3_entities, "llm")
            all_entities = _merge_entities(all_entities, stage3_tagged)
            logger.debug(
                "Stage 3 (LLM) added %d entities, %d relationships for memory %s",
                len(stage3_tagged), len(llm_relationships), memory_id,
            )
        except Exception:
            logger.warning(
                "LLM Stage 3 failed for memory %s; using Stage 1+2 results only",
                memory_id,
                exc_info=True,
            )

    if not all_entities:
        return {"memory_id": str(memory_id), "entities": [], "count": 0}

    created_entities: list[dict[str, Any]] = []

    for raw in all_entities:
        extractor = raw.get("extractor", "spacy")

        try:
            entity_node, was_created = await find_or_create_entity(
                name=raw["name"],
                entity_type=raw["type"],
                session=session,
                embedding_service=embedding_service,
                tenant_id=tenant_id,
                owner_id=owner_id,
                confidence=raw.get("confidence", 1.0),
                extractor=extractor,
            )

            await create_mentions_relationship(
                memory_id=memory_id,
                entity_id=entity_node.id,
                session=session,
                tenant_id=tenant_id,
                metadata={"extractor": extractor, "label": raw["label"]},
            )

            created_entities.append({
                "name": raw["name"],
                "type": raw["type"],
                "entity_id": str(entity_node.id),
                "was_created": was_created,
                "extractor": extractor,
            })
        except Exception:
            logger.warning(
                "Failed to process entity '%s' (type=%s) for memory %s",
                raw["name"], raw["type"], memory_id,
                exc_info=True,
            )

    # Create inter-entity relationships from Stage 3 LLM extraction
    if llm_relationships:
        entity_name_to_id: dict[str, uuid.UUID] = {}
        for e in created_entities:
            entity_name_to_id[e["name"].lower()] = uuid.UUID(e["entity_id"])

        for rel in llm_relationships:
            try:
                source_id = entity_name_to_id.get(rel["source_name"].lower())
                target_id = entity_name_to_id.get(rel["target_name"].lower())
                if source_id is None or target_id is None:
                    continue
                if source_id == target_id:
                    continue

                from memoryhub_core.models.schemas import RelationshipCreate
                from memoryhub_core.services.graph import create_relationship

                rel_create = RelationshipCreate(
                    source_id=source_id,
                    target_id=target_id,
                    relationship_type="related_to",
                    created_by="system:entity_extraction",
                    metadata={
                        "llm_relationship_type": rel.get("relationship_type", "related_to"),
                        "extractor": "llm",
                    },
                )
                await create_relationship(rel_create, session)
            except Exception:
                logger.warning(
                    "Failed to create inter-entity relationship %s -> %s for memory %s",
                    rel.get("source_name"), rel.get("target_name"), memory_id,
                    exc_info=True,
                )

    return {
        "memory_id": str(memory_id),
        "entities": created_entities,
        "count": len(created_entities),
    }
