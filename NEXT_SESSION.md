# Next Session Plan

## Priority: Fix byte-stability gap in memory injection, SDK model bug

### 1. Fix `get_injection_block()` byte-stability (HIGH)

The #185 validation proved that append-only mode invalidates the entire
vLLM prefix cache because `get_injection_block()` does not produce a
byte-stable prefix when appendix entries are present. The compiled
section's text shifts when new memories are added, breaking every cached
block from the first changed byte onward.

**The fix:** Render compiled and appendix as two separately stable text
segments. The compiled section must produce byte-identical output
regardless of what (or how many) appendix entries follow it.

Options to evaluate:
- (A) Two-segment concatenation: `{compiled_block}\n===\n{appendix_block}`
  where the compiled block is rendered independently
- (B) Pad the compiled section to a fixed token-aligned length (fragile,
  depends on tokenizer)
- (C) Render each memory with a fixed-width separator so inserted content
  never shifts prior memory positions

After implementing, run `python scripts/validate-prefix-cache.py --scenario byte_stability_fix`
to validate. Target: append-only hit rate >= 80% (currently 1.78% on
Granite, 8.36% on GPT-OSS).

### 2. Lower `should_recompile` threshold to 1 (INTERIM)

Until the byte-stability fix lands, set `min_appendix=1` so every memory
change triggers immediate recompilation. The threshold analysis shows
break-even at ~0.7-1.0 requests — appendix mode provides zero cache
benefit with the current rendering, so recompiling immediately is
strictly better.

File: `src/memoryhub_core/services/compilation.py`, function
`should_recompile()`, parameter `min_appendix` default from 5 to 1.

After implementing, run `python scripts/validate-prefix-cache.py --scenario immediate_recompile`
to validate.

### 3. Fix SDK `Memory` model for stub results

The `Memory` model requires `content: str` and `owner_id: str`, but the
server returns appendix entries as stubs (when token budget is exceeded)
without these fields. This causes `ValidationError` when searching with
`mode="full"` (the default) and the token budget degrades entries.

Fix: make `content` and `owner_id` optional with defaults
(`content: str = ""`, `owner_id: str = ""`), or split into separate
`MemoryFull` / `MemoryStub` models.

### 4. Downstream fips-agents template update

The fips-agents team has the SDK v0.5.0 migration read-out (delivered
this session). They need to update `memory.py`, `.memoryhub.yaml`, and
the `/add-memory` slash command. This is their work, not ours — track
whether they've picked it up.

## Completed this session

- **#184** — SDK `api_key`/`server_url` backward-compat shims shipped in
  v0.5.0. Published to PyPI. 88 tests, lint clean.
- **#183** — API key auth formalized in `docs/governance.md`. Named as
  first-class auth method with ConfigMap registry, security properties,
  and OAuth 2.1 upgrade path documented.
- **#185** — vLLM prefix cache validation complete. Validation script
  (`scripts/validate-prefix-cache.py`) with 5 baseline + 5 follow-up
  scenarios, per-request `cached_tokens` instrumentation, Prometheus/Thanos
  integration, and model auto-detection. Findings doc written for vLLM
  team audience.

### #185 validation results

Tested against two models on the cluster:

| Scenario | Granite 3.3 8B (v0.19.0) | GPT-OSS 20B (v0.13.0+rhai19) |
|----------|--------------------------|------------------------------|
| Stable prefix (warm) | 864/879 = 98.29% | 944/956 = 98.74% |
| Append-only (first) | 16/897 = 1.78% FAIL | 80/957 = 8.36% FAIL |
| Recompile miss | 16/824 = 1.94% | 256/795 = 32.20% |
| Recompile recovery | 816/824 = 99.03% | 784/795 = 98.62% |
| Block granularity | 800/827 = 97.84% | 784/798 = 98.25% |

Key findings:
- Stable prefix caching works (98-99% hit rate). Design is sound.
- Append-only mode is broken — `get_injection_block()` byte-stability gap.
- Recompile threshold of 5 is too high; lower to 1 as interim fix.
- 16-token block granularity confirmed. Partial block waste = `tokens mod 16`.
- GPT-OSS recompile preserved 32% prefix (vs 2% Granite) — high-weight
  memories staying at top means partial reuse happens naturally.

## Context

- SDK is at v0.5.0 on PyPI (v0.5.1 unreleased: empty-url normalization fix)
- CLI at v0.3.0, no changes needed
- #176 (first 3 users) still deprioritized
- Cluster has Prometheus monitoring via Thanos Querier with `metrics-reader`
  ServiceAccount. Validation script supports `PROMETHEUS_URL` and
  `PROMETHEUS_TOKEN` env vars for aggregate metrics.

## Cluster state

- Granite 3.3 8B: `granite-model` namespace, vLLM v0.19.0,
  `--enable-prefix-caching --enable-prompt-tokens-details --enable-server-load-tracking`
- GPT-OSS 20B: `gpt-oss-model-2` namespace, vLLM v0.13.0+rhai19,
  fp8_e4m3 KV cache, 154k GPU blocks
- MCP server: `memory-hub-mcp` namespace, compilation epoch 18+ (Granite) / 21 (GPT-OSS post-validation)
- DB: `memoryhub-db` namespace, migrations in sync
- Monitoring: Thanos Querier at `thanos-querier-openshift-monitoring.apps.cluster-n7pd5...`
