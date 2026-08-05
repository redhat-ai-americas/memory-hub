# Next Session — SOC Demo

**Last session:** 2026-08-04 · `session-summaries/2026-08-04-soc-demo-openshell.md`
**Branch:** `feat/soc-demo-openshell` (8 commits, not yet PR'd to main)

## What landed

Full infrastructure for the 4-agent cross-framework SOC demo: OpenShell on OpenShift, sandbox pods (Claude Code, OpenClaw, Hermes), FIPS-agent deployed, 6 incident memories seeded, orchestration harness with rich terminal output, web frontend visualization, harness-to-frontend wiring, Gemma 4 model config for all 3 open-source agents, asciinema recording pipeline.

## What's next

### Priority 1: Live agent inference through Gemma 4

The harness currently scripts the scenario via MemoryHub SDK calls. The agents have model configs pointing at Gemma 4 but haven't made real inference calls yet. Wire one agent (the FIPS-agent is the easiest -- it's a real BaseAgent with `/v1/chat/completions`) to receive a prompt, call Gemma 4, and use MemoryHub tools autonomously. This proves the full stack: agent -> LLM -> tool call -> MemoryHub -> memory written -> frontend event.

### Priority 2: Push broadcast event bridge

Build the ~80-line Python service that subscribes to MemoryHub push notifications and translates them into frontend events. This captures writes from any agent (including ones the harness doesn't drive) without the harness needing to know about the frontend. This is path 2 from the wiring discussion.

### Priority 3: Frontend iteration

The frontend deployed to the wrong cluster (khsm8 instead of mcp-rhoai) due to a context switch by a terminal-worker subagent. Redeploy to mcp-rhoai. Also: the standby-to-live transition needs testing in a real browser (Puppeteer couldn't advance past the standby screen).

### Priority 4: PR to main

When the demo is in a presentable state, PR `feat/soc-demo-openshell` to main. The branch has 8 commits -- consider squashing or grouping into prep + implementation + docs.

## Open questions

1. Should the harness drive real agent inference for the demo, or is the SDK-scripted approach sufficient for the RSA recording? Real inference adds unpredictability (the LLM might not produce the exact memory content the scenario expects), but it's more authentic.
2. The Hermes install inside the sandbox is ephemeral (pip install in a running pod). Worth building a proper sandbox image, or is the ephemeral approach acceptable for the demo?
3. The FIPS-agent deploys as a standard Helm Deployment, not an OpenShell sandbox. Is that distinction visible enough in the demo, or does it matter?
