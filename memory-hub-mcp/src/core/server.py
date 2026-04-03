import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from src.core.app import mcp
from src.core.loaders import load_all, start_hot_reload
from src.core.logging import configure_logging, get_logger

log = get_logger("bootstrap")


class UnifiedMCPServer:
    def __init__(
        self, name: Optional[str] = None, src_root: Optional[Path] = None
    ) -> None:
        load_dotenv(override=True)
        configure_logging(os.getenv("MCP_LOG_LEVEL", "INFO"))
        self.name = name or os.getenv("MCP_SERVER_NAME", "fastmcp-unified")
        self.src_root = src_root or Path(__file__).resolve().parent.parent
        try:
            mcp.name = self.name  # type: ignore[attr-defined]
        except Exception:
            pass
        self.mcp = mcp

    def load(self) -> None:
        load_all(self.mcp, self.src_root)

    def run(self) -> None:
        hot = os.getenv("MCP_HOT_RELOAD", "0").lower() in {"1", "true", "yes"}
        observer = None
        if hot:
            observer = start_hot_reload(self.mcp, self.src_root)

        transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
        if transport == "http":
            host = os.getenv("MCP_HTTP_HOST", "127.0.0.1")
            port = int(os.getenv("MCP_HTTP_PORT", "8000"))
            path = os.getenv("MCP_HTTP_PATH", "/mcp/")
            # Note: allowed_origins and bearer_verifier are not supported in FastMCP.run()
            # These would need to be configured differently if needed
            log.info(f"Starting FastMCP HTTP server at http://{host}:{port}{path}")
            self.mcp.run(
                transport="http",
                host=host,
                port=port,
                path=path,
            )
        else:
            log.info("Starting FastMCP in STDIO mode")
            self.mcp.run(transport="stdio")

        if observer:
            observer.stop()
            observer.join(timeout=2)
