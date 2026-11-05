"""Tests for personal and cluster ``memoryhub doctor`` diagnostics."""

from __future__ import annotations

import builtins
import json
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from memoryhub.exceptions import (
    AuthenticationError,
    ConnectionFailedError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
)
from typer.testing import CliRunner

from memoryhub_cli.main import app

runner = CliRunner()
SMOKE_MEMORY_ID = "11111111-2222-4333-8444-555555555555"
PREEXISTING_MEMORY_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class FakeClient:
    """Small async client fake for exercising the doctor sequence."""

    def __init__(self, fail_at: str | None = None, *, gated_write: bool = False):
        self.fail_at = fail_at
        self.gated_write = gated_write
        self.calls: list[str] = []
        self.deleted_ids: list[str] = []
        self.content: str | None = None
        self._url = "https://user:password@staging.example.test/mcp/?token=hidden#fragment"
        self.session_response: dict[str, object] = {"user_id": "doctor-test-user"}

    def _maybe_fail(self, stage: str) -> None:
        if self.fail_at != stage:
            return
        errors = {
            "endpoint": ConnectionFailedError("private endpoint detail"),
            "auth": AuthenticationError("private authentication detail"),
            "write": PermissionDeniedError("memory", "private write detail"),
            "search": ToolError("memory", "private search detail"),
            "read": NotFoundError(SMOKE_MEMORY_ID, "private read detail"),
            "delete": ToolError("memory", "private delete detail"),
        }
        raise errors[stage]

    async def __aenter__(self):
        self.calls.append("connect")
        self._maybe_fail("endpoint")
        if self.fail_at == "auth_on_connect":
            raise AuthenticationError("private registration detail")
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.calls.append("close")

    async def get_session(self):
        self.calls.append("session")
        self._maybe_fail("auth")
        return self.session_response

    async def write(self, content: str, *, scope: str):
        self.calls.append("write")
        self.content = content
        self._maybe_fail("write")
        if self.gated_write:
            return SimpleNamespace(
                memory=None,
                curation=SimpleNamespace(existing_memory_id=PREEXISTING_MEMORY_ID),
            )
        return SimpleNamespace(
            memory=SimpleNamespace(id=SMOKE_MEMORY_ID, content=content),
            curation=SimpleNamespace(gated=False),
        )

    async def search(self, query: str, **kwargs):
        self.calls.append("search")
        self._maybe_fail("search")
        if query != self.content:
            return SimpleNamespace(results=[])
        return SimpleNamespace(
            results=[SimpleNamespace(id=SMOKE_MEMORY_ID, content=self.content)]
        )

    async def read(self, memory_id: str):
        self.calls.append("read")
        self._maybe_fail("read")
        return SimpleNamespace(id=memory_id, content=self.content)

    async def delete(self, memory_id: str):
        self.calls.append("delete")
        self.deleted_ids.append(memory_id)
        self._maybe_fail("delete")
        return SimpleNamespace(deleted_id=memory_id)


