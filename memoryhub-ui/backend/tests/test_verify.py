"""Connection check result model and memory-behavior profile validation."""

import pytest
from fastapi import HTTPException

from src import me, verify


def _host(**over):
    body = {
        "schema": verify.SCHEMA,
        "produced_by": {"tool": "memoryhub", "version": "0.9", "api_key": "mh-secretsecretsecret"},
        "context": {"endpoint": "https://mcp/", "tenant": "default", "token": "abc", "extra": "dropped"},
        "checks": [
            {"id": "endpoint", "status": "pass", "explanation": "ok"},
            {
                "id": "auth",
                "status": "fail",
                "category": "auth_failed",
                "code": "auth.expired",
                "explanation": "Header was Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig",
                "next_action": "Run memoryhub login",
            },
            {"id": "cross_session", "status": "not_run"},
        ],
    }
    body.update(over)
    return body


def test_upload_is_normalized_and_secrets_are_stripped():
    out = verify.normalize_upload(_host())
    assert out["source"] == "host"
    assert out["produced_by"] == {
        "tool": "memoryhub",
        "version": "0.9",
        "command": None,
        "host": None,
        "profile_version": None,
    }
    assert out["context"] == {"endpoint": "https://mcp/", "tenant": "default"}
    auth = out["checks"][1]
    assert auth["category_label"] == "Authentication failed"
    assert "eyJ" not in auth["explanation"] and "[redacted]" in auth["explanation"]
    assert out["summary"] == {"pass": 1, "warn": 0, "fail": 1, "not_run": 1, "state": "fail"}


@pytest.mark.parametrize(
    "over",
    [
        {"schema": "other/v1"},
        {"checks": []},
        {"checks": [{"id": "x", "status": "ok"}]},
        {"checks": [{"id": "x", "status": "fail", "category": "made_up"}]},
    ],
)
def test_bad_uploads_are_rejected(over):
    with pytest.raises(HTTPException) as exc:
        verify.normalize_upload(_host(**over))
    assert exc.value.status_code == 422


def test_partial_state_when_checks_did_not_run():
    checks = [verify.check("endpoint", "pass", "ok"), verify.check("cross_session", "not_run", "host only")]
    assert verify.summarize(checks)["state"] == "partial"


def test_every_failure_category_from_r1_029_exists():
    assert set(verify.CATEGORIES) == {
        "missing_endpoint",
        "auth_failed",
        "insufficient_permission",
        "wrong_identity",
        "wrong_project",
        "missing_tool",
        "host_integration_failed",
        "extraction_failed",
        "service_unavailable",
        "cleanup_failed",
    }


def test_behavior_profile_defaults_and_validation():
    prefs = me._merge({})
    assert prefs["behavior"]["schema"] == me.PROFILE_SCHEMA
    assert prefs["behavior"]["template"] == "balanced"
    assert me._validate(prefs) == []
    prefs["behavior"]["cadence"] = "hourly"
    prefs["behavior"]["include"] = ["everything"]
    errors = me._validate(prefs)
    assert any("cadence" in e for e in errors) and any("categories" in e for e in errors)


def test_stored_profile_keeps_its_revision():
    stored = {"behavior": {**me.behavior_from_template("conservative", revision=4)}}
    assert me._merge(stored)["behavior"]["revision"] == 4
