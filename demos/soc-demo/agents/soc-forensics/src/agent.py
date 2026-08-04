"""Agent subclass — implement step() to define a single agent turn.

This is the minimal shape: one model call, optional tool dispatch, return.
See CLAUDE.md ("Calling Patterns") for richer patterns — structured output
via ``call_model_json``, validation-with-retry via ``call_model_validated``,
and agent-code tool dispatch via ``self.use_tool()``.

Replace ``MyAgent`` with your agent class name (``/create-agent`` does this
automatically from your ``AGENT_PLAN.md``).
"""

from __future__ import annotations

from fipsagents.baseagent import BaseAgent, StepResult


class MyAgent(BaseAgent):
    """Single-turn agent — calls the model, runs any tool calls, returns."""

    async def step(self) -> StepResult:
        response = await self.call_model()
        response = await self.run_tool_calls(response)
        return StepResult.done(result=response.content)


# ---------------------------------------------------------------------------
# HTTP server (default) vs. batch mode
#
# By default, the agent starts as an OpenAI-compatible HTTP server on
# port 8080 with /v1/chat/completions, /healthz, and /v1/agent-info.
# This is what the Helm chart, gateway, and UI expect.
#
# To switch to batch mode (one-shot execution, no HTTP server):
#   1. Replace the block below with:
#        import asyncio
#        from fipsagents.baseagent import load_config
#        async def main():
#            config = load_config()
#            agent = MyAgent(config=config)
#            await agent.start()
#        asyncio.run(main())
#   2. Comment out EXPOSE 8080 in the Containerfile
#   3. Remove the liveness/readiness probes from chart/templates/deployment.yaml
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from fipsagents.baseagent import load_config
    from fipsagents.server import OpenAIChatServer

    config = load_config("agent.yaml")
    server = OpenAIChatServer(
        agent_class=MyAgent,
        config_path="agent.yaml",
        title=config.agent.name,
        version=config.agent.version,
    )
    server.run(host=config.server.host, port=config.server.port)
