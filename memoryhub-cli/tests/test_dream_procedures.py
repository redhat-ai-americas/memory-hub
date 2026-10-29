"""``memoryhub dream --procedures`` (#554): the local procedural pass."""

from __future__ import annotations

import asyncio
import contextlib
import re
import sys
import types

import pytest
from typer.testing import CliRunner

from memoryhub_cli import main
from memoryhub_cli.main import OutputFormat, app

runner = CliRunner()


def test_dream_help_lists_procedures_flag():
    result = runner.invoke(app, ["dream", "--help"])
    assert result.exit_code == 0
    # On CI Rich forces colour and styles the two dashes separately.
    assert "--procedures" in re.sub(r"\x1b\[[0-9;]*m", "", result.output)


@pytest.fixture
def fake_local(monkeypatch):
    """A stand-in for memoryhub_local.services.procedure_extraction."""
    calls: dict = {"threads": []}
    module = types.ModuleType("memoryhub_local.services.procedure_extraction")

    async def get_procedural_pending_threads(session):
        return [{"id": "11111111-aaaa", "title": "a"}, {"id": "22222222-bbbb", "title": "b"}]

    async def extract_procedures_from_thread(session, tid, **kwargs):
        calls["threads"].append(tid)
        calls["kwargs"] = kwargs
        if tid.startswith("2"):
            raise RuntimeError("boom")
        return {"created": 1, "matched": 0, "rejections": [{"reason": "duplicate"}]}

    def make_http_complete_fn(model, url, api_key):
        calls["llm"] = (model, url, api_key)
        return object()

    module.get_procedural_pending_threads = get_procedural_pending_threads
    module.extract_procedures_from_thread = extract_procedures_from_thread
    module.make_http_complete_fn = make_http_complete_fn
    for name in ("memoryhub_local", "memoryhub_local.services"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return calls


class _State:
    embedding_service = object()
    recall_backend = object()

    @contextlib.asynccontextmanager
    async def _session(self):
        yield object()

    def session_factory(self):
        return self._session()


def test_procedural_pass_reports_per_thread_and_never_raises(fake_local):
    summary = asyncio.run(main._run_procedural_pass(
        _State(), "llama3.2", "http://localhost:11434/v1", None, None, OutputFormat.json,
    ))
    assert fake_local["threads"] == ["11111111-aaaa", "22222222-bbbb"]
    assert fake_local["llm"] == ("llama3.2", "http://localhost:11434/v1", None)
    assert fake_local["kwargs"]["extraction_model"] == "llama3.2"
    assert summary["created"] == 1 and summary["rejected"] == 1 and summary["errors"] == 1
    assert summary["results"][1]["error"] == "boom"


def test_procedural_pass_honours_explicit_thread(fake_local):
    asyncio.run(main._run_procedural_pass(
        _State(), "m", "http://x", None, "11111111-aaaa", OutputFormat.json,
    ))
    assert fake_local["threads"] == ["11111111-aaaa"]
