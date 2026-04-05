from fastapi import APIRouter, Request

from src.config import settings
from src.keys import get_jwks

router = APIRouter()


@router.get("/.well-known/oauth-authorization-server")
async def oauth_server_metadata(request: Request):
    """RFC 8414 — OAuth 2.0 Authorization Server Metadata."""
    base = settings.issuer
    return {
        "issuer": base,
        "token_endpoint": f"{base}/token",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "grant_types_supported": ["client_credentials", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "scopes_supported": [
            "memory:read",
            "memory:read:user",
            "memory:read:organizational",
            "memory:write",
            "memory:write:user",
            "memory:write:organizational",
            "memory:admin",
        ],
        "response_types_supported": [],
        "service_documentation": "https://github.com/redhat-ai-americas/memory-hub",
    }


@router.get("/.well-known/jwks.json")
async def jwks_endpoint():
    """JSON Web Key Set endpoint."""
    return get_jwks()
