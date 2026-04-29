# Cluster URL stability for kagenti-adk E2E

Status: Skeleton — 2026-04-29
Tracks: (no GitHub issue yet — file when picking up)
Author: @rdwj (drafted with Claude Code Opus 4.7)

## Why this exists

The kagenti-adk E2E test (`kagenti/adk` PR #231) is now wired to a specific MemoryHub MCP route on our sandbox cluster:

```
https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/
```

That hostname embeds a sandbox cluster ID (`n7pd5`, `sandbox5167`). Sandbox clusters rotate — when this one is replaced, the URL changes, and the kagenti-adk E2E test breaks until someone updates the repo secret. Today there is no automated handoff for that update; it depends on @rdwj noticing and pinging @JanPokorny out-of-band.

We need to decide how stable this URL needs to be and pick a strategy proportional to that decision. See [`docs/SYSTEMS.md`](../docs/SYSTEMS.md#kagenti-adk) for the full integration profile.

This document is the proposal. **No infrastructure changes in this document.** Implementation is a future session.

## Options

### Option A — document the rotation expectation

Tell kagenti-adk maintainers up front: "This URL belongs to a sandbox cluster and will rotate. If E2E breaks with a connection error, ping @rdwj for a fresh URL." Capture the contract in `docs/SYSTEMS.md` and the `examples/agent-integration/memoryhub/memoryhub-recall/` README on the kagenti side.

- Pro: zero infrastructure work.
- Pro: honest about the situation.
- Con: every rotation is a manual coordination cycle that costs time on both sides.
- Con: kagenti-adk CI is red between the rotation and the secret update.

### Option B — DNS aliasing in front of the route

Stand up a stable hostname (e.g., `memoryhub-test.redhat-ai-americas.example`) that CNAMEs to the current cluster route. When the cluster rotates, update the CNAME — the kagenti-adk secret stays untouched.

- Pro: kagenti-adk side is durable. One change at our edge propagates everywhere.
- Pro: a stable URL also helps any future downstream consumer.
- Con: requires a DNS we control + automation to update on cluster rotation.
- Con: TLS is non-trivial — the cluster's certificate is for the cluster's wildcard domain, not ours. Either accept cert mismatches (insecure) or terminate TLS at our hostname (more infra).

### Option C — dedicated long-lived cluster or namespace

Move the public-facing MemoryHub instance off the sandbox cluster onto something with a longer lifetime (a dev cluster we own, a dedicated OpenShift project, etc.).

- Pro: solves the rotation problem at the root.
- Pro: also gives us a stable home for any operator/admin URLs.
- Con: cluster cost / management overhead.
- Con: project scoping decision: do we host *production-like* MemoryHub for downstream consumers, or stay clearly "test instance"?

### Option D — status page + auto-detection

Publish the current URL at a known stable location (e.g., `https://redhat-ai-americas.github.io/memory-hub/current-url.txt`). The kagenti-adk E2E test reads that file at start to discover the URL.

- Pro: stable URL for *discovery*, even without DNS or new infrastructure.
- Pro: kagenti-adk CI self-heals after rotation (next run picks up the new URL).
- Con: requires a small change on the kagenti-adk side to look up the URL.
- Con: still need a manual step to update the discovery file on rotation; could be a 1-line GitHub Pages commit.

## Recommendation

Option A as the v1 — set expectations clearly. Layer in Option D when the first rotation actually causes pain. Option B/C are over-engineering for one downstream consumer; revisit if a second consumer shows up or if the manual coordination cost gets annoying.

## What needs deciding

- Are we OK with manual coordination on rotation, or is that already too painful?
- If layering in Option D: where does the discovery file live (GitHub Pages? a static route on the cluster itself? another)?
- Do we need to coordinate this with @JanPokorny before changing strategies, or can we adopt server-side and have kagenti-adk catch up?
- Sandbox cluster rotation cadence — how often does it actually happen? Influences how aggressive we need to be.

## Out of scope

- General "production hosting for MemoryHub" decisions. That is a much bigger conversation than test-instance URL stability.
- Authentication credential rotation. Separate concern, separate runbook (`docs/runbooks/add-mcp-api-user.md`).
