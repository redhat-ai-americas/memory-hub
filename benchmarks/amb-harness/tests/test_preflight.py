from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from rich.console import Console

from memory_bench.models import Query
from memory_bench.preflight import (
    PreflightResult,
    _probe_extraction_model,
    run_preflight,
)


class FakeMemory:
    source = "agent"
    content = "some content"


def _make_queries(n: int = 5) -> list[Query]:
    return [
        Query(
            id=f"q-{i:03d}",
            query=f"test query {i}",
            gold_ids=[],
            gold_answers=[],
            user_id="persona-1",
        )
        for i in range(n)
    ]


def _make_memory(
    *,
    ingestion_mode: str = "library",
    extraction_model: str | None = None,
    extraction_model_url: str | None = None,
    search_results: list | None = None,
) -> MagicMock:
    mem = MagicMock()
    mem._project_id = "amb-benchmark"
    mem._tenant_id = None
    mem._source_filter = None
    mem._exclude_source = None
    mem._focus_mode = None
    mem._retrieval_unit = None
    mem._ingestion_mode = ingestion_mode
    mem._extraction_model = extraction_model
    mem._extraction_model_url = extraction_model_url
    results = search_results if search_results is not None else [FakeMemory()]
    mem.preflight_search = AsyncMock(return_value=results)
    return mem


async def test_probe_passes_when_no_model_configured():
    ok, detail = await _probe_extraction_model(None, None)
    assert ok is True
    assert "server default" in detail


def _patched_genai(*, side_effect=None):
    mock_genai = MagicMock()
    if side_effect:
        mock_genai.Client.return_value.models.get.side_effect = side_effect
    else:
        mock_genai.Client.return_value.models.get.return_value = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    return patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai})


async def test_probe_passes_for_valid_gemini_model():
    with _patched_genai():
        ok, detail = await _probe_extraction_model("gemini-2.0-flash", None)
    assert ok is True
    assert "verified" in detail


async def test_probe_passes_for_valid_gemini_model_via_url():
    with _patched_genai():
        ok, detail = await _probe_extraction_model(
            "gemini-2.0-flash",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        )
    assert ok is True
    assert "verified" in detail


async def test_probe_fails_for_deprecated_gemini_model():
    with _patched_genai(side_effect=Exception("model not found")):
        ok, detail = await _probe_extraction_model("gemini-1.0-pro-deprecated", None)
    assert ok is False
    assert "not found" in detail


async def test_probe_passes_for_reachable_custom_url():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("memory_bench.preflight.httpx.AsyncClient", return_value=mock_client):
        ok, detail = await _probe_extraction_model(
            "custom-model", "https://custom.example.com/v1"
        )
    assert ok is True
    assert "reachable" in detail


async def test_probe_fails_for_unreachable_custom_url():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("memory_bench.preflight.httpx.AsyncClient", return_value=mock_client):
        ok, detail = await _probe_extraction_model(
            "custom-model", "https://custom.example.com/v1"
        )
    assert ok is False
    assert "unreachable" in detail


async def test_preflight_aborts_on_failed_probe():
    mem = _make_memory(ingestion_mode="dreaming", extraction_model="bad-model")
    queries = _make_queries()
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)

    with patch(
        "memory_bench.preflight._probe_extraction_model",
        return_value=(False, "model deprecated"),
    ):
        result = await run_preflight(mem, queries, None, console=console)

    assert result.aborted is True
    assert "probe failed" in result.abort_reason


async def test_preflight_continues_on_passed_probe():
    mem = _make_memory(ingestion_mode="dreaming", extraction_model="gemini-2.0-flash")
    queries = _make_queries()
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)

    with patch(
        "memory_bench.preflight._probe_extraction_model",
        return_value=(True, "verified"),
    ):
        result = await run_preflight(mem, queries, None, console=console)

    assert result.aborted is False
    assert result.passed is True


async def test_config_shows_extraction_model_in_dreaming_mode():
    mem = _make_memory(
        ingestion_mode="dreaming",
        extraction_model="gemini-2.0-flash",
        extraction_model_url="https://generativelanguage.googleapis.com/v1beta/openai",
    )
    queries = _make_queries()
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)

    with patch(
        "memory_bench.preflight._probe_extraction_model",
        return_value=(True, "verified"),
    ):
        await run_preflight(mem, queries, None, console=console)

    output = buf.getvalue()
    assert "extract model:" in output
    assert "gemini-2.0-flash" in output
    assert "extract URL:" in output


async def test_config_omits_extraction_in_library_mode():
    mem = _make_memory(ingestion_mode="library")
    queries = _make_queries()
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)

    await run_preflight(mem, queries, None, console=console)

    output = buf.getvalue()
    assert "extract model:" not in output


async def test_existing_smoke_logic_unchanged():
    mem = _make_memory(ingestion_mode="library")
    queries = _make_queries()
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)

    result = await run_preflight(mem, queries, None, console=console)

    assert result.passed is True
    assert result.aborted is False
    assert len(result.smoke_results) == 3
