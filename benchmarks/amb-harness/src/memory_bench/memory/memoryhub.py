"""MemoryHub hybrid search provider for AMB benchmark."""

import asyncio
import logging
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.embeddings import HttpEmbeddingService
from memoryhub_core.services.memory import search_memories_with_focus
from memoryhub_core.services.rerank import HttpRerankerService

from ..models import Document
from .base import MemoryProvider

logger = logging.getLogger(__name__)


class MemoryHubProvider(MemoryProvider):
    name = "memoryhub"
    description = "MemoryHub hybrid search (vector + keyword + reranker + RRF)"
    kind = "cloud"
    concurrency = 1

    def __init__(self):
        self._db_url = None
        self._engine = None
        self._session_factory = None
        self._embedding_service = None
        self._reranker = None
        self._doc_to_node_id: dict[str, str] = {}
        self._node_to_doc_id: dict[str, str] = {}
        self._reset = False

    def prepare(self, store_dir: Path, unit_ids: set[str] | None = None, reset: bool = True) -> None:
        db_host = os.environ.get("MEMORYHUB_DB_HOST", "localhost")
        db_port = os.environ.get("MEMORYHUB_DB_PORT", "25432")
        db_user = os.environ.get("MEMORYHUB_DB_USER", "memoryhub")
        db_pass = os.environ.get("MEMORYHUB_DB_PASS", "d64c86093e57f4e94aa4740974e70ad3")
        db_name = os.environ.get("MEMORYHUB_DB_NAME", "memoryhub")

        self._db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        # Defer engine creation to first async call so it's bound to the right event loop

        self._embedding_url = os.environ.get(
            "MEMORYHUB_EMBEDDING_URL",
            "https://all-minilm-l6-v2-embedding-model.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/embed",
        )
        self._reranker_url = os.environ.get(
            "MEMORYHUB_RERANKER_URL",
            "https://ms-marco-minilm-l12-v2-reranker-model.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com",
        )

        self._doc_to_node_id.clear()
        self._node_to_doc_id.clear()
        self._reset = reset
        # Engine will be created lazily in _ensure_engine

    def _ensure_engine(self):
        if self._engine is None:
            self._engine = create_async_engine(self._db_url, pool_size=5, max_overflow=10)
            self._session_factory = async_sessionmaker(
                self._engine, class_=AsyncSession, expire_on_commit=False
            )
            self._embedding_service = HttpEmbeddingService(url=self._embedding_url)
            self._reranker = HttpRerankerService(url=self._reranker_url)

    def ingest(self, documents: list[Document]) -> None:
        asyncio.run(self._run_ingest(documents))

    async def _run_ingest(self, documents: list[Document]) -> None:
        self._ensure_engine()
        if self._reset:
            async with self._session_factory() as session:
                result = await session.execute(
                    text("DELETE FROM memory_nodes WHERE tenant_id LIKE 'amb-%'")
                )
                await session.commit()
                logger.info("Deleted %d AMB benchmark memories", result.rowcount)
            self._reset = False

        for doc in documents:
            tenant_id = f"amb-{doc.user_id}" if doc.user_id else "amb-default"
            embed_content = doc.content[:500]
            embedding = await self._embedding_service.embed(embed_content)

            async with self._session_factory() as session:
                node = MemoryNode(
                    tenant_id=tenant_id,
                    owner_id="amb-benchmark",
                    content=doc.content,
                    stub=doc.content[:200],
                    scope="project",
                    content_type="experiential",
                    embedding=embedding if embedding else None,
                )
                session.add(node)
                await session.flush()

                await session.commit()

                node_id = str(node.id)
                self._doc_to_node_id[doc.id] = node_id
                self._node_to_doc_id[node_id] = doc.id

        await self._engine.dispose()
        self._engine = None
        self._session_factory = None

    def retrieve(
        self, query: str, k: int = 10, user_id: str | None = None,
        query_timestamp: str | None = None,
    ) -> tuple[list[Document], dict | None]:
        return asyncio.run(self._run_retrieve(query, k, user_id, query_timestamp))

    async def _run_retrieve(
        self, query: str, k: int, user_id: str | None, query_timestamp: str | None,
    ) -> tuple[list[Document], dict | None]:
        self._ensure_engine()
        tenant_id = f"amb-{user_id}" if user_id else "amb-default"

        async with self._session_factory() as session:
            bundle = await search_memories_with_focus(
                query=query,
                session=session,
                embedding_service=self._embedding_service,
                tenant_id=tenant_id,
                focus_string=query,
                reranker=self._reranker,
                max_results=k,
                weight_threshold=0.0,
                keyword_boost_weight=0.15,
            )

        documents = []
        for node, score in bundle.results:
            doc_id = self._node_to_doc_id.get(str(node.id), str(node.id))
            documents.append(Document(id=doc_id, content=node.content, user_id=user_id))

        await self._engine.dispose()
        self._engine = None
        self._session_factory = None

        return documents, None

    def cleanup(self) -> None:
        if self._engine:
            asyncio.run(self._engine.dispose())
