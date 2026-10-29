"""Local dashboard accounts: first-run admin setup, sign-up, sign-in and the
admin's account management.

Enabled with ``MEMORYHUB_UI_LOCAL_ACCOUNTS=true``. Behind the OpenShift OAuth
proxy accounts are not needed: identities come from the proxy headers and the
admin role from the ``ui_admin_group`` OpenShift group.

Two tables, created on first use next to ``memoryhub_ui_settings``:

* ``memoryhub_ui_accounts`` — one row per person: username, email, display
  name, scrypt password hash, role (``admin`` | ``user``) and status
  (``active`` | ``pending`` | ``disabled``).
* ``memoryhub_ui_invites`` — single-use invite codes an admin hands out.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import AdminDep
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import (
    DEFAULT_TENANT_SETTINGS,
    SESSION_COOKIE,
    Viewer,
    audit,
    load_tenant_settings,
    make_session_cookie,
    now_utc,
    save_tenant_settings,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

ACCOUNTS = "memoryhub_ui_accounts"
INVITES = "memoryhub_ui_invites"
USERNAME_RE = r"^[a-z0-9][a-z0-9._-]{1,62}$"
EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")
SIGNUP_MODES = ("open", "domain", "invite", "closed")

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt, digest = (stored or "").split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def password_problems(password: str, min_length: int) -> list[str]:
    problems = []
    if len(password) < min_length:
        problems.append(f"at least {min_length} characters")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9\W_]", password):
        problems.append("letters and at least one digit or symbol")
    return problems


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


async def ensure_tables(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


def _account_row(row: Any) -> dict:
    m = row._mapping
    return {
        "id": str(m["id"]),
        "username": m["username"],
        "email": m["email"],
        "display_name": m["display_name"],
        "role": m["role"],
        "status": m["status"],
        "job_title": m["job_title"],
        "requested_projects": m["requested_projects"] or [],
        "created_at": m["created_at"],
        "last_login_at": m["last_login_at"],
        "approved_by": m["approved_by"],
        "invited_by": m["invited_by"],
    }


async def admin_count(db: AsyncSession, tenant_id: str) -> int:
    await ensure_tables(db)
    return (
        await db.execute(
            text(f"SELECT count(*) FROM {ACCOUNTS} WHERE tenant_id = :t AND role = 'admin' AND status = 'active'"),
            {"t": tenant_id},
        )
    ).scalar_one()


async def _find(db: AsyncSession, tenant_id: str, login: str):
    return (
        await db.execute(
            text(f"SELECT * FROM {ACCOUNTS} WHERE tenant_id = :t AND (username = :l OR lower(email) = :l)"),
            {"t": tenant_id, "l": login.strip().lower()},
        )
    ).first()


async def _insert(db: AsyncSession, tenant_id: str, **values) -> uuid.UUID:
    account_id = uuid.uuid4()
    import json

    await db.execute(
        text(
            f"""
            INSERT INTO {ACCOUNTS} (id, tenant_id, username, email, display_name, password_hash, role, status,
                                    job_title, requested_projects, approved_by, invited_by)
            VALUES (:id, :t, :username, :email, :display_name, :password_hash, :role, :status,
                    :job_title, CAST(:requested_projects AS JSONB), :approved_by, :invited_by)
            """
        ),
        {
            "id": account_id,
            "t": tenant_id,
            "job_title": None,
            "approved_by": None,
            "invited_by": None,
            **values,
            "requested_projects": json.dumps(values.get("requested_projects") or []),
        },
    )
    return account_id


def _set_session(response: Response, settings: Settings, *, username: str, role: str, name: str, hours: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        make_session_cookie(username, settings, role=role, source="account", name=name, hours=hours),
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=hours * 3600,
    )


def _actor(username: str, role: str) -> Viewer:
    return Viewer(username=username, name=username, email=None, source="account", role=role)


# ---------------------------------------------------------------------------
# Validation of the access-related tenant settings
# ---------------------------------------------------------------------------


def validate_access_settings(values: dict) -> list[str]:
    errors = []
    signup = values.get("signup", {})
    if signup.get("mode") not in SIGNUP_MODES:
        errors.append("Sign-up mode must be open, domain, invite or closed")
    domains = signup.get("allowed_domains") or []
    if not isinstance(domains, list) or any(not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", str(d)) for d in domains):
        errors.append("Allowed domains must look like example.com")
    if signup.get("mode") == "domain" and not domains:
        errors.append("Domain sign-up needs at least one allowed domain")
    privacy = values.get("privacy", {})
    scopes = privacy.get("admin_readable_scopes") or []
    if not isinstance(scopes, list) or any(
        s not in ("project", "campaign", "role", "organizational", "enterprise") for s in scopes
    ):
        errors.append("Admins can never read user memories; that needs a super-user incident grant")
    pattern = privacy.get("incident_pattern")
    if pattern is not None:
        try:
            re.compile(str(pattern))
        except re.error:
            errors.append("The incident reference pattern is not a valid regular expression")
    if not (1 <= int(privacy.get("break_glass_hours", 24)) <= 72):
        errors.append("Break-glass access must expire within 1 to 72 hours")
    if not (1 <= int(privacy.get("break_glass_approvers", 2)) <= 5):
        errors.append("Break-glass approvers must be between 1 and 5")
    security = values.get("security", {})
    if not (1 <= int(security.get("session_hours", 12)) <= 24):
        errors.append("Sessions must last 1 to 24 hours")
    if not (10 <= int(security.get("password_min_length", 12)) <= 64):
        errors.append("Minimum password length must be between 10 and 64")
    return errors


def _normalise_domains(domains: list[str] | None) -> list[str]:
    return sorted({d.strip().lower().lstrip("@") for d in (domains or []) if d and d.strip()})


# ---------------------------------------------------------------------------
# Public: status, setup, sign-up, sign-in
# ---------------------------------------------------------------------------


async def accounts_status(db: AsyncSession, settings: Settings) -> dict:
    """Extra fields for /api/auth/status when local accounts are enabled."""
    try:
        admins = await admin_count(db, settings.ui_tenant_id)
        values = await load_tenant_settings(db, settings.ui_tenant_id)
    except Exception as exc:  # pragma: no cover - needs a database
        logger.warning("Accounts status unavailable: %s", exc)
        await db.rollback()
        return {"setup_required": False, "accounts_available": False}
    signup = values["signup"]
    return {
        "accounts_available": True,
        "setup_required": admins == 0,
        "setup_token_required": bool(settings.ui_setup_token),
        "organization": values["organization"].get("name") or None,
        "signup": {
            "mode": signup["mode"],
            "require_approval": bool(signup["require_approval"]),
            "allowed_domains": signup["allowed_domains"] if signup["mode"] == "domain" else [],
        },
        "password_min_length": int(values["security"]["password_min_length"]),
    }


class AdminAccountIn(BaseModel):
    username: str = Field(pattern=USERNAME_RE)
    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class SetupRequest(BaseModel):
    setup_token: str | None = None
    organization: dict = Field(default_factory=dict)  # name, contact_email
    admin: AdminAccountIn
    signup: dict = Field(default_factory=dict)  # mode, allowed_domains, require_approval
    privacy: dict = Field(default_factory=dict)  # admin_readable_scopes, break_glass, break_glass_hours, ...
    security: dict = Field(default_factory=dict)  # session_hours, password_min_length


@router.post("/api/auth/setup", status_code=201)
async def setup(body: SetupRequest, response: Response, db: DbDep, settings: SettingsDep):
    """Create the first platform admin and the tenant's access policy."""
    if not settings.ui_local_accounts:
        raise HTTPException(status_code=404, detail="Local accounts are disabled on this deployment")
    tenant_id = settings.ui_tenant_id
    if await admin_count(db, tenant_id) > 0:
        raise HTTPException(status_code=409, detail="This tenant already has a platform admin. Sign in instead.")
    if settings.ui_setup_token and not hmac.compare_digest(body.setup_token or "", settings.ui_setup_token):
        raise HTTPException(status_code=403, detail="The setup token is not valid")

    current = await load_tenant_settings(db, tenant_id)
    merged = {k: dict(current[k]) for k in DEFAULT_TENANT_SETTINGS}
    for section in ("organization", "signup", "privacy", "security"):
        merged[section].update({k: v for k, v in getattr(body, section).items() if k in merged[section]})
    merged["signup"]["allowed_domains"] = _normalise_domains(merged["signup"].get("allowed_domains"))
    org_name = str(merged["organization"].get("name") or "").strip()
    errors = validate_access_settings(merged)
    if not org_name:
        errors.append("Organization name is required")
    admin = body.admin
    email = admin.email.strip().lower()
    if not EMAIL_RE.match(email):
        errors.append("Admin email is not valid")
    problems = password_problems(admin.password, int(merged["security"]["password_min_length"]))
    if problems:
        errors.append("Password needs " + " and ".join(problems))
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))

    await _insert(
        db,
        tenant_id,
        username=admin.username,
        email=email,
        display_name=admin.display_name.strip(),
        password_hash=hash_password(admin.password),
        role="admin",
        status="active",
        approved_by="setup",
    )
    await save_tenant_settings(db, tenant_id, merged, admin.username)
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=_actor(admin.username, "admin"),
        event_type="account.setup",
        scope="session",
        owner_id=tenant_id,
        memory_id=None,
        metadata={"organization": org_name, "signup_mode": merged["signup"]["mode"]},
    )
    await db.commit()
    hours = int(merged["security"]["session_hours"])
    _set_session(response, settings, username=admin.username, role="admin", name=admin.display_name, hours=hours)
    return {"ok": True, "user": admin.username, "role": "admin"}


