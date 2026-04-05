import os
from fastmcp import FastMCP
from .logging import get_logger

APP_NAME = os.getenv("MCP_SERVER_NAME", "fastmcp-unified")
logger = get_logger("server")

# Wire JWT verification if AUTH_JWKS_URI is set (points to the auth service)
_auth = None
_jwks_uri = os.getenv("AUTH_JWKS_URI")
_issuer = os.getenv("AUTH_ISSUER")
_audience = os.getenv("AUTH_AUDIENCE", "memoryhub")
if _jwks_uri and _issuer:
    try:
        from fastmcp.server.auth.providers.jwt import JWTVerifier

        _auth = JWTVerifier(
            jwks_uri=_jwks_uri,
            issuer=_issuer,
            audience=_audience,
        )
        logger.info("JWT verification enabled — jwks_uri=%s, issuer=%s", _jwks_uri, _issuer)
    except ImportError:
        logger.warning("FastMCP JWTVerifier not available — running without auth")
else:
    logger.info("No AUTH_JWKS_URI set — running without JWT verification")

mcp = FastMCP(APP_NAME, auth=_auth) if _auth else FastMCP(APP_NAME)

# Import prompts module to trigger decorator registration
# This must happen after mcp is created but before the server runs
try:
    import src.prompts  # noqa: F401

    logger.debug("Prompts module imported for decorator registration")
except ImportError:
    logger.warning("Failed to import prompts module - prompts may not be available")
