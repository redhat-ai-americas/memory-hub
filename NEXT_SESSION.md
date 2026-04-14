# Next Session Plan

## Priority: API key auth formalization + vLLM validation

### 1. SDK backward-compat api_key shim (#184) — DONE

Shipped in sdk v0.5.0. `api_key=` and `server_url=` are now accepted as
convenience aliases. When `api_key` is provided, the SDK calls
`register_session` on connect instead of using OAuth. Downstream
fips-agents template still needs updating (separate repo).

### 2. Formalize API key auth docs (#183)

No code changes — documentation and positioning only:
- Name "API key authentication" explicitly in docs
- Document the `memoryhub-users` ConfigMap as the user registry
- Document the env var toggle and the upgrade path to OAuth 2.1
- Update docs/governance.md auth section

### 3. Validate compilation epoch assumptions against real vLLM (#185)

Deploy a test workload against the cluster's vLLM endpoint with MemoryHub memory injection. Measure actual cache hit rates with identical memory sets, append-only growth, and recompilation scenarios. Validate the 16-token block granularity and the should_recompile threshold (30% / 5 entries).

## Context from this session

- #184 (api_key backward-compat shim) shipped in sdk v0.5.0
- #175 (cache-optimized assembly) shipped and deployed — compilation epochs with Valkey state, `raw_results` opt-out, `compilation_hash`/`compilation_epoch`/`appendix_count` in responses
- README rewritten with governance-first value proposition
- All test debt resolved: 254 MCP + 288 unit + 55 integration = 597 tests, 0 failures
- Integration test compose stack verified working (podman machine + podman-compose)
- #176 (first 3 users) deprioritized ~1 week — do not surface as "what to work on next"
- `should_recompile` threshold kept as-is (option A); #185 validates assumptions

## Cluster state

- MCP server: build 23, pod `memory-hub-mcp-69f8ffc58-kg2dh`, image sha256:76ca05dd...
- Cache-optimized assembly verified live (compilation_epoch: 1, compilation_hash present)
- DB: memoryhub-db namespace, migrations in sync
