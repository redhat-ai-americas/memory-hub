"""Tests for turn-level hook commands (rebias, extract) and settings registration."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from memoryhub.extraction.models import CandidateMemory, ExtractionResult, TraceEvent
from memoryhub.models import Memory, SearchResult
from typer.testing import CliRunner

from memoryhub_cli.main import app

runner = CliRunner()


# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_MEMORY = Memory(
    id="aaaa-bbbb-cccc-dddd",
    content="Use Podman, not Docker",
    scope="user",
    weight=0.8,
    version=1,
    content_type="knowledge",
    owner_id="test-user",
)

SAMPLE_MEMORY_2 = Memory(
    id="eeee-ffff-gggg-hhhh",
    content="FIPS compliance required",
    scope="user",
    weight=0.9,
    version=1,
    content_type="knowledge",
    owner_id="test-user",
)

SAMPLE_SEARCH_RESULT = SearchResult(
    results=[SAMPLE_MEMORY, SAMPLE_MEMORY_2],
    total_matching=2,
)

EMPTY_SEARCH_RESULT = SearchResult(results=[], total_matching=0)


def _extraction_result(written=None, filtered=None):
    event = TraceEvent.assistant_message(content="test response")
    return ExtractionResult(
        event=event,
        candidates=[],
        written=written or [],
        reviewed=[],
        filtered=filtered or [],
    )


def _mock_client(**overrides):
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


# ── rebias ───────────────────────────────────────────────────────────────────


class TestRebias:
    def test_argument_input(self):
        mock_client = _mock_client(search=AsyncMock(return_value=SAMPLE_SEARCH_RESULT))
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["rebias", "what is the build tool?"])

        assert result.exit_code == 0
        assert "Use Podman, not Docker" in result.output
        assert "FIPS compliance required" in result.output

    def test_json_stdin(self):
        payload = json.dumps({"prompt": "how do we deploy?"})
        mock_client = _mock_client(search=AsyncMock(return_value=SAMPLE_SEARCH_RESULT))
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["rebias"], input=payload)

        assert result.exit_code == 0
        assert "Use Podman, not Docker" in result.output

    def test_plain_text_stdin(self):
        mock_client = _mock_client(search=AsyncMock(return_value=SAMPLE_SEARCH_RESULT))
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["rebias"], input="plain text query")

        assert result.exit_code == 0
        assert "Use Podman, not Docker" in result.output

    def test_json_output(self):
        mock_client = _mock_client(search=AsyncMock(return_value=SAMPLE_SEARCH_RESULT))
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["rebias", "query", "--output", "json"],
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"

    def test_no_results_exits_zero(self):
        mock_client = _mock_client(search=AsyncMock(return_value=EMPTY_SEARCH_RESULT))
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["rebias", "obscure query"])

        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_empty_stdin_exits_zero(self):
        result = runner.invoke(app, ["rebias"], input="")
        assert result.exit_code == 0

    def test_client_error_exits_zero(self):
        with patch("memoryhub_cli.main._get_client", side_effect=SystemExit(1)):
            result = runner.invoke(app, ["rebias", "query"])

        assert result.exit_code == 0

    def test_connection_error_exits_zero(self):
        mock_client = _mock_client(search=AsyncMock(side_effect=ConnectionError("unreachable")))
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["rebias", "query"])

        assert result.exit_code == 0

    def test_max_results_forwarded(self):
        mock_search = AsyncMock(return_value=SAMPLE_SEARCH_RESULT)
        mock_client = _mock_client(search=mock_search)
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            runner.invoke(app, ["rebias", "query", "--max", "5"])

        mock_search.assert_awaited_once()
        _, kwargs = mock_search.call_args
        assert kwargs["max_results"] == 5

    def test_project_id_option(self):
        mock_search = AsyncMock(return_value=SAMPLE_SEARCH_RESULT)
        mock_client = _mock_client(search=mock_search)
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            runner.invoke(app, ["rebias", "query", "--project-id", "my-proj"])

        _, kwargs = mock_search.call_args
        assert kwargs["project_id"] == "my-proj"

    def test_compact_output_wraps_in_xml(self):
        mock_client = _mock_client(search=AsyncMock(return_value=SAMPLE_SEARCH_RESULT))
        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["rebias", "query", "--output", "compact"],
            )

        assert "<memoryhub-context" in result.output
        assert "</memoryhub-context>" in result.output


# ── extract ──────────────────────────────────────────────────────────────────


class TestExtract:
    def test_argument_input(self):
        ext_result = _extraction_result(written=["mem-1"])
        mock_client = _mock_client()
        with (
            patch("memoryhub_cli.main._get_client", return_value=mock_client),
            patch("memoryhub.extraction.pipeline.ExtractionPipeline.observe",
                  new_callable=AsyncMock, return_value=ext_result),
        ):
            result = runner.invoke(
                app,
                ["extract", "This is a long enough response to pass the minimum length check for extraction."],
            )

        assert result.exit_code == 0

    def test_json_stdin(self):
        payload = json.dumps({
            "last_assistant_message": "The project uses PostgreSQL with pgvector for search.",
        })
        ext_result = _extraction_result(written=["mem-1"])
        mock_client = _mock_client()
        with (
            patch("memoryhub_cli.main._get_client", return_value=mock_client),
            patch("memoryhub.extraction.pipeline.ExtractionPipeline.observe",
                  new_callable=AsyncMock, return_value=ext_result),
        ):
            result = runner.invoke(app, ["extract"], input=payload)

        assert result.exit_code == 0

    def test_plain_text_stdin(self):
        ext_result = _extraction_result(written=["mem-1"])
        mock_client = _mock_client()
        with (
            patch("memoryhub_cli.main._get_client", return_value=mock_client),
            patch("memoryhub.extraction.pipeline.ExtractionPipeline.observe",
                  new_callable=AsyncMock, return_value=ext_result),
        ):
            result = runner.invoke(
                app, ["extract"],
                input="The project uses PostgreSQL with pgvector for vector search operations.",
            )

        assert result.exit_code == 0

    def test_json_output(self):
        ext_result = _extraction_result(written=["mem-1", "mem-2"], filtered=[
            CandidateMemory(
                content="dup",
                scope="user",
                confidence=0.9,
                extractor_name="PreferenceExtractor",
                source_event=TraceEvent.assistant_message(content="x"),
                duplicate_of="existing-1",
            ),
        ])
        mock_client = _mock_client()
        with (
            patch("memoryhub_cli.main._get_client", return_value=mock_client),
            patch("memoryhub.extraction.pipeline.ExtractionPipeline.observe",
                  new_callable=AsyncMock, return_value=ext_result),
        ):
            result = runner.invoke(
                app,
                ["extract", "--output", "json",
                 "Long enough response text to pass the twenty character minimum threshold for processing."],
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["written"] == ["mem-1", "mem-2"]
        assert parsed["data"]["filtered"] == 1

    def test_short_response_exits_zero(self):
        result = runner.invoke(app, ["extract", "too short"])
        assert result.exit_code == 0

    def test_empty_stdin_exits_zero(self):
        result = runner.invoke(app, ["extract"], input="")
        assert result.exit_code == 0

    def test_client_error_exits_zero(self):
        with patch("memoryhub_cli.main._get_client", side_effect=SystemExit(1)):
            result = runner.invoke(
                app,
                ["extract", "Long enough response to pass the minimum length check for extraction pipeline."],
            )

        assert result.exit_code == 0

    def test_pipeline_error_exits_zero(self):
        mock_client = _mock_client()
        with (
            patch("memoryhub_cli.main._get_client", return_value=mock_client),
            patch("memoryhub.extraction.pipeline.ExtractionPipeline.observe",
                  new_callable=AsyncMock, side_effect=RuntimeError("extraction failed")),
        ):
            result = runner.invoke(
                app,
                ["extract", "Long enough response to pass the minimum length check for extraction pipeline."],
            )

        assert result.exit_code == 0

    def test_session_id_forwarded(self):
        ext_result = _extraction_result(written=["mem-1"])
        mock_client = _mock_client()
        with (
            patch("memoryhub_cli.main._get_client", return_value=mock_client),
            patch("memoryhub.extraction.pipeline.ExtractionPipeline.observe",
                  new_callable=AsyncMock, return_value=ext_result) as mock_observe,
        ):
            runner.invoke(
                app,
                ["extract", "--session-id", "sess-123",
                 "Long enough response to pass the twenty character minimum threshold for processing."],
            )

        event = mock_observe.call_args[0][0]
        assert event.metadata["session_id"] == "sess-123"

    def test_quiet_output_default(self):
        result = runner.invoke(app, ["extract", "--help"])
        assert result.exit_code == 0
        assert "quiet" in result.output


# ── merge_settings_hooks turn-level entries ──────────────────────────────────


class TestMergeSettingsHooksTurnLevel:
    def test_creates_user_prompt_submit_entry(self, tmp_path):
        from memoryhub_cli.project_config import merge_settings_hooks

        settings_path = merge_settings_hooks(tmp_path)
        data = json.loads(settings_path.read_text())

        assert "UserPromptSubmit" in data["hooks"]
        entries = data["hooks"]["UserPromptSubmit"]
        assert len(entries) == 1
        assert "rebias-memories.sh" in entries[0]["hooks"][0]["command"]
        assert entries[0]["hooks"][0]["timeout"] == 3

    def test_creates_stop_entry(self, tmp_path):
        from memoryhub_cli.project_config import merge_settings_hooks

        settings_path = merge_settings_hooks(tmp_path)
        data = json.loads(settings_path.read_text())

        assert "Stop" in data["hooks"]
        entries = data["hooks"]["Stop"]
        assert len(entries) == 1
        assert "extract-memories.sh" in entries[0]["hooks"][0]["command"]
        assert entries[0]["hooks"][0]["timeout"] == 5

    def test_turn_level_hooks_idempotent(self, tmp_path):
        from memoryhub_cli.project_config import merge_settings_hooks

        merge_settings_hooks(tmp_path)
        first = (tmp_path / ".claude" / "settings.json").read_text()

        merge_settings_hooks(tmp_path)
        second = (tmp_path / ".claude" / "settings.json").read_text()

        assert first == second

    def test_preserves_existing_stop_hooks(self, tmp_path):
        from memoryhub_cli.project_config import merge_settings_hooks

        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir(parents=True)
        (settings_dir / "settings.json").write_text(json.dumps({
            "hooks": {
                "Stop": [{"matcher": "lint", "hooks": [{"type": "command", "command": "lint.sh"}]}],
            },
        }))

        settings_path = merge_settings_hooks(tmp_path)
        data = json.loads(settings_path.read_text())

        stop_entries = data["hooks"]["Stop"]
        assert len(stop_entries) == 2
        commands = [e["hooks"][0]["command"] for e in stop_entries]
        assert "lint.sh" in commands
        assert any("extract-memories.sh" in c for c in commands)
