#!/usr/bin/env python3
"""Push broadcast event bridge.

Subscribes to MemoryHub push notifications and forwards memory writes
to the SOC demo frontend as events. This captures writes from any agent
(including ones the harness doesn't drive) without the harness needing
to know about the frontend.

Usage:
    python demos/soc-demo/push-bridge.py

Env vars:
    FRONTEND_URL     -- frontend relay server (required)
    FRONTEND_TOKEN   -- optional X-Emit-Token for frontend auth
    MEMORYHUB_URL    -- MemoryHub MCP endpoint (or from credentials file)
    MEMORYHUB_API_KEY -- MemoryHub API key (or from credentials file)
"""

import asyncio
import configparser
import json
import logging
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdk/src"))

from memoryhub import MemoryHubClient
from memoryhub.config import MemoryLoadingConfig, ProjectConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("push-bridge")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "")
FRONTEND_TOKEN = os.environ.get("FRONTEND_TOKEN", "")


def emit(event: dict):
    if not FRONTEND_URL:
        return
    data = json.dumps(event).encode()
    headers = {"Content-Type": "application/json"}
    if FRONTEND_TOKEN:
        headers["X-Emit-Token"] = FRONTEND_TOKEN
    req = urllib.request.Request(f"{FRONTEND_URL}/emit", data, headers)
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        log.warning("Failed to emit event: %s", exc)


def load_credentials() -> tuple[str, str]:
    url = os.environ.get("MEMORYHUB_URL", "")
    api_key = os.environ.get("MEMORYHUB_API_KEY", "")
    if url and api_key:
        return url, api_key
    config = configparser.ConfigParser()
    config.read(os.path.expanduser("~/.config/memoryhub/credentials"))
    section = os.environ.get("MEMORYHUB_CONTEXT", "mcp-rhoai")
    if section not in config:
        section = "default"
    return (
        url or config.get(section, "url", fallback=""),
        api_key or config.get(section, "api_key", fallback=""),
    )


async def main():
    if not FRONTEND_URL:
        log.error("FRONTEND_URL not set")
        return 1

    url, api_key = load_credentials()
    if not url or not api_key:
        log.error("Set MEMORYHUB_URL/MEMORYHUB_API_KEY or configure credentials file")
        return 1

    project_config = ProjectConfig(
        memory_loading=MemoryLoadingConfig(live_subscription=True),
    )
    client = MemoryHubClient(url=url, api_key=api_key, project_config=project_config)

    async def on_memory_updated(uri: str):
        memory_id = uri.removeprefix("memoryhub://memory/")
        log.info("Memory updated: %s", memory_id)
        try:
            mem = await client.read(memory_id)
            content = mem.content if mem else ""
            scope = mem.scope if mem else "unknown"
            metadata = mem.metadata or {} if mem else {}
            emit({
                "type": "memory_write",
                "agent": "push",
                "memory_id": memory_id,
                "content": content[:500],
                "metadata": {
                    "scope": scope,
                    "source": "push_broadcast",
                    **metadata,
                },
            })
            log.info("Forwarded to frontend: %s (%d chars)", memory_id, len(content))
        except Exception as exc:
            log.warning("Failed to read memory %s: %s", memory_id, exc)

    client.on_memory_updated(on_memory_updated)
    log.info("Connecting to MemoryHub at %s", url)
    log.info("Forwarding events to %s", FRONTEND_URL)

    async with client:
        log.info("Push bridge active. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        log.info("Shutting down.")
