"""Retention sweep management command.

Runs the daily retention enforcement sweep. Designed to be invoked by
a Kubernetes CronJob or manually for testing:

    python -m memoryhub_core.cli.retention_sweep
"""

import asyncio
import logging
import sys

from memoryhub_core.services.database import get_session, init_db
from memoryhub_core.services.conversation import run_retention_sweep
from memoryhub_core.storage.s3 import S3StorageAdapter
from memoryhub_core.config import MinIOSettings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _run() -> int:
    """Execute the retention sweep and return exit code."""
    init_db()

    # Initialize S3 adapter for cleaning up large message content
    try:
        s3_settings = MinIOSettings()
        s3_adapter = S3StorageAdapter(
            endpoint=s3_settings.endpoint,
            access_key=s3_settings.access_key,
            secret_key=s3_settings.secret_key,
            bucket=s3_settings.bucket,
            secure=s3_settings.secure,
        )
    except Exception:
        logger.warning("S3 adapter not available; S3 cleanup will be skipped")
        s3_adapter = None

    async for session in get_session():
        summary = await run_retention_sweep(session, s3_adapter=s3_adapter)
        break

    logger.info(
        "Retention sweep complete: %d soft-deleted, %d hard-deleted, %d skipped (legal hold)",
        summary["soft_deleted"],
        summary["hard_deleted"],
        summary["skipped_legal_hold"],
    )
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
