"""Allow running as `python -m memoryhub_local`."""

import asyncio

from memoryhub_local.server import run_server

asyncio.run(run_server())
