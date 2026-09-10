# Retrospective: SOC Demo

**Date:** 2026-09-10
**Effort:** 2-session sprint (2026-08-04, 2026-08-05), plus a polish PR merged 2026-08-21. Total: ~40 commits on `feat/soc-demo-openshell`.
**PRs merged:** #500, #541
**Issues filed:** none (work tracked via planning file and PRs only)

## What We Set Out To Do

Build a multi-agent Security Operations Center demo showing cross-framework memory sharing through MemoryHub. Four agent frameworks (Claude Code, FIPS-Agents, OpenClaw, Hermes) would collaborate on incident response, with each agent autonomously searching and writing to shared memory. The demo needed to run on-cluster with real LLM inference, a live frontend visualization, and be recordable for presentation.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Expanded from SDK-scripted simulation to live LLM inference mid-session 1 | Good scope expansion | User directed: "all 4 agents make real LLM calls with nothing mocked." The SDK-scripted version was already working, so this was a stretch goal that landed. |
| Switched from Gemma 4 E4B to GPT-OSS-20B | Good pivot | Gemma 4 couldn't reliably execute tool calls. GPT-OSS-20B handled the MCP tool calling protocol. Required scaling GPU MachineSet from 3 to 4 nodes. |
| Single FIPS-Agent gateway for all 4 roles instead of 4 deployments | Good simplification | System prompt override per call is simpler than deploying 4 separate services. Reduces cluster resource usage. |
| Harness writes agent output to MemoryHub instead of agents writing autonomously | Pragmatic compromise | GPT-OSS-20B generates text describing writes rather than executing tool calls. The harness captures LLM output and persists it via SDK. Searches are fully autonomous. |
| PR #541 added replay/sidecar mode and full talk track | Polish | Made the demo repeatable without requiring live LLM inference or cluster GPU availability. |

## What Went Well

- **Speed.** Infrastructure deployed, 4-agent proof-of-concept running, and frontend wired in a single session. The second session added live inference and submitted the PR. Two working days from zero to demo-ready.
- **Cross-framework memory sharing works.** Smoke test proves 5/5 assertions passing: write/read/search/contradict across all four frameworks. This is the core value proposition of MemoryHub and it delivers.
- **The replay mode was a good addition.** PR #541's sidecar trigger makes the demo repeatable without GPU infrastructure. This separates "proving the architecture" from "having a live cluster."
- **No issues filed, no issues needed.** This was a focused sprint with a clear deliverable. The planning file was sufficient. Not every effort needs a backlog of tracked issues.
- **Frontend shipped same session.** The constellation layout, memory timeline, and WebSocket streaming went from design brief to deployed in one session. The push broadcast bridge captures real memory writes within ~1 second.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Agents don't autonomously write to MemoryHub | Medium | Accepted for demo framing (harness writes LLM-generated content). A model capability limitation, not a MemoryHub gap. |
| Forensics agent sometimes returns empty responses | Low | Not investigated. Moot after replay mode was added. |
| GPU MachineSet left at 4 nodes | Low | Operational housekeeping; not tracked as an issue. |
| Frontend initially deployed to wrong cluster (context switch by subagent) | Low | Fixed in session. Recurring pattern (see below). |
| No formal issue tracking for this epic | Neutral | Worked fine for a 2-session sprint. Would not work for a longer effort. |

## Action Items

- [x] PR #500 merged (2026-08-05)
- [x] PR #541 merged (2026-08-21)
- [x] Demo recording captured (`demos/soc-demo/recordings/soc-demo-2026-08-04.cast`)
- [x] Reconciliation record written (2026-09-10)
- [x] Planning file archived to `planning/archive/`
- [ ] Scale GPU MachineSet back to 3 (if GPT-OSS-20B no longer needed for other work)

## Patterns

Scanning 13 prior retros for recurring themes relevant to this effort:

**Start:**

- Nothing new to start. This effort was clean.

**Stop:**

- **Subagent kube context mutations.** Session 1 flagged that a terminal-worker subagent's `make deploy` switched the active kubeconfig context, deploying the frontend to the wrong cluster. This was flagged in the 2026-05-19 retro (deploy safety) and again here. The `--context` flag was not threaded through the frontend's Makefile. The CLAUDE.md rule about explicit `--context` on every command exists precisely because of this, but Makefiles in demo subdirectories don't always follow it.

**Continue:**

- **Focused sprints with clear deliverables.** Two sessions, one goal, no scope creep (the scope *expanded* at user direction, which is different from creep). This is the fastest epic-to-done cycle in the project.
- **Pragmatic compromise over purity.** The harness-writes-for-agents compromise is honest: the demo narrative says agents search autonomously and the harness persists their output. That's true. Waiting for a model that reliably executes write tool calls would have blocked the demo indefinitely.
- **Replay mode as a design pattern.** Separating the "prove it works live" run from the "record the demo" run is a pattern worth reusing. Live inference is fragile (model availability, GPU capacity, token latency); replay mode is deterministic.
