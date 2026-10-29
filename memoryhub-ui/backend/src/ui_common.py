"""Shared helpers for the dashboard (redesign) endpoints in ``ui_routes``.

Everything here is tenant-scoped by ``Settings.ui_tenant_id`` like the rest
of the BFF. Helpers never raise for an unreachable optional component; they
report it so the UI can show a degraded or "not configured" state instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, Request
from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings

logger = logging.getLogger(__name__)

SCOPES = ["user", "project", "campaign", "role", "organizational", "enterprise"]
WRITE_EVENTS = ("memory.write", "memory.update", "memory.delete", "memory.relationship_created")
SEARCH_EVENTS = ("memory.search",)
REVIEW_EVENT_PREFIX = "review."


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_uuid(value: str, what: str = "ID") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"Invalid {what}: {value!r}") from None


def live_filters(tenant_id: str, *, current: bool = True) -> list:
    """Base predicates for memories an operator can see in the dashboard."""
    filters = [MemoryNode.tenant_id == tenant_id, MemoryNode.deleted_at.is_(None)]
    if current:
        filters.append(MemoryNode.is_current.is_(True))
    return filters


def clean_stub(stub: str | None) -> str:
    """Drop the "[scope=…, weight=…]" suffix the core service appends to stubs."""
    return re.sub(r"\s*\[scope=[^\]]*\]?.*$", "", stub or "").strip() or (stub or "")


def preview(content: str | None, limit: int = 280) -> str:
    content = content or ""
    return content if len(content) <= limit else content[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Who is using the dashboard
# ---------------------------------------------------------------------------


@dataclass
class Viewer:
    username: str
    name: str
    email: str | None
    source: str  # "oauth-proxy" | "account" | "api-key" | "anonymous"
    role: str = "operator"  # "admin" | "user" | "operator" (open development mode)
    # Test mode account switcher: who is really signed in when viewing as someone else.
    real_username: str | None = None
    real_role: str | None = None

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.replace(".", " ").replace("-", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    @property
    def is_admin(self) -> bool:
        """Platform admin or super-user (#667 tiers 2 and 3)."""
        return self.role in ("admin", "superuser")

    @property
    def is_superuser(self) -> bool:
        return self.role == "superuser"

    @property
    def can_admin(self) -> bool:
        """Platform management (identities, keys, rules, settings, audit)."""
        return self.role in ("admin", "superuser", "operator")

    @property
    def restricted(self) -> bool:
        """Memory reads go through the per-user RBAC predicate.

        Only signed-in users are restricted. Admins are not filtered but never
        see content (see ``redacts_content``); the open-mode operator keeps the
        legacy tenant-wide view and exists only when no sign-in is configured.
        """
        return self.role == "user"

    @property
    def redacts_content(self) -> bool:
        """Admins and super-users never see user-scope content by default;
        which scopes they may read is decided in ``access.access_for``."""
        return self.role in ("admin", "superuser")


def _groups(header_value: str | None) -> list[str]:
    return [g for g in re.split(r"[,\s]+", header_value or "") if g]


VIEW_AS_COOKIE = "memoryhub_ui_view_as"
VIEW_AS_ROLES = ("admin", "superuser", "user", "operator")


def make_view_as_cookie(username: str, role: str, settings: Settings) -> str:
    payload = f"{_clean(username)}|{role}"
    return f"{payload}|{_sign('view-as|' + payload, session_secret(settings))}"


def read_view_as(request: Request, settings: Settings) -> tuple[str, str] | None:
    """The test-mode account switcher's choice, when test mode is on."""
    if not settings.ui_test_mode:
        return None
    raw = request.cookies.get(VIEW_AS_COOKIE)
    if not raw or raw.count("|") != 2:
        return None
    username, role, signature = raw.split("|")
    if role not in VIEW_AS_ROLES or not username:
        return None
    if not hmac.compare_digest(signature, _sign(f"view-as|{username}|{role}", session_secret(settings))):
        return None
    return username, role


def viewer_from_request(request: Request, settings: Settings) -> Viewer:
    """The effective viewer: the signed-in person, or whoever they switched to
    with the test-mode account switcher (MEMORYHUB_UI_TEST_MODE=true)."""
    real = real_viewer(request, settings)
    view_as = read_view_as(request, settings)
    if not view_as or (view_as[0] == real.username and view_as[1] == real.role):
        return real
    username, role = view_as
    return Viewer(
        username=username,
        name=username,
        email=real.email if username == real.username else None,
        source=real.source,
        role=role,
        real_username=real.username,
        real_role=real.role,
    )


def _is_superuser(username: str, groups: list[str], settings: Settings) -> bool:
    """Super-user is assigned by deployment config only (#667), never in the UI."""
    if settings.ui_superuser_group and settings.ui_superuser_group in groups:
        return True
    return username in _groups(settings.ui_superuser_users)


def real_viewer(request: Request, settings: Settings) -> Viewer:
    """Identify the human behind the request.

    The OpenShift OAuth proxy in front of the UI forwards the authenticated
    user in ``X-Forwarded-User`` / ``X-Forwarded-Preferred-Username`` /
    ``X-Forwarded-Email`` and, when configured, ``X-Forwarded-Groups``; members
    of ``ui_admin_group`` are platform admins. Local accounts and dev API-key
    logins carry user and role in the signed session cookie.
    """
    headers = request.headers
    username = headers.get("x-forwarded-preferred-username") or headers.get("x-forwarded-user")
    email = headers.get("x-forwarded-email")
    if username:
        in_group = bool(settings.ui_admin_group) and settings.ui_admin_group in _groups(
            headers.get("x-forwarded-groups")
        )
        groups = _groups(headers.get("x-forwarded-groups"))
        listed = username in _groups(settings.ui_admin_users)
        role = "admin" if in_group or listed else "user"
        if _is_superuser(username, groups, settings):
            role = "superuser"
        return Viewer(username=username, name=username, email=email, source="oauth-proxy", role=role)
    session = read_session(request, settings)
    if session:
        role = session.role
        if role == "admin" and _is_superuser(session.username, [], settings):
            role = "superuser"
        return Viewer(
            username=session.username,
            name=session.name or session.username,
            email=None,
            source=session.source,
            role=role,
        )
    return Viewer(username="dashboard", name="Dashboard operator", email=None, source="anonymous", role="operator")


# ---------------------------------------------------------------------------
# Session cookie (local accounts and dev API-key login)
# ---------------------------------------------------------------------------

SESSION_COOKIE = "memoryhub_ui_session"
SESSION_HOURS = 12


def auth_enabled(settings: Settings) -> bool:
    return bool(settings.ui_dev_api_key or settings.ui_local_accounts)


def session_secret(settings: Settings) -> str:
    if settings.ui_session_secret:
        return settings.ui_session_secret
    if settings.ui_dev_api_key:
        return settings.ui_dev_api_key
    seed = f"memoryhub-ui-session|{settings.db_user}|{settings.db_password}|{settings.db_host}|{settings.ui_tenant_id}"
    return hashlib.sha256(seed.encode()).hexdigest()


def _sign(value: str, key: str) -> str:
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


@dataclass
class Session:
    username: str
    role: str
    source: str
    name: str | None = None


def _clean(part: str) -> str:
    return part.replace("|", "").replace(";", "").strip()


def make_session_cookie(
    username: str,
    settings: Settings,
    *,
    role: str = "admin",
    source: str = "api-key",
    name: str | None = None,
    hours: int = SESSION_HOURS,
) -> str:
    expires = str(int(time.time()) + max(1, hours) * 3600)
    payload = "|".join([_clean(username), role, source, _clean(name or username), expires])
    return f"{payload}|{_sign(payload, session_secret(settings))}"


def read_session(request: Request, settings: Settings) -> Session | None:
    if not auth_enabled(settings):
        return None
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw or raw.count("|") != 5:
        return None
    username, role, source, name, expires, signature = raw.split("|")
    payload = "|".join([username, role, source, name, expires])
    if not hmac.compare_digest(signature, _sign(payload, session_secret(settings))):
        return None
    if role not in ("admin", "user") or source not in ("account", "api-key"):
        return None
    try:
        if time.time() > int(expires):
            return None
    except ValueError:
        return None
    if source == "api-key" and not settings.ui_dev_api_key:
        return None
    if source == "account" and not settings.ui_local_accounts:
        return None
    return Session(username=username, role=role, source=source, name=name)


def read_session_cookie(request: Request, settings: Settings) -> str | None:
    session = read_session(request, settings)
    return session.username if session else None


# ---------------------------------------------------------------------------
# Audit trail for dashboard actions
# ---------------------------------------------------------------------------


async def audit(
    db: AsyncSession,
    *,
    tenant_id: str,
    viewer: Viewer,
    event_type: str,
    scope: str,
    owner_id: str,
    memory_id: uuid.UUID | None,
    decision: str = "allowed",
    metadata: dict | None = None,
) -> None:
    """Append a dashboard action to ``audit_log`` (append-only table)."""
    from memoryhub_core.models.audit import AuditLog

    db.add(
        AuditLog(
            event_type=event_type,
            actor_id=viewer.username,
            driver_id=viewer.username,
            scope=scope or "session",
            owner_id=owner_id or viewer.username,
            memory_id=memory_id,
            decision=decision,
            event_metadata={"via": "dashboard", **(metadata or {})},
            tenant_id=tenant_id,
        )
    )


# ---------------------------------------------------------------------------
# Embeddings / reranker
# ---------------------------------------------------------------------------


async def embed(text_value: str, embedding_url: str, timeout: float = 5.0) -> list[float] | None:
    if not embedding_url or not text_value:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(embedding_url, json={"inputs": text_value})
            response.raise_for_status()
            data = response.json()
            if not data:
                return None
            return data[0] if isinstance(data[0], list) else data
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Embedding service unavailable: %s", exc)
        return None


async def rerank(query: str, texts: list[str], reranker_url: str) -> list[float] | None:
    """Score ``texts`` against ``query`` with a TEI-style reranker."""
    if not reranker_url or not texts:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(reranker_url, json={"query": query, "texts": texts})
            response.raise_for_status()
            data = response.json()
        scores = [0.0] * len(texts)
        for item in data:
            scores[int(item["index"])] = float(item["score"])
        return scores
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Reranker unavailable: %s", exc)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Tenant settings (dashboard-owned)
# ---------------------------------------------------------------------------

DEFAULT_TENANT_SETTINGS: dict[str, Any] = {
    "retrieval": {
        "max_results": 10,
        "max_response_tokens": 4000,
        "session_focus_weight": 0.4,
        "full_content_threshold": 0.8,
        "rerank": True,
        "cache_optimized_ordering": True,
        "realtime_push": True,
    },
    "governance": {
        "project_isolation": True,
        "role_isolation": True,
        "contradiction_threshold": 5,
        "enterprise_approvers": 1,
    },
    "audit": {
        "read_detail": "summary",
        "full_retention_days": 90,
        "mcp_profile": "compact",
    },
    # Set by the first-run admin setup; editable on the Accounts screen.
    "organization": {
        "name": "",
        "contact_email": "",
    },
    "signup": {
        # open: anyone; domain: emails from allowed_domains; invite: invite code; closed: admins create accounts
        "mode": "invite",
        "allowed_domains": [],
        "require_approval": True,
    },
    "privacy": {
        # Scopes whose content admins may read and moderate (#667). User scope
        # is never on this list: personal memories need a super-user incident grant.
        "admin_readable_scopes": ["project", "campaign", "role", "organizational", "enterprise"],
        "break_glass": True,
        "break_glass_hours": 24,
        "break_glass_approvers": 2,  # unused since #667: grants need an incident reference, not approvals
        "incident_pattern": r"^[A-Za-z][A-Za-z0-9]{1,15}-[0-9]{1,10}$",
        "notify_owner": True,
    },
    "security": {
        "session_hours": 12,
        "password_min_length": 12,
    },
}

_SETTINGS_TABLE = "memoryhub_ui_settings"


async def _ensure_settings_table(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


def _merge(defaults: dict, stored: dict) -> dict:
    merged = {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            merged[key] = _merge(value, stored.get(key, {}) if isinstance(stored.get(key), dict) else {})
        else:
            merged[key] = stored.get(key, value)
    return merged


async def load_tenant_settings(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """Return tenant settings merged over defaults. Never raises."""
    try:
        await _ensure_settings_table(db)
        row = (
            await db.execute(
                text(f"SELECT settings, updated_at, updated_by FROM {_SETTINGS_TABLE} WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).first()
    except Exception as exc:
        logger.warning("Could not read tenant settings, using defaults: %s", exc)
        await db.rollback()
        return {**DEFAULT_TENANT_SETTINGS, "_meta": {"updated_at": None, "updated_by": None, "persisted": False}}
    stored = row[0] if row else {}
    if isinstance(stored, str):
        stored = json.loads(stored)
    merged = _merge(DEFAULT_TENANT_SETTINGS, stored or {})
    merged["_meta"] = {
        "updated_at": row[1].isoformat() if row and row[1] else None,
        "updated_by": row[2] if row else None,
        "persisted": True,
    }
    return merged


async def save_tenant_settings(db: AsyncSession, tenant_id: str, values: dict, updated_by: str) -> None:
    await _ensure_settings_table(db)
    clean = _merge(DEFAULT_TENANT_SETTINGS, values)
    await db.execute(
        text(
            f"""
            INSERT INTO {_SETTINGS_TABLE} (tenant_id, settings, updated_at, updated_by)
            VALUES (:t, CAST(:s AS JSONB), now(), :u)
            ON CONFLICT (tenant_id) DO UPDATE
              SET settings = EXCLUDED.settings, updated_at = now(), updated_by = EXCLUDED.updated_by
            """
        ),
        {"t": tenant_id, "s": json.dumps(clean), "u": updated_by},
    )


# ---------------------------------------------------------------------------
# Component health probes
# ---------------------------------------------------------------------------


@dataclass
class Probe:
    key: str
    name: str
    status: str  # healthy | degraded | down | not_configured
    detail: str | None = None
    latency_ms: int | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


async def _timed_http(method: str, url: str, **kwargs) -> tuple[int | None, int]:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.request(method, url, **kwargs)
        return response.status_code, int((time.perf_counter() - started) * 1000)
    except Exception:
        return None, int((time.perf_counter() - started) * 1000)


async def _tcp_probe(url: str, default_port: int) -> tuple[bool, int]:
    started = time.perf_counter()
    parsed = urlparse(url if "://" in url else f"tcp://{url}")
    host, port = parsed.hostname, parsed.port or default_port
    if not host:
        return False, 0
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2.0)
        writer.close()
        return True, int((time.perf_counter() - started) * 1000)
    except Exception:
        return False, int((time.perf_counter() - started) * 1000)


def _latency_status(ok: bool, ms: int, slow_ms: int) -> str:
    if not ok:
        return "down"
    return "degraded" if ms >= slow_ms else "healthy"


async def probe_components(db: AsyncSession, settings: Settings) -> list[dict]:
    async def mcp() -> Probe:
        if not settings.mcp_server_url:
            return Probe("mcp", "MCP server", "not_configured")
        code, ms = await _timed_http("GET", settings.mcp_server_url)
        ok = code is not None and code < 500
        return Probe("mcp", "MCP server", _latency_status(ok, ms, 1500), None if ok else "Not responding", ms)

    async def auth() -> Probe:
        if not settings.auth_service_url:
            return Probe("auth", "Auth service (OAuth 2.1)", "not_configured")
        code, ms = await _timed_http("GET", f"{settings.auth_service_url.rstrip('/')}/healthz")
        ok = code is not None and code < 400
        return Probe(
            "auth", "Auth service (OAuth 2.1)", _latency_status(ok, ms, 1500), None if ok else "Not responding", ms
        )

    async def embedding() -> Probe:
        if not settings.embedding_url:
            return Probe("embedding", "Embedding model", "not_configured")
        started = time.perf_counter()
        vector = await embed("health check", settings.embedding_url, timeout=3.0)
        ms = int((time.perf_counter() - started) * 1000)
        return Probe(
            "embedding",
            "Embedding model",
            _latency_status(vector is not None, ms, 300),
            f"{len(vector)} dims" if vector else "Not responding",
            ms,
        )

    async def reranker() -> Probe:
        if not settings.reranker_url:
            return Probe("reranker", "Cross-encoder reranker", "not_configured")
        started = time.perf_counter()
        scores = await rerank("health check", ["health check"], settings.reranker_url)
        ms = int((time.perf_counter() - started) * 1000)
        return Probe(
            "reranker",
            "Cross-encoder reranker",
            _latency_status(scores is not None, ms, 300),
            None if scores is not None else "Not responding",
            ms,
        )

    async def valkey() -> Probe:
        if not settings.valkey_url:
            return Probe("valkey", "Valkey (push + jobs)", "not_configured")
        ok, ms = await _tcp_probe(settings.valkey_url, 6379)
        return Probe(
            "valkey", "Valkey (push + jobs)", _latency_status(ok, ms, 500), None if ok else "Not reachable", ms
        )

    async def minio() -> Probe:
        if not settings.s3_endpoint:
            return Probe("minio", "MinIO object storage", "not_configured")
        endpoint = settings.s3_endpoint if "://" in settings.s3_endpoint else f"http://{settings.s3_endpoint}"
        code, ms = await _timed_http("GET", f"{endpoint.rstrip('/')}/minio/health/live")
        ok = code is not None and code < 500
        return Probe(
            "minio", "MinIO object storage", _latency_status(ok, ms, 1000), None if ok else "Not reachable", ms
        )

    started = time.perf_counter()
    pg = Probe("postgres", "PostgreSQL + pgvector", "healthy")
    try:
        has_vector = (await db.execute(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'"))).scalar_one()
        pg.latency_ms = int((time.perf_counter() - started) * 1000)
        if not has_vector:
            pg.status, pg.detail = "degraded", "pgvector extension missing"
    except Exception:
        await db.rollback()
        pg.status, pg.detail = "down", "Query failed"

    others = await asyncio.gather(mcp(), auth(), embedding(), reranker(), valkey(), minio())
    ordered = [others[0], others[1], pg, others[2], others[3], others[4], others[5]]
    return [p.as_dict() for p in ordered]
