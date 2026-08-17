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

check_retrieval_caps = _mod.check_retrieval_caps
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
    "retrieval": {
        "requested_k": 10,
        "effective_k": 10,
        "caps": [],
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


# ---------------------------------------------------------------------------
# check_retrieval_caps
# ---------------------------------------------------------------------------


class TestCheckRetrievalCaps:
    def test_no_caps_applied(self):
        result = check_retrieval_caps(10)
        assert result["requested_k"] == 10
        assert result["effective_k"] == 10
        assert result["caps"] == []

    def test_harness_cap(self):
        result = check_retrieval_caps(70, harness_k=50)
        assert result["requested_k"] == 70
        assert result["effective_k"] == 50
        assert len(result["caps"]) == 1
        assert result["caps"][0]["source"] == "harness"

    def test_sdk_cap(self):
        result = check_retrieval_caps(70, sdk_max_results=50)
        assert result["requested_k"] == 70
        assert result["effective_k"] == 50
        assert len(result["caps"]) == 1
        assert result["caps"][0]["source"] == "sdk_config"

    def test_tool_cap(self):
        result = check_retrieval_caps(300, tool_max_results=200)
        assert result["requested_k"] == 300
        assert result["effective_k"] == 200
        assert len(result["caps"]) == 1
        assert result["caps"][0]["source"] == "mcp_tool_param"

    def test_multiple_caps_lowest_wins(self):
        result = check_retrieval_caps(
            70, harness_k=50, sdk_max_results=30, tool_max_results=200
        )
        assert result["requested_k"] == 70
        assert result["effective_k"] == 30
        assert len(result["caps"]) == 2

    def test_default_requested_k(self):
        result = check_retrieval_caps(None)
        assert result["requested_k"] == 10
        assert result["effective_k"] == 10

    def test_explicit_zero_not_replaced_with_default(self):
        """Regression: requested_k=0 must not be swallowed by `or 10`."""
        result = check_retrieval_caps(0)
        assert result["requested_k"] == 0
        assert result["effective_k"] == 0
        assert result["caps"] == []

    def test_deliberate_cap_k70_cap10(self):
        """Issue #404: k=70 with cap=10 should clearly show the discrepancy."""
        result = check_retrieval_caps(70, harness_k=10)
        assert result["requested_k"] == 70
        assert result["effective_k"] == 10
        assert result["caps"][0]["source"] == "harness"
        assert result["caps"][0]["limit"] == 10

        # Verify this shows up as a mismatch in manifest enforcement
        # when the expected manifest assumes no cap was applied.
        manifest_with_cap = {**SAMPLE_MANIFEST, "retrieval": result}
        expected_no_cap = {
            "retrieval": {"effective_k": 70}
        }
        ok, diff = enforce_manifest(manifest_with_cap, expected_no_cap)
        assert ok is False
        assert "retrieval.effective_k" in diff
        assert "70" in diff
        assert "10" in diff


# ---------------------------------------------------------------------------
# main() wiring
# ---------------------------------------------------------------------------

main = _mod.main
run_preflight = _mod.run_preflight


class TestMainWiring:
    """Verify main() passes the right values to run_preflight."""

    def _run_main(self, monkeypatch, env_overrides=None):
        """Helper: run main() with mocked run_preflight, return captured kwargs."""
        env = {
            "MEMORYHUB_DB_HOST": "localhost",
            "MEMORYHUB_DB_PORT": "5432",
            "MEMORYHUB_DB_USER": "test",
            "MEMORYHUB_DB_PASS": "test",
            "MEMORYHUB_DB_NAME": "test",
        }
        if env_overrides:
            env.update(env_overrides)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("MEMORYHUB_RERANKER_URL", raising=False)
        monkeypatch.delenv("MEMORYHUB_TENANT_ID", raising=False)
        monkeypatch.setattr("sys.argv", ["preflight"])

        captured = {}

        async def fake_run_preflight(db_url, **kwargs):
            captured.update(kwargs)
            return {
                "signals": {},
                "retrieval": check_retrieval_caps(
                    kwargs.get("requested_k"),
                    sdk_max_results=kwargs.get("sdk_max_results"),
                ),
                "corpus": {},
                "versions": {},
                "timestamp": "",
            }

        monkeypatch.setattr(_mod, "run_preflight", fake_run_preflight)
        main()
        return captured

    def test_memoryhub_k_becomes_requested_k(self, monkeypatch):
        """MEMORYHUB_K should flow to requested_k, not harness_k."""
        captured = self._run_main(monkeypatch, {"MEMORYHUB_K": "70"})
        assert captured["requested_k"] == 70
        assert captured.get("harness_k") is None

    def test_no_memoryhub_k_yields_none(self, monkeypatch):
        monkeypatch.delenv("MEMORYHUB_K", raising=False)
        captured = self._run_main(monkeypatch)
        assert captured["requested_k"] is None

    def test_sdk_max_results_not_passed_without_sdk(self, monkeypatch):
        """When memoryhub SDK is not importable, sdk_max_results should be None."""
        monkeypatch.delenv("MEMORYHUB_K", raising=False)
        captured = self._run_main(monkeypatch)
        assert captured.get("sdk_max_results") is None

    def test_harness_k_not_duplicated_from_memoryhub_k(self, monkeypatch):
        """Regression: main() must not pass the same MEMORYHUB_K as both
        requested_k and harness_k — the harness overrides UP, not caps DOWN."""
        captured = self._run_main(monkeypatch, {"MEMORYHUB_K": "70"})
        assert captured["requested_k"] == 70
        assert captured.get("harness_k") is None

    def test_memoryhub_k_zero_is_preserved(self, monkeypatch):
        """Explicit MEMORYHUB_K=0 must reach requested_k as 0, not become None/10."""
        captured = self._run_main(monkeypatch, {"MEMORYHUB_K": "0"})
        assert captured["requested_k"] == 0
        assert captured.get("harness_k") is None
