# Next Session Plan

## Completed this session (2026-04-16)
- Drafted, committed, and pushed design docs for 6 needs-design issues
  (commit 8bc7856): #166 project-governance, #109 ui/design, #168
  conversation-persistence, #169 context-compaction, #170
  graph-enhanced-memory, #171 knowledge-compilation.
- Linked each design doc from its issue with a summary comment.
- Removed `needs-design` label from #168, #169, #170, #171.
- #102 already closed (confirmed fixed by #63).
- Consulted with demo-chat-agent builder session on MemoryHub
  integration: register_session tool-call pattern (not HTTP header),
  BaseAgent.connect_mcp auth extension, Secret plumbing, system prompt
  block for gpt-oss-20b tool usage.
- Investigated "Red Hat managed" indicator on the RHOAI dashboard tile
  (findings below).

## Priority items for next session

### Red Hat managed indicator — dashboard enablement is harder than it looked

**Current state (verified 2026-04-16).** `OdhApplication/memoryhub` in
`redhat-ods-applications` stays at `spec.category: "Red Hat managed"`
with `provider: "Community"` and `support: "community"`. Attempted to
switch to Self-managed and it disabled the launch link despite every
override we tried.

**What we tried.** Live test 2026-04-16 with `/tmp/memoryhub-tile-backup/`
holding the pre-experiment state:

1. Set `spec.category: "Self-managed"` + `provider: "Red Hat AI Americas"`
   + `support: "community"` and applied. Tile label updated correctly
   but "Open application" became disabled. A useless "View Documentation"
   link appeared.
2. Confirmed `odh-enabled-applications-config` ConfigMap retained
   `memoryhub: "true"` after the switch — the dashboard does NOT prune
   that entry. But the ConfigMap entry alone is not sufficient to
   enable the launch link.
3. Patched the CR's `status.enabled: true` via subresource patch — the
   value stuck (dashboard did not reconcile it away) but the tile
   remained disabled in the UI. `status.enabled` is not the field the
   dashboard reads for the launch-link gate.
4. Reverted to `category: "Red Hat managed"` via direct patch.
   `status.enabled=true` left set (harmless — was already implicitly
   true under Red Hat managed).

**What the dashboard actually checks for Self-managed tiles.** Inspecting
nvidia-nim's full spec: it has an `enable` block whose `inProgressText`
reads "Contacting NVIDIA to validate the license key." The dashboard
source has hardcoded per-app validation endpoints — the `enable` block's
`variables`/`warningValidation` fields only describe the form UI. The
actual "click Enable → tile becomes enabled" transition is gated by an
app-specific validator in the dashboard backend that knows how to talk
to each ISV's service. There is no generic "no-op validator" path
exposed via the CR alone.

**What this means for Self-managed + launch link.** Two paths forward,
both out of scope for a single implementation session:

- **Path 1: Submit an odh-dashboard PR** registering a MemoryHub
  validator. The validator would likely call `register_session` on the
  MCP server with the user-provided API key and return success iff
  auth succeeds. This ties the enable flow to the api-key onboarding
  users already need. Requires engaging with opendatahub-io/odh-dashboard
  maintainers. Probably 2-3 weeks of back-and-forth.
- **Path 2: Bundle MemoryHub into the RHOAI operator's reconciled
  resource set.** This is the right long-term path (already documented
  in `docs/RHOAI-DEMO/odh-application-cr.md`) and skips the Self-managed
  enablement question entirely because Red Hat managed becomes
  legitimately true. Requires coordination with the RHOAI engineering
  team. The same conversation you need to have for the Red Hat managed
  approval anyway.

**Presentation framing.** For the Red Hat managed gatekeepers: the CR
currently says `category: Red Hat managed` because it is the only
RHOAI-dashboard-accepted value that enables the launch link for a
non-Operator-backed app. Present this as "the label needs your approval
to become honest" — the ask is bundling MemoryHub into the RHOAI
operator's reconciled resource set so the category claim matches
reality. Alternative fallback (Self-managed + disabled launch link)
would be honest but degrades UX.

**Cleanup.** The repo YAML at
`memoryhub-ui/openshift/odh-application.yaml` is back at the known-
working state with updated comments documenting why. The local backups
at `/tmp/memoryhub-tile-backup/` can be removed after this session.

### Design doc implementation work (from yesterday's NEXT_SESSION)

The 6 design docs are now candidates for implementation. In ascending
order of scope:

- **#166** (project-governance) — smallest scope, good warm-up.
  Admin API + MCP tools + UI panel + migration 013 with `scope_id` FK.
- **#109** (ui/design) — no implementation, the doc itself is the
  deliverable; future UI issues reference it.
- **#170** Phase 1 (graph-enhanced memory) — temporal validity on
  `memory_relationships` + graph-enhanced retrieval via RRF. Low-risk,
  high-value.
- **#168** (conversation-persistence) — new subsystem; start here if
  pursuing #171 long-term.
- **#169** (context-compaction) — extends existing curator; can be
  done standalone.
- **#171** (knowledge-compilation) — the crown jewel; composes
  168+169+170. Largest scope.

## Context
- SDK v0.6.0 on PyPI (v0.6.1 unreleased: project_id field in ProjectConfig)
- CLI v0.3.0 (unreleased: --project/--non-interactive flags)
- MCP server v0.5.1, build #27, 14 tools deployed
- MinIO deployed to memory-hub-mcp namespace (single-instance, dev credentials)
- Curation thresholds: exact_duplicate 0.98, near_duplicate gate 0.90,
  flag 0.80
- min_appendix=5 (was 1)

## Cluster state
- Cluster: workshop-cluster (n7pd5, sandbox5167). **Pass `--context
  workshop-cluster` on every `oc` / `kubectl` command.** The default
  kubeconfig context is currently the gemma-cluster (l78nk).
- `scripts/cluster-health-check.sh` uses the default context; its
  output is misleading on this cluster. Fix is tracked separately.
- Granite 3.3 8B: granite-model namespace, vLLM (not currently used
  by demo-chat-agent; Granite generates tool-call JSON as raw text on
  this cluster rather than proper `tool_calls`, breaking the ReAct loop)
- gpt-oss-20b second instance: `gpt-oss-model-2` namespace, verified live
- MCP server: memory-hub-mcp namespace
- MinIO: memory-hub-mcp namespace (co-located with MCP server)
- DB: memoryhub-db namespace, migrations through 012 in sync
- OdhApplication: `redhat-ods-applications/memoryhub` (currently
  `category: Red Hat managed`)
