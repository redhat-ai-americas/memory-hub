"""MemoryHub provider for AMB benchmark.

Uses the memoryhub SDK (MemoryHubClient) to talk to the MCP server over
streamable-HTTP -- the same path any agent would use.

Required env vars:
    MEMORYHUB_URL        -- MCP server endpoint (e.g. https://...apps.../mcp/)
    MEMORYHUB_API_KEY    -- API key for register_session auth
    MEMORYHUB_PROJECT_ID -- project for benchmark memories (default: amb-benchmark)

Optional env vars:
    MEMORYHUB_TENANT_ID        -- explicit tenant for search/write (default: session tenant)
    MEMORYHUB_DISABLED_SIGNALS -- comma-separated signal names to disable
                                  (reranker, focus, keyword, domain, graph)
    MEMORYHUB_FOCUS_MODE       -- "persona" to pass persona name as focus string,
                                  enabling 2-vector retrieval (default: off)
    MEMORYHUB_RETURN_CHUNKS    -- "true" to return matched chunks directly
                                  instead of expanding to parent memories
    MEMORYHUB_K                -- retrieval depth, default 70
    MEMORYHUB_CHUNK_TARGET_TOKENS  -- target tokens per chunk (default: server default, 256)
    MEMORYHUB_CHUNK_OVERLAP_TOKENS -- overlap tokens between chunks (default: 0)
    MEMORYHUB_EXTRACT_FACTS        -- fact extraction mode: eager, background, off
                                     (default: None = server default)
    MEMORYHUB_INGESTION_MODE       -- "library" (default) or "dreaming"
    MEMORYHUB_EXTRACTION_MODEL     -- extraction model name (dreaming mode only)
    MEMORYHUB_EXTRACTION_MODEL_URL -- extraction model endpoint (dreaming mode only)

Reset-only env vars (raw SQL DELETE for test scaffolding):
    MEMORYHUB_DB_HOST    -- default localhost
    MEMORYHUB_DB_PORT    -- default 25432
    MEMORYHUB_DB_USER    -- default memoryhub
    MEMORYHUB_DB_PASS
    MEMORYHUB_DB_NAME    -- default memoryhub
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from memoryhub import MemoryHubClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..models import Document
from .base import MemoryProvider

logger = logging.getLogger(__name__)


class MemoryHubProvider(MemoryProvider):
    name = "memoryhub"
    description = "MemoryHub via SDK (vector + keyword + reranker + RRF)"
    kind = "cloud"
    concurrency = 1

    def __init__(self):
        self._url: str | None = None
        self._api_key: str | None = None
        self._project_id: str | None = None
        self._db_url: str | None = None
        self._doc_to_memory_id: dict[str, str] = {}
        self._memory_to_doc_id: dict[str, str] = {}
        self._reset = False
        self._disabled_signals: list[str] | None = None
        self._tenant_id: str | None = None
        self._focus_mode: str | None = None
        self._return_chunks: bool = False
        self._chunk_target_tokens: int | None = None
        self._chunk_overlap_tokens: int | None = None
        self._extract_facts: str | None = None
        self._ingestion_mode: str = "library"
        self._extraction_model: str | None = None
        self._extraction_model_url: str | None = None

    def prepare(self, store_dir: Path, unit_ids: set[str] | None = None, reset: bool = True) -> None:
        self._url = os.environ.get("MEMORYHUB_URL")
        self._api_key = os.environ.get("MEMORYHUB_API_KEY")
        self._project_id = os.environ.get("MEMORYHUB_PROJECT_ID", "amb-benchmark")
        if not self._url or not self._api_key:
            raise RuntimeError(
                "MEMORYHUB_URL and MEMORYHUB_API_KEY are required. "
                "Point MEMORYHUB_URL at the MCP server's streamable-HTTP endpoint."
            )

        db_host = os.environ.get("MEMORYHUB_DB_HOST", "localhost")
        db_port = os.environ.get("MEMORYHUB_DB_PORT", "25432")
        db_user = os.environ.get("MEMORYHUB_DB_USER", "memoryhub")
        db_pass = os.environ.get("MEMORYHUB_DB_PASS", "")
        db_name = os.environ.get("MEMORYHUB_DB_NAME", "memoryhub")
        self._db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

        self._tenant_id = os.environ.get("MEMORYHUB_TENANT_ID") or None

        raw_disabled = os.environ.get("MEMORYHUB_DISABLED_SIGNALS", "")
        self._disabled_signals = (
            [s.strip() for s in raw_disabled.split(",") if s.strip()]
            if raw_disabled else None
        )

        self._focus_mode = os.environ.get("MEMORYHUB_FOCUS_MODE", "").strip().lower() or None
        self._return_chunks = os.environ.get("MEMORYHUB_RETURN_CHUNKS", "").lower() in ("1", "true", "yes")

        raw_chunk_target = os.environ.get("MEMORYHUB_CHUNK_TARGET_TOKENS", "").strip()
        self._chunk_target_tokens = int(raw_chunk_target) if raw_chunk_target else None
        raw_chunk_overlap = os.environ.get("MEMORYHUB_CHUNK_OVERLAP_TOKENS", "").strip()
        self._chunk_overlap_tokens = int(raw_chunk_overlap) if raw_chunk_overlap else None

        raw_extract = os.environ.get("MEMORYHUB_EXTRACT_FACTS", "").strip().lower()
        self._extract_facts = raw_extract if raw_extract in ("eager", "background", "off") else None

        raw_mode = os.environ.get("MEMORYHUB_INGESTION_MODE", "library").strip().lower()
        if raw_mode not in ("library", "dreaming"):
            raise RuntimeError(
                f"MEMORYHUB_INGESTION_MODE must be 'library' or 'dreaming', got '{raw_mode}'"
            )
        self._ingestion_mode = raw_mode
        self._extraction_model = os.environ.get("MEMORYHUB_EXTRACTION_MODEL", "").strip() or None
        self._extraction_model_url = os.environ.get("MEMORYHUB_EXTRACTION_MODEL_URL", "").strip() or None

        self._doc_to_memory_id.clear()
        self._memory_to_doc_id.clear()
        self._reset = reset

    def ingest(self, documents: list[Document]) -> None:
        asyncio.run(self._run_ingest(documents))

    async def _run_ingest(self, documents: list[Document]) -> None:
        if self._reset:
            await self._reset_benchmark_data()
            self._reset = False

        if self._ingestion_mode == "dreaming":
            await self._run_dreaming_ingest(documents)
        else:
            await self._run_library_ingest(documents)

    async def _run_library_ingest(self, documents: list[Document]) -> None:
        async with MemoryHubClient(url=self._url, api_key=self._api_key) as client:
            try:
                await client.create_project(
                    self._project_id,
                    description="AMB benchmark memory isolation",
                )
                logger.info("Created project %s", self._project_id)
            except Exception:
                logger.debug("Project %s already exists", self._project_id)

            for i, doc in enumerate(documents):
                owner = f"amb-{doc.user_id}" if doc.user_id else "amb-default"
                write_kwargs: dict[str, Any] = dict(
                    content=doc.content,
                    scope="project",
                    project_id=self._project_id,
                    owner_id=owner,
                    content_type="experiential",
                    force=True,
                )
                if self._tenant_id:
                    write_kwargs["tenant_id"] = self._tenant_id
                if self._chunk_target_tokens is not None:
                    write_kwargs["chunk_target_tokens"] = self._chunk_target_tokens
                if self._chunk_overlap_tokens is not None:
                    write_kwargs["chunk_overlap_tokens"] = self._chunk_overlap_tokens
                if self._extract_facts is not None:
                    write_kwargs["extract_facts"] = self._extract_facts
                result = await client.write(**write_kwargs)

                if result.memory:
                    self._doc_to_memory_id[doc.id] = result.memory.id
                    self._memory_to_doc_id[result.memory.id] = doc.id
                else:
                    logger.warning(
                        "Write returned no memory for doc %s (curation gated: %s)",
                        doc.id, result.curation.gated,
                    )

                if (i + 1) % 50 == 0:
                    logger.info("Ingested %d/%d documents", i + 1, len(documents))

        logger.info("Ingestion complete: %d documents", len(documents))

    async def _run_dreaming_ingest(self, documents: list[Document]) -> None:
        """Ingest via dreaming mode: threads + extraction per session."""
        persona_sessions: dict[str, list[Document]] = defaultdict(list)
        for doc in documents:
            persona_sessions[doc.user_id or "default"].append(doc)
        for pid in persona_sessions:
            persona_sessions[pid].sort(key=lambda d: d.id)

        total_sessions = sum(len(ss) for ss in persona_sessions.values())
        total_personas = len(persona_sessions)
        sessions_done = 0
        total_extractions = 0
        total_failures = 0

        async with MemoryHubClient(url=self._url, api_key=self._api_key) as client:
            try:
                await client.create_project(
                    self._project_id,
                    description="AMB benchmark memory isolation (dreaming mode)",
                )
                logger.info("Created project %s", self._project_id)
            except Exception:
                logger.debug("Project %s already exists", self._project_id)

            for p_idx, (persona_id, sessions) in enumerate(
                sorted(persona_sessions.items()), 1
            ):
                owner = f"amb-{persona_id}" if persona_id else "amb-default"
                thread = await client.create_thread(
                    scope="project",
                    scope_id=self._project_id,
                    owner_id=owner,
                    title=f"PersonaMem {persona_id}",
                    metadata={
                        "persona_id": persona_id,
                        "benchmark": "personamem",
                        "session_count": len(sessions),
                    },
                )
                logger.info(
                    "Persona %d/%d (%s): thread %s, %d sessions",
                    p_idx, total_personas, persona_id, thread.id, len(sessions),
                )

                for s_idx, doc in enumerate(sessions, 1):
                    for msg in doc.messages or []:
                        content = msg.get("content", "")
                        if not content.strip():
                            continue
                        msg_meta: dict[str, Any] = {"session_doc_id": doc.id}
                        if doc.timestamp:
                            msg_meta["session_timestamp"] = doc.timestamp
                        await client.append_message(
                            thread.id,
                            role=msg.get("role", "user"),
                            content=content,
                            metadata=msg_meta,
                        )

                    extract_kwargs: dict[str, Any] = {}
                    if self._extraction_model:
                        extract_kwargs["model"] = self._extraction_model
                    if self._extraction_model_url:
                        extract_kwargs["model_url"] = self._extraction_model_url

                    result = await client.extract_thread(thread.id, **extract_kwargs)
                    total_extractions += result.extracted_count
                    total_failures += result.failures
                    sessions_done += 1

                    logger.info(
                        "Persona %s session %d/%d (doc %s): "
                        "extracted=%d cursor=%d failures=%d [%d/%d overall]",
                        persona_id, s_idx, len(sessions), doc.id,
                        result.extracted_count, result.cursor, result.failures,
                        sessions_done, total_sessions,
                    )

        logger.info(
            "Dreaming ingestion complete: %d personas, %d sessions, "
            "%d extracted memories, %d failures",
            total_personas, total_sessions, total_extractions, total_failures,
        )

    async def _reset_benchmark_data(self) -> None:
        """Delete previous benchmark data via raw SQL (test scaffolding)."""
        engine = create_async_engine(self._db_url, pool_size=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                mem_result = await session.execute(
                    text(
                        "DELETE FROM memory_nodes "
                        "WHERE owner_id LIKE 'amb-%' AND scope_id = :project_id"
                    ),
                    {"project_id": self._project_id},
                )
                thread_result = await session.execute(
                    text(
                        "DELETE FROM conversation_threads "
                        "WHERE owner_id LIKE 'amb-%' AND scope_id = :project_id"
                    ),
                    {"project_id": self._project_id},
                )
                recon_result = await session.execute(
                    text(
                        "DELETE FROM reconciliation_decisions "
                        "WHERE owner_id LIKE 'amb-%' AND scope_id = :project_id"
                    ),
                    {"project_id": self._project_id},
                )
                await session.commit()
                logger.info(
                    "Reset project %s: %d memories, %d threads, %d recon decisions",
                    self._project_id,
                    mem_result.rowcount, thread_result.rowcount, recon_result.rowcount,
                )
        finally:
            await engine.dispose()

    def _resolve_k(self, k: int | None) -> int:
        if k is None or k == 10:
            return int(os.environ.get("MEMORYHUB_K", "70"))
        return k

    def retrieve(
        self, query: str, k: int | None = None, user_id: str | None = None,
        query_timestamp: str | None = None,
    ) -> tuple[list[Document], dict | None]:
        return asyncio.run(self._run_retrieve(query, self._resolve_k(k), user_id, query_timestamp))

    async def async_retrieve(
        self, query: str, k: int = 10, user_id: str | None = None,
        query_timestamp: str | None = None,
    ) -> tuple[list[Document], dict | None]:
        return await asyncio.to_thread(self.retrieve, query, self._resolve_k(k), user_id, query_timestamp)

    @staticmethod
    def _extract_persona_name(query: str) -> str | None:
        """Extract persona name from "User: Name\n..." prefix."""
        if query.startswith("User: "):
            return query.split("\n", 1)[0].removeprefix("User: ").strip() or None
        return None

    async def _run_retrieve(
        self, query: str, k: int, user_id: str | None, query_timestamp: str | None,
    ) -> tuple[list[Document], dict | None]:
        owner = f"amb-{user_id}" if user_id else "amb-default"

        async with MemoryHubClient(url=self._url, api_key=self._api_key) as client:
            search_kwargs: dict[str, Any] = dict(
                query=query,
                max_results=k,
                owner_id=owner,
                project_id=self._project_id,
                weight_threshold=0.0,
                mode="full_only",
                max_response_tokens=0,
                disabled_signals=self._disabled_signals,
            )
            if self._tenant_id:
                search_kwargs["tenant_id"] = self._tenant_id
            if self._focus_mode == "persona":
                name = self._extract_persona_name(query)
                if name:
                    search_kwargs["focus"] = name
            if self._return_chunks:
                search_kwargs["return_chunks"] = True
                search_kwargs["raw_results"] = True
            results = await client.search(**search_kwargs)

        documents = []
        for memory in results.results:
            doc_id = self._memory_to_doc_id.get(memory.id, memory.id)
            documents.append(Document(
                id=doc_id,
                content=memory.content,
                user_id=user_id,
            ))

        return documents, None

    def cleanup(self) -> None:
        pass
