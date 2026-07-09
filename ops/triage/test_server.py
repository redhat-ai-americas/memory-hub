import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from server import app, rate_limit_queue

TEST_SECRET = "test-webhook-secret-123"


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("TRIAGE_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setenv("TRIAGE_SKIP_AUTHORS", "rdwj,dependabot[bot]")
    monkeypatch.setenv("TRIAGE_RATE_LIMIT", "10")


@pytest.fixture(autouse=True)
def reset_rate_limit():
    rate_limit_queue.clear()
    yield
    rate_limit_queue.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_subprocess():
    with patch("server.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="", stderr="")
        yield mock


def post_webhook(
    client, payload: dict, event_type: str = "issues",
    secret: str = TEST_SECRET, include_sig: bool = True,
):
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"X-GitHub-Event": event_type, "Content-Type": "application/json"}
    if include_sig:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={sig}"
    return client.post("/webhook", content=body, headers=headers)


def make_issue_payload(number=1, author="external-user", body="Issue body", action="opened"):
    return {
        "action": action,
        "issue": {"number": number, "title": "Test issue", "user": {"login": author}, "body": body},
    }


def make_pr_payload(number=1, author="external-user", additions=10, deletions=5, changed_files=2, action="opened"):
    return {
        "action": action,
        "pull_request": {
            "number": number, "title": "Test PR", "user": {"login": author},
            "body": "PR description", "additions": additions, "deletions": deletions,
            "changed_files": changed_files,
        },
    }


# -- Signature validation --

def test_valid_signature_accepted(client, mock_subprocess):
    resp = post_webhook(client, make_issue_payload())
    assert resp.status_code == 202


def test_missing_signature_rejected(client):
    resp = post_webhook(client, make_issue_payload(), include_sig=False)
    assert resp.status_code == 401


def test_wrong_signature_rejected(client):
    resp = post_webhook(client, make_issue_payload(), secret="wrong-secret")
    assert resp.status_code == 401


def test_malformed_signature_rejected(client):
    body = json.dumps(make_issue_payload()).encode()
    resp = client.post("/webhook", content=body, headers={
        "X-GitHub-Event": "issues", "Content-Type": "application/json",
        "X-Hub-Signature-256": "malformed-no-prefix",
    })
    assert resp.status_code == 401


# -- Author filtering --

@pytest.mark.parametrize("author,should_skip", [
    ("rdwj", True), ("dependabot[bot]", True),
    ("external-user", False), ("another-contributor", False),
])
def test_author_filtering_issues(client, mock_subprocess, author, should_skip):
    resp = post_webhook(client, make_issue_payload(author=author))
    if should_skip:
        assert resp.json()["status"] == "skipped"
        mock_subprocess.assert_not_called()
    else:
        assert resp.status_code == 202


@pytest.mark.parametrize("author,should_skip", [
    ("rdwj", True), ("dependabot[bot]", True), ("external-user", False),
])
def test_author_filtering_prs(client, mock_subprocess, author, should_skip):
    resp = post_webhook(client, make_pr_payload(author=author), event_type="pull_request")
    if should_skip:
        assert resp.json()["status"] == "skipped"
        mock_subprocess.assert_not_called()
    else:
        assert resp.status_code == 202


# -- Event routing --

@pytest.mark.parametrize("event_type,payload_fn,action,expected", [
    ("issues", make_issue_payload, "opened", "accepted"),
    ("pull_request", make_pr_payload, "opened", "accepted"),
    ("issues", make_issue_payload, "closed", "ignored"),
    ("push", lambda **kw: {"action": None}, None, "ignored"),
    ("star", lambda **kw: {"action": "created"}, "created", "ignored"),
])
def test_event_routing(client, mock_subprocess, event_type, payload_fn, action, expected):
    payload = payload_fn(action=action) if action else payload_fn()
    resp = post_webhook(client, payload, event_type=event_type)
    assert resp.json()["status"] == expected


# -- Rate limiting --

def test_rate_limit_allows_ten_requests(client, mock_subprocess):
    payload = make_issue_payload()
    for _ in range(10):
        assert post_webhook(client, payload).status_code == 202


def test_rate_limit_rejects_eleventh(client, mock_subprocess):
    payload = make_issue_payload()
    for _ in range(10):
        post_webhook(client, payload)
    assert post_webhook(client, payload).status_code == 429


# -- Prompt assembly --

def test_issue_prompt_includes_title_and_number():
    from prompts import build_issue_prompt
    payload = make_issue_payload(number=42)
    payload["issue"]["title"] = "Important bug report"
    prompt = build_issue_prompt(payload)
    assert "#42" in prompt
    assert "Important bug report" in prompt


def test_issue_prompt_handles_none_body():
    from prompts import build_issue_prompt
    payload = make_issue_payload()
    payload["issue"]["body"] = None
    assert "(empty)" in build_issue_prompt(payload)


def test_pr_prompt_includes_stats():
    from prompts import build_pr_prompt
    payload = make_pr_payload(number=99, additions=250, deletions=100, changed_files=8)
    prompt = build_pr_prompt(payload)
    assert "#99" in prompt and "+250" in prompt and "-100" in prompt and "8 file(s)" in prompt


def test_pr_prompt_uses_hardcoded_repo():
    from prompts import build_pr_prompt
    assert "redhat-ai-americas/memory-hub" in build_pr_prompt(make_pr_payload())


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"
