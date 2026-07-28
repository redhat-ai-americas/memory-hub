"""Tests for OnnxEmbeddingService and semantic search quality."""

import math
import os
import shutil
import tempfile

import pytest

# Skip all tests if onnxruntime is not installed
ort = pytest.importorskip("onnxruntime")

from memoryhub_local.embeddings.onnx import (  # noqa: E402
    OnnxEmbeddingService,
    get_default_model_dir,
    is_model_downloaded,
)

_model_dir = get_default_model_dir()
needs_model = pytest.mark.skipif(
    not is_model_downloaded(_model_dir),
    reason="ONNX model not downloaded",
)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0


@needs_model
class TestOnnxEmbeddingService:
    @pytest.fixture
    def svc(self):
        return OnnxEmbeddingService(_model_dir)

    async def test_embed_returns_384_dims(self, svc):
        vec = await svc.embed("hello world")
        assert len(vec) == 384

    async def test_embed_is_normalized(self, svc):
        vec = await svc.embed("test normalization")
        magnitude = math.sqrt(sum(x * x for x in vec))
        assert abs(magnitude - 1.0) < 0.01

    async def test_batch_embed(self, svc):
        vecs = await svc.embed_batch(["hello", "world"])
        assert len(vecs) == 2
        assert all(len(v) == 384 for v in vecs)

    async def test_empty_batch(self, svc):
        vecs = await svc.embed_batch([])
        assert vecs == []

    async def test_semantic_similarity(self, svc):
        """Cat/kitten should be more similar than cat/database."""
        e_cat = await svc.embed("The cat sat on the mat")
        e_kitten = await svc.embed("A kitten was lying on the rug")
        e_db = await svc.embed("PostgreSQL database optimization techniques")

        sim_cat_kitten = _cosine(e_cat, e_kitten)
        sim_cat_db = _cosine(e_cat, e_db)

        assert sim_cat_kitten > sim_cat_db, (
            f"cat-kitten ({sim_cat_kitten:.3f}) should be > "
            f"cat-database ({sim_cat_db:.3f})"
        )


@needs_model
class TestSemanticSearch:
    async def test_search_ranks_by_relevance(self):
        """Write cheese and DB memories, search for cheese, verify ranking."""
        tmpdir = tempfile.mkdtemp()
        prev_xdg = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = tmpdir

        try:
            from memoryhub_local.database import (
                auto_migrate,
                create_local_engine,
                make_session_factory,
            )
            from memoryhub_local.storage.sqlite import SQLiteBackend
            from memoryhub_local.tools._state import init_state
            from memoryhub_local.tools.memory import memory
            from memoryhub_local.tools.register_session import register_session

            engine = await create_local_engine()
            await auto_migrate(engine)
            sf = make_session_factory(engine)

            svc = OnnxEmbeddingService(_model_dir)
            init_state(sf, svc, SQLiteBackend())

            await register_session(ctx=None)
            await memory(action="write", content="Parmesan is an aged Italian hard cheese")
            await memory(action="write", content="PostgreSQL supports JSONB columns")
            await memory(action="write", content="Gouda is a Dutch cheese with creamy texture")

            results = await memory(action="search", query="What cheese should I try?")
            result_list = results.get("results", [])

            assert len(result_list) >= 2
            # Both cheese memories should score higher than the DB memory
            cheese = [r for r in result_list if "cheese" in r.get("content", "").lower()]
            db = [r for r in result_list if "PostgreSQL" in r.get("content", "")]
            assert len(cheese) == 2
            assert len(db) == 1
            assert min(r["relevance_score"] for r in cheese) > db[0]["relevance_score"]
        finally:
            if prev_xdg is not None:
                os.environ["XDG_DATA_HOME"] = prev_xdg
            else:
                os.environ.pop("XDG_DATA_HOME", None)
            shutil.rmtree(tmpdir, ignore_errors=True)
