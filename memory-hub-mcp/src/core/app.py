import os
from fastmcp import FastMCP
from .logging import get_logger

APP_NAME = os.getenv("MCP_SERVER_NAME", "fastmcp-unified")
mcp = FastMCP(APP_NAME)
logger = get_logger("server")

# Import prompts module to trigger decorator registration
# This must happen after mcp is created but before the server runs
try:
    import src.prompts  # noqa: F401

    logger.debug("Prompts module imported for decorator registration")
except ImportError:
    logger.warning("Failed to import prompts module - prompts may not be available")
