"""Tests for the preflight manifest module.

Imports bypass the package __init__.py to avoid pulling in the EvalHub SDK
dependency chain (oras, olot, etc.) which is only needed at runtime.
"""

import importlib
import sys
from pathlib import Path

import pytest

# Direct import of the preflight module without triggering __init__.py
_src = Path(__file__).resolve().parent.parent / "src"
_spec = importlib.util.spec_from_file_location(
    "memoryhub_evalhub.preflight",
    _src / "memoryhub_evalhub" / "preflight.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_mod.__name__] = _mod
_spec.loader.exec_module(_mod)

check_signal_focus = _mod.check_signal_focus
check_signal_reranker = _mod.check_signal_reranker
enforce_manifest = _mod.enforce_manifest
get_version_shas = _mod.get_version_shas


# ---------------------------------------------------------------------------
# Sample manifest for reuse across tests
# ---------------------------------------------------------------------------

SAMPLE_MANIFEST = {
    "signals": {
        "vector": {"active": True, "node_count": 1024},
        "reranker": {"active": False, "reason": "MEMORYHUB_RERANKER_URL not set"},
        "keyword": {
            "active": True,
            "column_exists": True,
            "index_exists": True,
            "populated_count": 900,
        },
        "focus": {"active": False, "reason": "benchmark does not call set_focus"},
        "domain": {"active": True, "tagged_count": 500},
        "graph": {"active": False, "edge_count": 0},
    },
    "corpus": {
        "tenant_id": "amb-benchmark",
        "total_nodes": 1024,
        "parent_nodes": 128,
        "chunk_nodes": 896,
    },
    "versions": {"pipeline_sha": "abc123"},
    "timestamp": "2026-07-14T00:00:00+00:00",
}


# ---------------------------------------------------------------------------
# enforce_manifest tests
# ---------------------------------------------------------------------------


class TestEnforceManifest:
    def test_exact_match(self):
        ok, diff = enforce_manifest(SAMPLE_MANIFEST, SAMPLE_MANIFEST)
        assert ok is True
        assert diff == ""

    def test_subset_match(self):
        expected = {"signals": {"vector": {"active": True}}}
        ok, diff = enforce_manifest(SAMPLE_MANIFEST, expected)
        assert ok is True
        assert diff == ""

    def test_extra_keys_ignored(self):
        actual = {**SAMPLE_MANIFEST, "extra_top": "ignored"}
        ok, diff = enforce_manifest(actual, SAMPLE_MANIFEST)
        assert ok is True
        assert diff == ""

    def test_mismatch_boolean(self):
        expected = {"signals": {"reranker": {"active": True}}}
        ok, diff = enforce_manifest(SAMPLE_MANIFEST, expected)
        assert ok is False
        assert "signals.reranker.active" in diff

    def test_mismatch_integer(self):
        expected = {"corpus": {"chunk_nodes": 100}}
        ok, diff = enforce_manifest(SAMPLE_MANIFEST, expected)
        assert ok is False
        assert "corpus.chunk_nodes" in diff
        assert "100" in diff

    def test_missing_key(self):
        expected = {"signals": {"reranker": {"model": "bge-reranker"}}}
        ok, diff = enforce_manifest(SAMPLE_MANIFEST, expected)
        assert ok is False
        assert "signals.reranker.model" in diff
        assert "missing" in diff.lower()

    def test_nested_mismatch(self):
        expected = {
            "signals": {
                "keyword": {
                    "active": True,
                    "populated_count": 9999,
                }
            }
        }
        ok, diff = enforce_manifest(SAMPLE_MANIFEST, expected)
        assert ok is False
        assert "signals.keyword.populated_count" in diff
        # active should still match, so only populated_count appears
        assert "signals.keyword.active" not in diff

    def test_empty_expected(self):
        ok, diff = enforce_manifest(SAMPLE_MANIFEST, {})
        assert ok is True
        assert diff == ""

    def test_mismatch_string(self):
        expected = {"corpus": {"tenant_id": "other-tenant"}}
        ok, diff = enforce_manifest(SAMPLE_MANIFEST, expected)
        assert ok is False
        assert "corpus.tenant_id" in diff
        assert "other-tenant" in diff


# ---------------------------------------------------------------------------
# check_signal_focus
# ---------------------------------------------------------------------------


class TestCheckSignalFocus:
    def test_focus_always_inactive(self):
        result = check_signal_focus()
        assert result["active"] is False
        assert "reason" in result


# ---------------------------------------------------------------------------
# get_version_shas
# ---------------------------------------------------------------------------


class TestGetVersionShas:
    def test_version_shas_returns_dict(self):
        result = get_version_shas()
        assert isinstance(result, dict)
        assert "pipeline_sha" in result
        # In a git repo the SHA should be a hex string; if git isn't
        # available it falls back to "unknown".
        sha = result["pipeline_sha"]
        assert sha == "unknown" or len(sha) == 40


# ---------------------------------------------------------------------------
# check_signal_reranker (no-db cases)
# ---------------------------------------------------------------------------


class TestCheckSignalReranker:
    @pytest.mark.asyncio
    async def test_reranker_no_url(self):
        result = await check_signal_reranker(None)
        assert result["active"] is False
        assert "not set" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_reranker_empty_url(self):
        result = await check_signal_reranker("")
        assert result["active"] is False

    @pytest.mark.asyncio
    async def test_reranker_unreachable(self):
        # Use a URL that will definitely fail to connect
        result = await check_signal_reranker("http://192.0.2.1:1")
        assert result["active"] is False
        assert result["url"] == "http://192.0.2.1:1"
        assert "reason" in result
