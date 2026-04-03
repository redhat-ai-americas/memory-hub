import logging
from fastmcp.utilities.logging import get_logger as _get


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    # Namespaced logger under FastMCP.* per docs
    return _get(name)
