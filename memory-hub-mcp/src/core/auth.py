import os
import jwt
from dataclasses import dataclass
from fastmcp import Context
from .logging import get_logger

log = get_logger("auth")


@dataclass
class AllowedOrigins:
    patterns: list[str]

    @classmethod
    def from_env(cls, key: str) -> "AllowedOrigins":
        raw = os.getenv(key, "")
        patterns = [p.strip() for p in raw.split(",") if p.strip()]
        return cls(patterns)


class BearerVerifier:
    def __init__(
        self,
        alg: str | None = None,
        secret: str | None = None,
        public_key: str | None = None,
    ) -> None:
        self.alg = alg
        self.secret = secret
        self.public_key = public_key

    @classmethod
    def from_env(cls) -> "BearerVerifier | None":
        alg = os.getenv("MCP_AUTH_JWT_ALG")
        secret = os.getenv("MCP_AUTH_JWT_SECRET")
        public_key = os.getenv("MCP_AUTH_JWT_PUBLIC_KEY")
        if not alg or not (secret or public_key):
            return None
        return cls(alg=alg, secret=secret, public_key=public_key)

    def verify(self, token: str) -> dict | None:
        try:
            if self.public_key:
                return jwt.decode(token, self.public_key, algorithms=[self.alg])
            return jwt.decode(token, self.secret, algorithms=[self.alg])
        except Exception as e:
            log.warning(f"JWT verify failed: {e}")
            return None


def _get_bearer_from_headers(headers: dict[str, str]) -> str | None:
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth:
        return None
    if not auth.lower().startswith("bearer "):
        return None
    return auth.split(" ", 1)[1].strip()


def claims_from_ctx(ctx: Context) -> dict | None:  # best‑effort; HTTP transport only
    try:
        headers = getattr(getattr(ctx, "request", None), "headers", {}) or {}
        token = _get_bearer_from_headers(headers)
        verifier = BearerVerifier.from_env()
        return verifier.verify(token) if (verifier and token) else None
    except Exception:
        return None


def requires_scopes(*scopes: str):
    required = (
        set(scopes)
        if scopes
        else set((os.getenv("MCP_REQUIRED_SCOPES", "").split(",")))
    )
    required = {s.strip() for s in required if s.strip()}

    def deco(fn):
        async def wrapper(*args, **kwargs):
            ctx = kwargs.get("ctx") or next(
                (a for a in args if isinstance(a, Context)), None
            )
            if not ctx:
                return {"error": "missing context for auth"}
            claims = claims_from_ctx(ctx) or {}
            token_scopes = set((claims.get("scope") or "").split()) | set(
                claims.get("scopes", [])
            )
            if not required.issubset(token_scopes):
                await ctx.error("Forbidden: missing required scopes")
                return {
                    "error": "forbidden",
                    "missing": sorted(required - token_scopes),
                }
            return await fn(*args, **kwargs)

        return wrapper

    return deco
