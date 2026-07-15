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

        self._doc_to_memory_id.clear()
        self._memory_to_doc_id.clear()
        self._reset = reset

    def ingest(self, documents: list[Document]) -> None:
        asyncio.run(self._run_ingest(documents))

    async def _run_ingest(self, documents: list[Document]) -> None:
        if self._reset:
            await self._reset_benchmark_data()
            self._reset = False

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

    async def _reset_benchmark_data(self) -> None:
        """Delete previous benchmark data via raw SQL (test scaffolding)."""
        engine = create_async_engine(self._db_url, pool_size=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                result = await session.execute(
                    text("DELETE FROM memory_nodes WHERE owner_id LIKE 'amb-%'")
                )
                await session.commit()
                logger.info("Deleted %d AMB benchmark memories", result.rowcount)
        finally:
            await engine.dispose()

    def retrieve(
        self, query: str, k: int = 70, user_id: str | None = None,
        query_timestamp: str | None = None,
    ) -> tuple[list[Document], dict | None]:
        return asyncio.run(self._run_retrieve(query, k, user_id, query_timestamp))

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
