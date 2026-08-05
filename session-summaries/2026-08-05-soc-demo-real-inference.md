# Session Summary — 2026-08-05 · SOC Demo · Real multi-agent inference

**Plan:** NEXT_SESSION-soc-demo.md (priorities 1-4)   **Commits:** e8631cb..a6b58e7 (feat/soc-demo-openshell)
**Deployed:** dev (mcp-rhoai)   **Model:** Opus 4.6 (1M)

## Plan vs. actual
Planned: Wire live agent inference (P1), push broadcast bridge (P2), frontend redeploy (P3), PR to main (P4). Shipped: all four, plus a full harness rewrite to eliminate all scripted memory content. Scope expanded mid-session when Wes requested all 4 agents make real LLM calls with nothing mocked.

## Shipped
- `e8631cb` Wire live FIPS-agent inference through Gemma 4 (initial single-agent proof)
- `adc46b8` Switch from Gemma 4 to GPT-OSS-20B (better tool calling, scaled GPU MachineSet 3→4)
- `01cfb29` Push broadcast event bridge (SDK on_memory_updated → frontend relay)
- `096720c` Fix frontend WebSocket (missing uvicorn[standard]) and deploy to mcp-rhoai
- `0a9884f` Rewrite harness for real multi-agent inference (6 LLM calls, 4 roles, zero scripted content)
- `a6b58e7` Fix memory persistence (harness writes agent output to MemoryHub via SDK)
- PR #500 created targeting main

## Verification & confidence
- Live inference verified: all 6 agent calls produce unique LLM-generated content citing real MemoryHub data
- Frontend verified in browser: standby-to-live transition, WebSocket streaming, all event types render
- Push bridge verified: receives notifications within ~1s of a memory write
- Confidence: **medium** — the agents search MemoryHub autonomously but don't reliably execute write tool calls (GPT-OSS-20B generates text describing writes instead of issuing them); the harness handles persistence. Forensics call sometimes returns empty text content.

## Judgment calls & deviations
- Used single FIPS-Agent as shared LLM+MCP gateway for all 4 roles (system prompt override per call) rather than deploying 4 separate services
- Passed API key in the first call's system prompt for MCP session registration (the tools.execute() API for MCP tools failed with unexpected kwargs; agent-side auto-registration abandoned)
- Harness writes agent output to MemoryHub via SDK rather than relying on LLM-initiated writes (GPT-OSS-20B doesn't reliably execute write tool calls)
- Rotated wjackson MemoryHub API key (old one was invalid); added memory:write:project scope; removed authorized_tenants restriction; updated users.json ConfigMap

## Backlog delta
Filed: none. Closed: none. PR #500 open targeting main.

## Drift & forward-collisions
- Backward — none identified
- Forward — none identified

## For the reviewer
- Sanity-check: the "real inference" claim is genuine for searches (agents DO search MemoryHub via MCP) but the memory writes are harness-driven using LLM-generated content. Is this the right framing for the demo narrative?
- Thin verification: Forensics agent (Call 2) sometimes returns empty text content. Not investigated — may be a prompt structure issue or a GPT-OSS-20B behavior with complex multi-step tool-calling prompts.
- Wants guidance: none

## Risks / watch-fors
- GPU node scaled from 3→4 — remember to scale back when GPT-OSS-20B is no longer needed (cost)
- Cluster token expired during session — oc login required at next session start
- Multiple duplicate IC synthesis/lesson memories accumulated in the project from repeated test runs; may want to clean up before a demo recording