def _hide_personal_edition(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def import_without_personal(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "memoryhub_local" or name.startswith("memoryhub_local."):
            raise ImportError("personal edition hidden for test")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_personal)


def _patch_cluster_client(
    monkeypatch: pytest.MonkeyPatch, client: FakeClient,
) -> None:
    _hide_personal_edition(monkeypatch)
    monkeypatch.setattr("memoryhub_cli.main._get_client", lambda output: client)


def _install_fake_personal_edition(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    local = ModuleType("memoryhub_local")
    local.__path__ = []
    database = ModuleType("memoryhub_local.database")
    database.get_default_db_path = lambda: tmp_path / "missing.db"

    embeddings = ModuleType("memoryhub_local.embeddings")
    embeddings.__path__ = []
    embeddings_base = ModuleType("memoryhub_local.embeddings.base")
    embeddings_base.EMBEDDING_DIM = 384
    embeddings_onnx = ModuleType("memoryhub_local.embeddings.onnx")
    embeddings_onnx.MODEL_DIR_NAME = "test-model"
    embeddings_onnx.get_default_model_dir = lambda: tmp_path / "models" / "test-model"
    embeddings_onnx.is_model_downloaded = lambda model_dir: False

    local.database = database
    local.embeddings = embeddings
    embeddings.base = embeddings_base
    embeddings.onnx = embeddings_onnx
    for name, module in (
        ("memoryhub_local", local),
        ("memoryhub_local.database", database),
        ("memoryhub_local.embeddings", embeddings),
        ("memoryhub_local.embeddings.base", embeddings_base),
        ("memoryhub_local.embeddings.onnx", embeddings_onnx),
    ):
        monkeypatch.setitem(sys.modules, name, module)


def _invoke_cluster(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeClient,
    *args: str,
):
    _patch_cluster_client(monkeypatch, client)
    return runner.invoke(app, ["doctor", *args])


@pytest.mark.parametrize("output_format", ["table", "json"])
@pytest.mark.parametrize("edition_args", [[], ["--edition", "local"]])
def test_personal_doctor_output_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    output_format: str,
    edition_args: list[str],
):
    _install_fake_personal_edition(monkeypatch, tmp_path)

    def unexpected_cluster_client(output):
        raise AssertionError("personal diagnostics must not build a cluster client")

    monkeypatch.setattr("memoryhub_cli.main._get_client", unexpected_cluster_client)
    result = runner.invoke(
        app, ["doctor", *edition_args, "--output", output_format]
    )

    assert result.exit_code == 0
    if output_format == "json":
        payload = json.loads(result.output)
        assert payload == {
            "status": "ok",
            "data": {
                "edition": "personal",
                "db_path": str(tmp_path / "missing.db"),
                "db_exists": False,
                "db_size_bytes": 0,
                "model_dir": str(tmp_path / "models" / "test-model"),
                "model_downloaded": False,
                "model_name": "test-model",
                "embedding_dim": 384,
            },
        }
    else:
        assert "Edition:" in result.output
        assert "personal" in result.output
        assert "Database:" in result.output
        assert "Model:" in result.output
        assert "Endpoint" not in result.output


def test_forced_cluster_edition_overrides_installed_local_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
):
    _install_fake_personal_edition(monkeypatch, tmp_path)
    client = FakeClient()
    monkeypatch.setattr("memoryhub_cli.main._get_client", lambda output: client)

    result = runner.invoke(app, ["doctor", "--edition", "cluster"])

    assert result.exit_code == 0
    assert "Edition:    cluster" in result.output
    assert "Database:" not in result.output
    assert client.calls == [
        "connect", "session", "write", "search", "read", "delete", "close",
    ]


@pytest.mark.parametrize("output_format", ["table", "json"])
def test_context_selects_cluster_and_reports_sanitized_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    output_format: str,
):
    _install_fake_personal_edition(monkeypatch, tmp_path)
    client = FakeClient()

    def context_client(output, *, context=None):
        assert context == "staging"
        return client

    monkeypatch.setattr("memoryhub_cli.main._get_client", context_client)
    result = runner.invoke(
        app, ["doctor", "--context", "staging", "--output", output_format]
    )

    assert result.exit_code == 0
    if output_format == "json":
        data = json.loads(result.output)["data"]
        assert data["edition"] == "cluster"
        assert data["context"] == "staging"
        assert data["endpoint"] == "https://staging.example.test/mcp/"
    else:
        assert "Edition:    cluster" in result.output
        assert "Context:    staging" in result.output
        assert "Server URL: https://staging.example.test/mcp/" in result.output
    assert "password" not in result.output
    assert "token=hidden" not in result.output
    assert "fragment" not in result.output


@pytest.mark.parametrize("output_format", ["table", "json"])
def test_context_cannot_be_used_for_local_checks(
    output_format: str,
):
    result = runner.invoke(
        app,
        [
            "doctor", "--edition", "local", "--context", "staging",
            "--output", output_format,
        ],
    )

    assert result.exit_code == 1
    if output_format == "json":
        error = json.loads(result.stderr)
        assert error["status"] == "error"
        assert error["error"]["code"] == "invalid_context"
        message = error["error"]["message"]
    else:
        message = result.output + result.stderr
        assert "Error (invalid_context)" in message
    assert "--context applies only to cluster checks" in message


