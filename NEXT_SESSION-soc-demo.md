# Next Session — SOC Demo

**Last session:** 2026-08-05 · `session-summaries/2026-08-05-soc-demo-real-inference.md`
**Branch:** `feat/soc-demo-openshell` (16 commits, PR #500 open to main)

## What landed

All 4 SOC agents (Tier 1/Claude Code, Forensics/FIPS-Agent, Threat Intel/Hermes, IC/OpenClaw) make real LLM calls through GPT-OSS-20B on-cluster via a single FIPS-Agent gateway. Each call searches MemoryHub autonomously via MCP tools. The harness persists each agent's LLM-generated output to MemoryHub. Push broadcast bridge captures real memory writes. Frontend deployed to mcp-rhoai with WebSocket working.

## What's next

### Priority 1: Fix the Forensics empty-response issue

The Forensics agent (Call 2) sometimes returns empty text content from GPT-OSS-20B. The model may be putting all output into tool calls rather than generating a text response. Investigate whether this is a prompt issue (too many steps?) or a model behavior. Try: shorter prompt, explicit "respond with your findings in text" instruction, or capturing tool call results as the response content.

### Priority 2: Clean up duplicate memories

Repeated test runs accumulated duplicate IC synthesis and lesson memories in the `midwest-financial-soc` project. Delete duplicates before the demo recording. Consider adding a `--clean` flag to the harness that removes agent-written memories from previous runs before starting.

### Priority 3: Demo recording

Record the demo with asciinema using `demos/soc-demo/record.sh`. The full run takes 3-5 minutes with 6 LLM calls. Consider whether to also record with the frontend visible (split-screen or picture-in-picture).

### Priority 4: Merge PR #500

Review and merge `feat/soc-demo-openshell` to main. 16 commits -- consider squashing into logical groups (infrastructure, harness, frontend, inference wiring).

### Priority 5: Scale down GPU

The GPU MachineSet was scaled from 3 to 4 for GPT-OSS-20B. Scale back to 3 after the demo is recorded to reduce costs, or keep it if GPT-OSS-20B is needed for other work.

## Open questions

1. The agents search MemoryHub autonomously but don't reliably execute write tool calls -- the harness handles persistence. Is this framing acceptable for the demo narrative, or does the write path need to be agent-driven too?
2. Should the demo recording include the web frontend visualization alongside the terminal output?
3. The cluster token expired mid-session -- `oc login` needed at next session start.
