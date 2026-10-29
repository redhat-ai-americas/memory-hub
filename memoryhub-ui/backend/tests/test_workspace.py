"""Knowledge pages, scheduler, restore, entity merge helpers and the usage signal."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from src.knowledge import build_page
from src.main import app
from src.routes_workspace import clean_aliases, heads, usage_from_events
from src.scheduler import is_due
from src.ui_common import Viewer

NOW = datetime.now(UTC)


def _node(stub, *, weight=0.7, domains=None, days=1, version=1, scope="user"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        stub=stub,
        content=stub,
        weight=weight,
        domains=domains,
        updated_at=NOW - timedelta(days=days),
        created_at=NOW - timedelta(days=days),
        version=version,
        scope=scope,
    )


def test_knowledge_page_groups_folds_and_cites():
    a = _node("Prefers Podman over Docker", weight=0.9, domains=["tooling"])
    b = _node("Uses Podman for local containers", weight=0.6, domains=["tooling"])
    c = _node("Deploys to OpenShift", domains=["deploy"], days=100)
    d = _node("Likes short standups", domains=None, days=3)
    e1 = {"id": "e1", "name": "Podman", "type": "object"}
    page = build_page(
        [a, b, c, d],
        entities={a.id: [e1], b.id: [e1]},
        contradictions={c.id: 2},
        same=[(a.id, b.id, 0.95)],
        previous={"facts_index": {"gone": "Old fact"}, "generated_at": "yesterday"},
        fade_days=60,
    )
    assert page["source_count"] == 4
    assert page["summary"]["facts"] == 3 and page["summary"]["folded"] == 1
    tooling = next(s for s in page["sections"] if s["title"] == "tooling")
    fact = tooling["facts"][0]
    assert fact["text"] == "Prefers Podman over Docker" and fact["similar"] == 1
    assert set(fact["memory_ids"]) == {str(a.id), str(b.id)}
    assert page["sections"][-1]["title"] == "General"
    assert page["entities"][0] == {**e1, "count": 2}
    assert page["questions"][0]["memory_id"] == str(c.id)
    assert any(f["memory_id"] == str(c.id) for f in page["stale"])
    assert all(h["memory_id"] != str(c.id) for h in page["highlights"])  # contradicted facts are not highlights
    assert page["changes"]["removed"] == [{"memory_id": "gone", "text": "Old fact"}]
    assert len(page["changes"]["added"]) == 3


def test_schedule_due():
    now = datetime(2026, 10, 22, 10, 0, tzinfo=UTC)
    assert is_due("nightly", "02:00", None, now)
    assert is_due("nightly", "02:00", now - timedelta(days=1), now)
    assert not is_due("nightly", "02:00", now.replace(hour=3), now)
    assert not is_due("nightly", "23:00", now - timedelta(hours=5), now)
    assert not is_due("weekly", "02:00", now - timedelta(days=3), now)
    assert is_due("weekly", "02:00", now - timedelta(days=8), now)
    assert not is_due("off", "02:00", None, now)


def test_restore_makes_newest_versions_current():
    v1 = SimpleNamespace(id=1, previous_version_id=None)
    v2 = SimpleNamespace(id=2, previous_version_id=1)
    branch = SimpleNamespace(id=3, previous_version_id=None)
    assert heads([v1, v2, branch]) == {2, 3}


def test_aliases_are_deduplicated_and_skip_the_name():
    assert clean_aliases(["Podman", " podman ", "pdm", "", "PDM", "Containers"], "podman") == ["pdm", "Containers"]


def test_usage_signal():
    t = NOW
    events = [
        ("m1", "agent", "memory.search", t),
        ("m1", "agent", "memory.read", t + timedelta(minutes=2)),
        ("m1", "agent", "memory.search", t + timedelta(hours=1)),
        ("m2", "agent", "memory.search", t),
        ("m2", "agent", "memory.read", t + timedelta(hours=2)),
        ("m3", "agent", "memory.search", t),
    ]
    usage = usage_from_events(events, full_text_ids={"m3"})
    assert usage["m1"]["used"] == 1 and usage["m1"]["skipped"] == 1 and usage["m1"]["use_rate"] == 0.5
    assert usage["m2"]["used"] == 0 and usage["m2"]["skipped"] == 1
    assert usage["m3"]["full"] == 1 and usage["m3"]["use_rate"] is None


@pytest.mark.asyncio
async def test_admins_get_no_knowledge_or_entity_pages(monkeypatch, labs_on):
    admin = Viewer(username="dk", name="dk", email=None, source="account", role="admin")
    monkeypatch.setattr("src.access.viewer_from_request", lambda request, settings: admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/knowledge")).status_code == 403
        assert (await client.get("/api/knowledge/me/x")).status_code == 403
        assert (await client.get(f"/api/entities/{uuid.uuid4()}")).status_code == 403
        assert (
            await client.post(f"/api/entities/{uuid.uuid4()}/merge", json={"into": str(uuid.uuid4())})
        ).status_code == 403


# ---------------------------------------------------------------------------
# Step 2–4: retrieval funnel, checks, documents, operations
# ---------------------------------------------------------------------------


def test_relaxed_reasons_explain_filtered_memories():
    from src.retrieval import _relaxed_reason

    body = SimpleNamespace(current_only=True, include_branches=False)
    base = {"status": "active", "is_current": True, "parent_id": None, "version": 2}
    assert _relaxed_reason(SimpleNamespace(**{**base, "status": "quarantined"}), body)[0] == "quarantined"
    assert _relaxed_reason(SimpleNamespace(**{**base, "status": "pending"}), body)[0] == "pending"
    assert _relaxed_reason(SimpleNamespace(**{**base, "is_current": False}), body)[0] == "superseded"
    assert _relaxed_reason(SimpleNamespace(**{**base, "parent_id": 1}), body)[0] == "branch"
    assert _relaxed_reason(SimpleNamespace(**base), body) is None
    assert (
        _relaxed_reason(
            SimpleNamespace(**{**base, "parent_id": 1}), SimpleNamespace(current_only=True, include_branches=True)
        )
        is None
    )


def test_check_metrics():
    from src.quality import score, summarise

    m = score(["a", "b"], ["x", "a", "y"])
    assert m == {"expected": 2, "found": 1, "hit": True, "recall": 0.5, "precision": 0.333, "mrr": 0.5, "first_rank": 2}
    assert score(["a"], [])["hit"] is False and score(["a"], [])["precision"] == 0.0
    s = summarise([{"metrics": m, "total_ms": 10}, {"metrics": score(["c"], ["c"]), "total_ms": 30}])
    assert s["checks"] == 2 and s["hit_rate"] == 1.0 and s["recall"] == 0.75 and s["failing"] == 1


def test_search_health_aggregates_counts_only():
    from src.retrieval import summarise_runs

    rows = [
        (
            NOW,
            "playground",
            "vector",
            "on",
            10.0,
            {"matched": 10, "budget": 3, "rbac_dropped": 2, "weight_dropped": 1},
            {"embed": 2},
        ),
        (NOW, "check", "text", "off", 30.0, {"matched": 10, "budget": 0, "rbac_dropped": 0}, {"embed": 4}),
    ]
    h = summarise_runs(rows)
    assert h["runs"] == 2 and h["vector_share"] == 0.5 and h["empty_share"] == 0.5
    assert h["cut"]["rbac"] == 0.1 and h["avg"]["returned"] == 1.5
    assert summarise_runs([]) == {"runs": 0}


def test_document_passages_keep_offsets_and_relocate():
    from src.documents import passages, relocate

    text = "# Title\n\nFirst paragraph here, long enough to stand alone.\n\nSecond one is here too, also long enough."
    parts = passages(text)
    assert all(text[p["start"] : p["end"]] == p["text"] for p in parts)
    assert parts[0]["text"].startswith("# Title") and len(parts) == 2
    long = ("Sentence number one is here. " * 80).strip()
    assert len(passages(long)) > 1
    assert relocate("Second one", "Intro.\n\n" + text, 60) == (
        text.index("Second one") + 8,
        text.index("Second one") + 18,
    )
    assert relocate("gone", text, 0) is None


@pytest.mark.asyncio
async def test_admins_get_no_content_features(monkeypatch, labs_on):
    admin = Viewer(username="dk", name="dk", email=None, source="account", role="admin")
    monkeypatch.setattr("src.access.viewer_from_request", lambda request, settings: admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for method, path in [
            ("get", "/api/saved-queries"),
            ("get", "/api/checks"),
            ("post", "/api/checks/run"),
            ("get", "/api/context-packs"),
            ("get", "/api/documents"),
            ("post", "/api/search"),
        ]:
            resp = await getattr(client, method)(path, **({"json": {"query": "x"}} if method == "post" else {}))
            assert resp.status_code == 403, path


def test_every_ui_table_has_a_migration():
    """Tables are created by Alembic only; any new memoryhub_ui_* table needs a revision."""
    import importlib.util
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    used = set()
    for path in (root / "src").glob("*.py"):
        used |= set(re.findall(r"memoryhub_ui_[a-z_]+", path.read_text()))
    used -= {"memoryhub_ui_session", "memoryhub_ui_view_as"}  # cookies, not tables
    migrated = set()
    for path in (root / "migrations" / "versions").glob("*.py"):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        migrated |= set(getattr(mod, "TABLES", []))
    assert not (used - migrated), f"tables without a migration: {sorted(used - migrated)}"
    for path in (root / "src").glob("*.py"):
        assert "CREATE TABLE" not in path.read_text(), f"{path.name} creates a table outside Alembic"


@pytest.mark.asyncio
async def test_labs_features_are_off_by_default(monkeypatch):
    user = Viewer(username="ar", name="ar", email=None, source="account", role="user")
    monkeypatch.setattr("src.access.viewer_from_request", lambda request, settings: user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for path in [
            "/api/knowledge",
            "/api/context-packs",
            "/api/documents",
            "/api/checks",
            "/api/dreams",
            "/api/search/health",
        ]:
            resp = await client.get(path)
            assert resp.status_code == 404 and "Labs" in resp.json()["detail"], path