def test_unknown_context_reports_configuration_error(monkeypatch: pytest.MonkeyPatch):
    _hide_personal_edition(monkeypatch)
    monkeypatch.setattr("memoryhub_cli.main.read_credentials_section", lambda context: None)
    monkeypatch.setattr(
        "memoryhub.MemoryHubClient",
        lambda **kwargs: pytest.fail("unknown context must fail before connecting"),
    )

    result = runner.invoke(
        app,
        ["doctor", "--edition", "cluster", "--context", "missing", "--output", "json"],
    )

    assert result.exit_code == 1
    error = json.loads(result.stderr)
    assert error["status"] == "error"
    assert "context 'missing' was not found" in error["error"]["message"]


def test_forced_local_without_package_gives_install_instruction(
    monkeypatch: pytest.MonkeyPatch,
):
    _hide_personal_edition(monkeypatch)
    monkeypatch.setattr(
        "memoryhub_cli.main._get_client",
        lambda output: pytest.fail("forced local mode must not check the cluster"),
    )

    result = runner.invoke(app, ["doctor", "--edition", "local", "--output", "json"])

    assert result.exit_code == 1
    error = json.loads(result.stderr)
    assert error["status"] == "error"
    assert error["error"]["code"] == "local_edition_unavailable"
    assert "pip install 'memoryhub[local]'" in error["error"]["message"]