class RegisterRequest(BaseModel):
    username: str = Field(pattern=USERNAME_RE)
    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)
    job_title: str | None = Field(default=None, max_length=255)
    requested_projects: list[str] = Field(default_factory=list, max_length=20)
    invite_code: str | None = Field(default=None, max_length=64)
    accept_privacy: bool = False


@router.post("/api/auth/register", status_code=201)
async def register(body: RegisterRequest, response: Response, db: DbDep, settings: SettingsDep):
    if not settings.ui_local_accounts:
        raise HTTPException(status_code=404, detail="Local accounts are disabled on this deployment")
    tenant_id = settings.ui_tenant_id
    await ensure_tables(db)
    if await admin_count(db, tenant_id) == 0:
        raise HTTPException(status_code=409, detail="This tenant has not been set up yet. Create the admin first.")
    values = await load_tenant_settings(db, tenant_id)
    signup, security = values["signup"], values["security"]
    email = body.email.strip().lower()
    match = EMAIL_RE.match(email)
    errors = []
    if not match:
        errors.append("Email is not valid")
    if not body.accept_privacy:
        errors.append("Accept the privacy notice to continue")
    problems = password_problems(body.password, int(security["password_min_length"]))
    if problems:
        errors.append("Password needs " + " and ".join(problems))
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))

    invite = None
    mode = signup["mode"]
    if body.invite_code:
        invite = (
            await db.execute(
                text(
                    f"SELECT * FROM {INVITES} WHERE code = :c AND tenant_id = :t AND used_at IS NULL "
                    "AND expires_at > now()"
                ),
                {"c": body.invite_code.strip(), "t": tenant_id},
            )
        ).first()
        if invite is None:
            raise HTTPException(status_code=403, detail="That invite code is not valid or has expired")
        if invite._mapping["email"] and invite._mapping["email"].lower() != email:
            raise HTTPException(status_code=403, detail="That invite was issued for a different email address")
    elif mode == "closed":
        raise HTTPException(status_code=403, detail="Sign-up is closed. Ask a platform admin for an account.")
    elif mode == "invite":
        raise HTTPException(status_code=403, detail="Sign-up needs an invite code from a platform admin")
    elif mode == "domain" and match and match.group(1) not in signup["allowed_domains"]:
        raise HTTPException(status_code=403, detail="Sign-up is limited to " + ", ".join(signup["allowed_domains"]))

    if await _find(db, tenant_id, body.username) or await _find(db, tenant_id, email):
        raise HTTPException(status_code=409, detail="An account with that username or email already exists")

    role = invite._mapping["role"] if invite is not None else "user"
    # An invite is an admin's approval; everyone else waits when approval is on.
    status = "active" if invite is not None or not signup["require_approval"] else "pending"
    await _insert(
        db,
        tenant_id,
        username=body.username,
        email=email,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
        role=role,
        status=status,
        job_title=body.job_title,
        requested_projects=[p.strip() for p in body.requested_projects if p.strip()],
        approved_by=invite._mapping["created_by"] if invite is not None else None,
        invited_by=invite._mapping["created_by"] if invite is not None else None,
    )
    if invite is not None:
        await db.execute(
            text(f"UPDATE {INVITES} SET used_by = :u, used_at = now() WHERE code = :c"),
            {"u": body.username, "c": invite._mapping["code"]},
        )
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=_actor(body.username, role),
        event_type="account.register",
        scope="session",
        owner_id=body.username,
        memory_id=None,
        metadata={"status": status, "via": "invite" if invite is not None else mode},
    )
    await db.commit()
    if status == "active":
        _set_session(
            response,
            settings,
            username=body.username,
            role=role,
            name=body.display_name,
            hours=int(security["session_hours"]),
        )
    return {"ok": True, "user": body.username, "role": role, "status": status}


