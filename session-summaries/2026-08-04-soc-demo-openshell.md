# Session Summary — 2026-08-04 · SOC Demo · Multi-framework demo on OpenShell

**Plan:** Discussion-driven (no prior NEXT_SESSION)   **Commits:** 502f059..30c68ce (`feat/soc-demo-openshell`)
**Deployed:** OpenShell gateway + FIPS-agent + frontend on cluster   **Model:** Opus 4.6

## Plan vs. actual
Planned: discuss and build a multi-agent SOC demo using Claude Code, FIPS-Agents, OpenClaw, and Hermes on OpenShell. Shipped: full infrastructure deployed, 4-agent proof-of-concept running, orchestration harness with live frontend wiring, recording pipeline. Slipped: none -- exceeded initial scope (frontend visualization and model wiring were added mid-session at user direction).

## Shipped
- `502f059` OpenShell infrastructure on OpenShift: Agent Sandbox CRDs, gateway (v0.0.97, Kubernetes driver), Helm values, sandbox network policy (MCP-protocol-aware), seed script for 6 incident memories, agent configs for all 4 roles
- `85396c5` Cross-framework smoke test: 5/5 assertions passing against real MemoryHub (write/read/search/contradict across Claude Code, FIPS-Agent, OpenClaw, Hermes)
- `36639e3` Orchestration harness (rich terminal output, 7 phases, RSA shot list coverage), recording pipeline (asciinema), FIPS-agent BuildConfig for on-cluster builds
- `48d9067` Frontend design brief for Claude Designer
- `1fbc15e` Gemma 4 E4B model wiring for all 3 open-source agents (on-cluster vLLM)
- `923cab7` Frontend visualization (constellation layout, memory timeline, presenter controls) from Claude Designer
- `30c68ce` Harness-to-frontend wiring (POST /emit integration)

## Verification & confidence
- Cross-framework memory sharing: proven via smoke-test.py (5/5 PASS) and harness.py (7 phases complete) against real MemoryHub on mcp-rhoai cluster
- OpenShell sandbox creation: verified (base sandbox created/deleted, Claude Code v2.1.156 ran, OpenClaw v2026.3.11 ran, Hermes v0.15.2 installed and ran)
- MCP connectivity from sandboxes: verified (403 = auth required, network path works)
- FIPS-agent build: completed on-cluster (BuildConfig, image in internal registry, pod healthy)
- Frontend: deployed on khsm8 cluster (wrong context -- see judgment calls), 37 events received from harness
- Model wiring: Gemma 4 E4B reachable from both sandbox pods and FIPS-agent pod cross-namespace
- Confidence: **medium-high** -- infrastructure is proven, harness drives real MemoryHub data, but the agents aren't yet making autonomous LLM calls through Gemma 4 (the harness scripts the scenario via SDK, not via live agent inference)

## Judgment calls & deviations
- Used OpenShell `allowUnauthenticatedUsers: true` for dev/demo mode instead of configuring OIDC -- appropriate for demo, not for production
- FIPS-agent deployed as a standard Helm Deployment in its own namespace (`soc-forensics`) rather than as an OpenShell sandbox pod -- OpenShell sandboxes use their own image catalog, and creating custom sandbox images is a heavier lift than a standard deployment
- Frontend deployed to khsm8 cluster (not mcp-rhoai) because the terminal-worker subagent's `make deploy` switched the active kube context. Frontend works fine on a different cluster since it's just a relay server -- harness pushes to it over HTTPS
- `hermesclaw` community sandbox image not available in OpenShell catalog -- used base sandbox + `pip install hermes-agent` as fallback
- Harness uses SDK-based simulation for all 4 agents rather than driving real agent inference -- the SDK proves cross-framework memory sharing; live agent inference through Gemma 4 is Phase 3 work

## Backlog delta
Filed: none. Closed: none. New namespaces on cluster: `openshell`, `agent-sandbox-system`, `soc-forensics`, `soc-demo` (on khsm8). Memory: none written. Deferred: push broadcast event bridge (path 2 of frontend wiring), scaling to 10 agents, live agent inference through Gemma 4.

## Drift & forward-collisions
- Backward: none -- this is a new feature branch, no existing issues affected
- Forward: the frontend visualization and harness could serve as the recording pipeline for the clinical scenario too (same architecture, different scenario.json)

## For the reviewer
- Sanity-check: the `allowUnauthenticatedUsers` Helm setting is fine for demo but should not propagate to any production pattern
- Thin verification: agents are not yet making real LLM calls through Gemma 4; the harness scripts the scenario deterministically. The model wiring is verified at the connectivity level (curl to /v1/models succeeds) but not at the inference level
- Wants guidance: none

## Risks / watch-fors
- The kube context switch by the frontend deploy subagent is a recurring pattern -- terminal-worker agents that run `make deploy` can mutate the shared kubeconfig. The `--context` flag on the Makefile wasn't threaded through to all `oc` calls in the frontend's Makefile
- OpenShell is alpha software (their README says "single-player mode"). Sandbox pods may not survive cluster upgrades or node maintenance
- The Hermes install via `pip install` inside a running sandbox is ephemeral -- if the pod restarts, Hermes is gone. A proper sandbox image would fix this
