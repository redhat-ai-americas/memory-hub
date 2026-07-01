"""Entry point for the Trace Reviewer agent."""

import asyncio
import logging

from memoryhub_agents.config import AgentConfig
from memoryhub_agents.lifecycle import AgentRunner
from memoryhub_agents.plugins.trace_reviewer import TraceReviewerPlugin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


def main() -> None:
    config = AgentConfig()
    plugin = TraceReviewerPlugin()
    runner = AgentRunner(config, plugin)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