async def password_login(db: AsyncSession, settings: Settings, response: Response, login: str, password: str) -> dict:
    tenant_id = settings.ui_tenant_id
    await ensure_tables(db)
    row = await _find(db, tenant_id, login)
    # Same message for unknown user and wrong password.
    if row is None or not verify_password(password, row._mapping["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong username, email or password")
    m = row._mapping
    if m["status"] == "pending":
        raise HTTPException(status_code=403, detail="Your account is waiting for a platform admin to approve it")
    if m["status"] != "active":
        raise HTTPException(status_code=403, detail="This account is disabled. Contact a platform admin.")
    await db.execute(text(f"UPDATE {ACCOUNTS} SET last_login_at = now() WHERE id = :id"), {"id": m["id"]})
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=_actor(m["username"], m["role"]),
        event_type="account.login",
        scope="session",
        owner_id=m["username"],
        memory_id=None,
    )
    await db.commit()
    hours = int((await load_tenant_settings(db, tenant_id))["security"]["session_hours"])
    _set_session(response, settings, username=m["username"], role=m["role"], name=m["display_name"], hours=hours)
    return {"ok": True, "user": m["username"], "role": m["role"]}


# ---------------------------------------------------------------------------
# Admin: accounts and invites
# ---------------------------------------------------------------------------