def test_cluster_success_table_reports_all_checks(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient()

    result = _invoke_cluster(monkeypatch, client)

    assert result.exit_code == 0
    for label in ("Endpoint", "Authentication", "Write", "Search", "Read", "Delete"):
        assert label in result.output
    assert result.output.count("passed") == 6
    assert client.calls == [
        "connect", "session", "write", "search", "read", "delete", "close",
    ]
    assert client.deleted_ids == [SMOKE_MEMORY_ID]
    assert client.content.startswith("[test] MemoryHub doctor smoke check ")


def test_cluster_success_json_reports_all_checks(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient()

    result = _invoke_cluster(monkeypatch, client, "--output", "json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["data"]["edition"] == "cluster"
    assert payload["data"]["healthy"] is True
    assert {
        name: check["status"]
        for name, check in payload["data"]["checks"].items()
    } == {
        "endpoint_reachable": "passed",
        "authenticated": "passed",
        "write": "passed",
        "search": "passed",
        "read": "passed",
        "delete": "passed",
    }


def test_cluster_json_reports_session_identity_scopes_expiry_and_projects(
    monkeypatch: pytest.MonkeyPatch,
):
    client = FakeClient()
    client.session_response = {
        "user_id": "doctor-test-user",
        "name": "Doctor Test User",
        "scopes": ["memory:write:user", "memory:read:user"],
        "expires_at": "2026-11-04T13:00:00+00:00",
        "remaining_seconds": 240,
        "projects": [
            {"project_id": "project-b", "description": "hidden description"},
            {"project_id": "project-a"},
        ],
        "session_id": "do-not-report-session-id",
    }

    result = _invoke_cluster(monkeypatch, client, "--output", "json")

    assert result.exit_code == 0
    payload = json.loads(result.output)["data"]
    assert payload["session"] == {
        "user_id": "doctor-test-user",
        "name": "Doctor Test User",
        "scopes": ["memory:read:user", "memory:write:user"],
        "user_scope_permissions": {"read": "granted", "write": "granted"},
        "expires_at": "2026-11-04T13:00:00+00:00",
        "remaining_seconds": 240,
        "near_expiry": True,
        "projects": ["project-a", "project-b"],
    }
    assert "do-not-report-session-id" not in result.output
    assert "hidden description" not in result.output


def test_cluster_table_warns_when_session_near_expiry(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient()
    client.session_response = {
        "user_id": "doctor-test-user",
        "scopes": ["memory:read:user", "memory:write:user"],
        "remaining_seconds": 120,
    }

    result = _invoke_cluster(monkeypatch, client)

    assert result.exit_code == 0
    assert "Identity:" in result.output
    assert "User permissions:" in result.output
    assert "read granted, write granted" in result.output
    assert "Session expires: in 2m (near expiry)" in result.output


@pytest.mark.parametrize(
    ("scopes", "missing_permission"),
    [
        (["memory:read:user"], "user-scope write"),
        (["memory:write:user"], "user-scope read"),
    ],
)
def test_cluster_missing_required_session_scope_fails_before_write(
    monkeypatch: pytest.MonkeyPatch,
    scopes: list[str],
    missing_permission: str,
):
    client = FakeClient()
    client.session_response = {
        "user_id": "doctor-test-user",
        "scopes": scopes,
    }

    result = _invoke_cluster(monkeypatch, client)

    assert result.exit_code == 1
    assert "Authentication:" in result.output
    assert f"missing {missing_permission} permission" in result.output
    assert "memory:write:user" in result.output
    assert "Write:" in result.output and "skipped" in result.output
    assert client.deleted_ids == []
    assert "Smoke-test memory created." not in result.output
    assert "write" not in client.calls


def test_cluster_accepts_broad_memory_read_write_scopes(
    monkeypatch: pytest.MonkeyPatch,
):
    client = FakeClient()
    client.session_response = {
        "user_id": "doctor-test-user",
        "scopes": ["memory:write", "memory:read"],
    }

    result = _invoke_cluster(monkeypatch, client, "--output", "json")

    assert result.exit_code == 0
    session = json.loads(result.output)["data"]["session"]
    assert session["user_scope_permissions"] == {
        "read": "granted",
        "write": "granted",
    }


def test_cluster_derives_near_expiry_from_expiry_timestamp(
    monkeypatch: pytest.MonkeyPatch,
):
    client = FakeClient()
    client.session_response = {
        "user_id": "doctor-test-user",
        "scopes": ["memory:read:user", "memory:write:user"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
    }

    result = _invoke_cluster(monkeypatch, client, "--output", "json")

    assert result.exit_code == 0
    session = json.loads(result.output)["data"]["session"]
    assert session["near_expiry"] is True
    assert 0 < session["remaining_seconds"] <= 300


def test_cluster_expired_session_fails_before_write(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient()
    client.session_response = {
        "user_id": "doctor-test-user",
        "scopes": ["memory:read:user", "memory:write:user"],
        "remaining_seconds": 0,
    }

    result = _invoke_cluster(monkeypatch, client)

    assert result.exit_code == 3
    assert "session has expired" in result.output
    assert "memoryhub login" in result.output
    assert client.deleted_ids == []


@pytest.mark.parametrize(
    ("stage", "label", "exit_code", "next_action"),
    [
        ("endpoint", "Endpoint", 2, "Check MEMORYHUB_URL"),
        ("auth", "Authentication", 3, "memoryhub login"),
        ("auth_on_connect", "Authentication", 3, "memoryhub login"),
        ("write", "Write", 1, "write permission"),
        ("search", "Search", 2, "embedding services"),
        ("read", "Read", 1, "read permission"),
        ("delete", "Delete", 2, "delete it manually"),
    ],
)
def test_cluster_failed_stage_reports_next_action_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    label: str,
    exit_code: int,
    next_action: str,
):
    client = FakeClient(fail_at=stage)

    result = _invoke_cluster(monkeypatch, client)

    assert result.exit_code == exit_code
    assert label in result.output
    assert "failed" in result.output
    assert "Next action:" in result.output
    assert next_action in result.output
    assert "private" not in result.output


@pytest.mark.parametrize("stage", ["search", "read"])
def test_cluster_cleanup_runs_after_later_check_failure(
    monkeypatch: pytest.MonkeyPatch, stage: str,
):
    client = FakeClient(fail_at=stage)

    result = _invoke_cluster(monkeypatch, client)

    assert result.exit_code != 0
    assert client.deleted_ids == [SMOKE_MEMORY_ID]
    assert "Smoke-test memory deleted." in result.output
    assert "failed" in result.output


def test_gated_write_does_not_delete_preexisting_memory(
    monkeypatch: pytest.MonkeyPatch,
):
    client = FakeClient(gated_write=True)

    result = _invoke_cluster(monkeypatch, client)

    assert result.exit_code == 1
    assert "Write:" in result.output
    assert "gated" in result.output
    assert "Delete:" in result.output
    assert "skipped" in result.output
    assert client.deleted_ids == []
    assert PREEXISTING_MEMORY_ID not in result.output


def test_failed_write_does_not_attempt_cleanup(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient(fail_at="write")

    result = _invoke_cluster(monkeypatch, client)

    assert result.exit_code == 1
    assert "Write:" in result.output
    assert client.deleted_ids == []


def test_cleanup_failure_is_reported_with_original_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    client = FakeClient(fail_at="search")
    client.delete_failure = ToolError("memory", "private delete detail")

    async def failing_delete(memory_id: str):
        client.calls.append("delete")
        client.deleted_ids.append(memory_id)
        raise client.delete_failure

    client.delete = failing_delete
    result = _invoke_cluster(monkeypatch, client)
    output = " ".join(result.output.split())

    assert result.exit_code != 0
    assert "The smoke-test search failed." in output
    assert "Cleanup also failed." in output
    assert "may remain" in output
    assert "private" not in output


@pytest.mark.parametrize("args", [["--output", "quiet"], ["-o", "quiet"]])
def test_quiet_success_has_zero_exit_and_no_output(
    monkeypatch: pytest.MonkeyPatch, args: list[str],
):
    result = _invoke_cluster(monkeypatch, FakeClient(), *args)

    assert result.exit_code == 0
    assert result.output == ""


def test_quiet_failure_has_nonzero_exit_and_no_output(monkeypatch: pytest.MonkeyPatch):
    result = _invoke_cluster(monkeypatch, FakeClient(fail_at="endpoint"), "-o", "quiet")

    assert result.exit_code == 2
    assert result.output == ""


def test_json_failure_includes_check_results_and_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
):
    result = _invoke_cluster(
        monkeypatch, FakeClient(fail_at="auth"), "--output", "json",
    )

    assert result.exit_code == 3
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert payload["data"]["healthy"] is False
    assert payload["data"]["checks"]["authenticated"]["status"] == "failed"
    assert payload["error"]["next_action"]
    assert "private" not in result.stderr


@pytest.mark.parametrize("auth_mode", ["api_key", "oauth"])
def test_doctor_uses_api_key_precedence_and_oauth_fallback(
    monkeypatch: pytest.MonkeyPatch, auth_mode: str,
):
    client = FakeClient()
    _hide_personal_edition(monkeypatch)

    if auth_mode == "api_key":
        monkeypatch.setattr("memoryhub_cli.main.get_api_key", lambda: "secret-test-key")
        monkeypatch.setattr(
            "memoryhub_cli.main.get_server_url",
            lambda: "https://memory.example.test/mcp/",
        )
        monkeypatch.setattr(
            "memoryhub_cli.main.get_connection_params",
            lambda: pytest.fail("OAuth fallback must not override an API key"),
        )
        expected = {
            "url": "https://memory.example.test/mcp/",
            "api_key": "secret-test-key",
        }
    else:
        monkeypatch.setattr("memoryhub_cli.main.get_api_key", lambda: None)
        monkeypatch.setattr(
            "memoryhub_cli.main.get_connection_params",
            lambda: {
                "url": "https://memory.example.test/mcp/",
                "auth_url": "https://auth.example.test",
                "client_id": "test-client",
                "client_secret": "secret-test-client",
            },
        )
        expected = {
            "url": "https://memory.example.test/mcp/",
            "auth_url": "https://auth.example.test",
            "client_id": "test-client",
            "client_secret": "secret-test-client",
        }

    with patch("memoryhub.MemoryHubClient", return_value=client) as client_factory:
        result = runner.invoke(app, ["doctor", "--output", "quiet"])

    assert result.exit_code == 0
    client_factory.assert_called_once_with(**expected)
    assert "secret-test" not in result.output
