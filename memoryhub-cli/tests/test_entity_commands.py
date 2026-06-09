"""Tests for CLI entity management commands: list, merge, rename."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from memoryhub.exceptions import NotFoundError, ValidationError
from memoryhub.models import ListEntitiesResult, EntityInfo, MergeEntitiesResult, RenameEntityResult
from memoryhub_cli.main import app

runner = CliRunner()

# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_ENTITIES = ListEntitiesResult(
    entities=[
        EntityInfo(
            id="ent-001",
            content="OpenShift",
            entity_type="object",
            aliases=["OCP"],
            mentions_count=12,
        ),
        EntityInfo(
            id="ent-002",
            content="Kubernetes",
            entity_type="object",
            aliases=["K8s", "k8s"],
            mentions_count=8,
        ),
    ],
    total=2,
    limit=50,
    offset=0,
    has_more=False,
)

SAMPLE_EMPTY = ListEntitiesResult(
    entities=[],
    total=0,
    limit=50,
    offset=0,
    has_more=False,
)

SAMPLE_MERGE = MergeEntitiesResult(
    surviving_entity={
        "id": "ent-002",
        "content": "Kubernetes",
        "aliases": ["K8s", "k8s"],
    },
    reassigned_mentions=5,
    skipped_duplicates=1,
    source_deleted="ent-001",
    message="Merged 'K8s' into 'Kubernetes'",
)

SAMPLE_RENAME = RenameEntityResult(
    entity={
        "id": "ent-001",
        "content": "Red Hat OpenShift",
        "entity_type": "object",
        "aliases": ["OpenShift"],
        "content_hash": "abc123",
    },
    old_name="OpenShift",
    message="Renamed entity from 'OpenShift' to 'Red Hat OpenShift'",
)


def _mock_client(**overrides):
    """Build a mock MemoryHubClient with async context manager support."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


# ── entity list ─────────────────────────────────────────────────────────────


class TestEntityList:
    def test_happy_path(self):
        mock_client = _mock_client(list_entities=AsyncMock(return_value=SAMPLE_ENTITIES))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["entity", "list"])

        assert result.exit_code == 0
        assert "OpenShift" in result.output
        assert "Kubernetes" in result.output
        assert "12" in result.output

    def test_json_output(self):
        mock_client = _mock_client(list_entities=AsyncMock(return_value=SAMPLE_ENTITIES))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["entity", "list", "--output", "json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert len(parsed["data"]["entities"]) == 2
        assert parsed["data"]["total"] == 2

    def test_with_type_filter(self):
        mock_list = AsyncMock(return_value=SAMPLE_ENTITIES)
        mock_client = _mock_client(list_entities=mock_list)

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["entity", "list", "--type", "person"])

        assert result.exit_code == 0
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args[1]
        assert call_kwargs["entity_type"] == "person"

    def test_empty_results(self):
        mock_client = _mock_client(list_entities=AsyncMock(return_value=SAMPLE_EMPTY))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["entity", "list"])

        assert result.exit_code == 0
        assert "No entities found" in result.output


# ── entity merge ────────────────────────────────────────────────────────────


class TestEntityMerge:
    def test_happy_path(self):
        mock_client = _mock_client(merge_entities=AsyncMock(return_value=SAMPLE_MERGE))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["entity", "merge", "ent-001", "ent-002"])

        assert result.exit_code == 0
        assert "Merged" in result.output
        assert "Kubernetes" in result.output
        assert "5" in result.output

    def test_json_output(self):
        mock_client = _mock_client(merge_entities=AsyncMock(return_value=SAMPLE_MERGE))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["entity", "merge", "ent-001", "ent-002", "--output", "json"]
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["reassigned_mentions"] == 5
        assert parsed["data"]["source_deleted"] == "ent-001"

    def test_not_found(self):
        mock_merge = AsyncMock(
            side_effect=NotFoundError("ent-999", "Entity not found")
        )
        mock_client = _mock_client(merge_entities=mock_merge)

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["entity", "merge", "ent-999", "ent-002"])

        assert result.exit_code == 1
        assert "not_found" in result.output or "not found" in result.output.lower()


# ── entity rename ───────────────────────────────────────────────────────────


class TestEntityRename:
    def test_happy_path(self):
        mock_client = _mock_client(rename_entity=AsyncMock(return_value=SAMPLE_RENAME))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["entity", "rename", "ent-001", "Red Hat OpenShift"]
            )

        assert result.exit_code == 0
        assert "Renamed" in result.output
        assert "Red Hat OpenShift" in result.output
        assert "OpenShift" in result.output

    def test_json_output(self):
        mock_client = _mock_client(rename_entity=AsyncMock(return_value=SAMPLE_RENAME))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["entity", "rename", "ent-001", "Red Hat OpenShift", "--output", "json"]
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["old_name"] == "OpenShift"
        assert parsed["data"]["entity"]["content"] == "Red Hat OpenShift"

    def test_not_found(self):
        mock_rename = AsyncMock(
            side_effect=NotFoundError("ent-999", "Entity not found")
        )
        mock_client = _mock_client(rename_entity=mock_rename)

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["entity", "rename", "ent-999", "New Name"]
            )

        assert result.exit_code == 1
        assert "not_found" in result.output or "not found" in result.output.lower()