@router.get("/api/accounts")
async def list_accounts(db: DbDep, settings: SettingsDep, viewer: AdminDep):
    await ensure_tables(db)
    rows = (
        await db.execute(
            text(
                f"SELECT * FROM {ACCOUNTS} WHERE tenant_id = :t "
                "ORDER BY (status = 'pending') DESC, role, created_at DESC"
            ),
            {"t": settings.ui_tenant_id},
        )
    ).all()
    items = [_account_row(r) for r in rows]
    invites = (
        await db.execute(
            text(f"SELECT * FROM {INVITES} WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 50"),
            {"t": settings.ui_tenant_id},
        )
    ).all()
    now = now_utc()
    return {
        "items": items,
        "counts": {
            "all": len(items),
            "pending": sum(1 for i in items if i["status"] == "pending"),
            "admins": sum(1 for i in items if i["role"] == "admin" and i["status"] == "active"),
            "disabled": sum(1 for i in items if i["status"] == "disabled"),
        },
        "invites": [
            {
                "code": r._mapping["code"][:4] + "…" + r._mapping["code"][-4:],
                "id": r._mapping["code"][:12],
                "role": r._mapping["role"],
                "email": r._mapping["email"],
                "note": r._mapping["note"],
                "created_by": r._mapping["created_by"],
                "created_at": r._mapping["created_at"],
                "expires_at": r._mapping["expires_at"],
                "used_by": r._mapping["used_by"],
                "state": "used" if r._mapping["used_at"] else ("expired" if r._mapping["expires_at"] < now else "open"),
            }
            for r in invites
        ],
    }


class AccountUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    role: str | None = Field(default=None, pattern="^(admin|user)$")


@router.patch("/api/accounts/{account_id}")
async def update_account(account_id: str, body: AccountUpdate, db: DbDep, settings: SettingsDep, viewer: AdminDep):
    await ensure_tables(db)
    tenant_id = settings.ui_tenant_id
    try:
        parsed = uuid.UUID(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid account ID") from exc
    row = (
        await db.execute(
            text(f"SELECT * FROM {ACCOUNTS} WHERE id = :id AND tenant_id = :t"), {"id": parsed, "t": tenant_id}
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    m = row._mapping
    losing_admin = (
        m["role"] == "admin" and m["status"] == "active" and (body.role == "user" or body.status == "disabled")
    )
    if losing_admin and await admin_count(db, tenant_id) <= 1:
        raise HTTPException(status_code=409, detail="The tenant needs at least one active platform admin")
    if m["username"] == viewer.username and losing_admin:
        raise HTTPException(status_code=409, detail="You cannot remove your own admin access")
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if not changes:
        return _account_row(row)
    sets = ", ".join(f"{k} = :{k}" for k in changes)
    extra = ", approved_by = :approver" if changes.get("status") == "active" and m["status"] == "pending" else ""
    await db.execute(
        text(f"UPDATE {ACCOUNTS} SET {sets}{extra} WHERE id = :id"),
        {**changes, "approver": viewer.username, "id": parsed},
    )
    event = "account.approve" if extra else "account.update"
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type=event,
        scope="session",
        owner_id=m["username"],
        memory_id=None,
        metadata={"changes": changes},
    )
    await db.commit()
    fresh = (await db.execute(text(f"SELECT * FROM {ACCOUNTS} WHERE id = :id"), {"id": parsed})).first()
    return _account_row(fresh)


class InviteRequest(BaseModel):
    role: str = Field(default="user", pattern="^(admin|user)$")
    email: str | None = Field(default=None, max_length=320)
    note: str | None = Field(default=None, max_length=255)
    expires_days: int = Field(default=7, ge=1, le=30)


@router.post("/api/invites", status_code=201)
async def create_invite(body: InviteRequest, request: Request, db: DbDep, settings: SettingsDep, viewer: AdminDep):
    await ensure_tables(db)
    email = (body.email or "").strip().lower() or None
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Email is not valid")
    code = secrets.token_urlsafe(18)
    expires = now_utc() + timedelta(days=body.expires_days)
    await db.execute(
        text(
            f"INSERT INTO {INVITES} (code, tenant_id, role, email, note, created_by, expires_at) "
            "VALUES (:c, :t, :r, :e, :n, :by, :x)"
        ),
        {
            "c": code,
            "t": settings.ui_tenant_id,
            "r": body.role,
            "e": email,
            "n": body.note,
            "by": viewer.username,
            "x": expires,
        },
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="account.invite",
        scope="session",
        owner_id=email or "invite",
        memory_id=None,
        metadata={"role": body.role, "expires_days": body.expires_days},
    )
    await db.commit()
    base = str(request.base_url).rstrip("/")
    # The code is shown once, like a client secret.
    return {
        "code": code,
        "role": body.role,
        "email": email,
        "expires_at": expires,
        "link": f"{base}/#/register?invite={code}",
    }
