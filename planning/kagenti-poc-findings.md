# Kagenti + MemoryHub PoC: Findings Log

**Date:** 2026-04-23
**Cluster:** kagenti-memory-hub (OCP 4.20.18, AWS us-east-2, fresh RHPDS)
**Goal:** Deploy kagenti + MemoryHub from scratch, validate all three integration layers

## Issues Found

### 1. Kagenti installer requires `.secret_values.yaml` even when not needed

**Symptom:** `run-install.sh --env ocp` fails immediately with:
```
Secret values file '.../envs/.secret_values.yaml' not found.
```
The wrapper script warns "continuing without secrets" but the playbook's own `01_setup_vars.yaml` task has a stricter check that fails.

**Workaround:** Copy `secret_values.yaml.example` to `.secret_values.yaml`.

**Action:** File issue on `kagenti/kagenti`. The wrapper and playbook disagree — either the playbook should tolerate a missing file when the wrapper already warned, or the wrapper should not say "continuing without secrets" if the playbook will fail.

---

### 2. SPIFFE IdP setup job uses HTTP but OIDC discovery provider only serves HTTPS

**Symptom:** `kagenti-spiffe-idp-setup-job` loops for 30 attempts with:
```
Connection to spire-spiffe-oidc-discovery-provider...svc.cluster.local timed out. (connect timeout=5)
```
The job's Python script connects to port 80 (HTTP), but the `spire-spiffe-oidc-discovery-provider` Service only exposes port 443 (HTTPS).

**Verified:** `urllib.request.urlopen('https://...:443/keys')` from the job pod returns 200 with valid JWKS.

**Impact:** Non-blocking — the ansible playbook continued past it (132 tasks ok, 0 failed), and all other components installed successfully. The job will eventually exhaust retries but doesn't gate the rest of the install.

**Action:** File issue on `kagenti/kagenti`. The job's health check URL should use `https://` and port 443, matching the service definition. Possible PR — the fix is likely a one-line URL change in the job's Python script or its ConfigMap.

---

### 3. Helm v4 incompatibility (known, documented)

**Symptom:** `run-install.sh` exits early if Helm v4 is detected.

**Impact:** Users with Helm v4 (now the default from Homebrew) must install Helm v3 alongside it.

**Workaround:** `PATH="/opt/homebrew/Cellar/helm@3/3.20.1/bin:$PATH"` before running the installer.

**Action:** Already documented in their README. No issue needed — but worth noting that Helm v4 is now the default, so this will affect more users over time.

---

### 4. NVIDIA ClusterPolicy requires more fields than documented

**Symptom:** Minimal ClusterPolicy with just `driver`, `toolkit`, `devicePlugin`, `dcgmExporter` is rejected:
```
spec.daemonsets: Required value
spec.dcgm: Required value
spec.gfd: Required value
spec.nodeStatusExporter: Required value
```

**Workaround:** Add empty/enabled stanzas for all required fields (`daemonsets: {}`, `dcgm.enabled: true`, `gfd.enabled: true`, `nodeStatusExporter.enabled: true`).

**Action:** This is an NVIDIA operator issue, not kagenti. Note for our docs if we include GPU setup instructions.

---

### 5. MemoryHub deploy-full.sh hardcodes `mcp-rhoai` context

**Symptom:** `deploy-full.sh` has `--context mcp-rhoai` hardcoded in ~53 `oc` commands.

**Workaround:** The deploy agent sed-replaced all occurrences to `kagenti-memory-hub`.

**Action:** File issue on `redhat-ai-americas/memory-hub`. Parameterize the context: `CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"` at the top, then `--context "$CONTEXT"` throughout. This makes the script cluster-agnostic.

---

### 6. UBI9 container runs as non-root — venv creation fails without USER 0

**Symptom:** BuildConfig build fails with:
```
error: failed to create directory `/app/agents/memoryhub-test-agent/.venv`: Permission denied (os error 13)
```
The `COPY . /app/.` creates root-owned files, but UBI9's python-311 image runs as user 1001 by default. `uv sync` can't create the venv.

**Fix:** `USER 0` before COPY/RUN, then `chmod -R g=u` on the venv, then `USER 1001` for runtime. Standard OpenShift pattern.

**Action:** This is a known pattern, not a bug. But worth noting in the test agent's README for anyone reproducing. The CLAUDE.md in memory-hub already documents this (chmod 644 before builds).

---

## Actions Taken (chronological)

| Time | Action | Why |
|------|--------|-----|
| 11:08 | Fork kagenti/kagenti and kagenti/adk | Setup |
| 11:10 | ADK clone via SSH (HTTPS returned 500 — GitHub processing fork of large repo) | GitHub transient issue |
| 11:11 | Create `.secret_values.yaml` from example | Work around finding #1 |
| 11:12 | Start kagenti install with Helm v3 PATH override | Work around finding #3 |
| 11:12 | Create `feature/memory-store` branch in ADK fork | Track B |
| 11:15 | Write MemoryStore protocol (`memory_store.py`) | Track B |
| 11:18 | Write MemoryHub implementation (`memoryhub_memory_store.py`) | Track B |
| 11:20 | Add `memoryhub` optional dependency to adk-py pyproject.toml | Track B |
| 11:25 | Write test agent (`memoryhub-test-agent/`) | Track B |
| 11:28 | Install completed — kagenti-deps chart + kagenti chart + RHOAI DSC | Track A (16m 12s) |
| 11:30 | Create GPU MachineSet (g5.2xlarge) | Track A2 |
| 11:30 | Install NFD and NVIDIA GPU operators | Track A2 |
| 11:30 | Start MemoryHub deployment (via terminal-worker agent) | Track A4 |
| 11:32 | Create NFD instance | Track A2 |
| 11:32 | Create NVIDIA ClusterPolicy (first attempt rejected — finding #4) | Track A2 |
| 11:33 | Fix ClusterPolicy with all required fields | Track A2 |
| 11:38 | GPU node Ready, NVIDIA drivers installed, 1x GPU allocatable | Track A2 complete |
| 11:38 | MemoryHub MCP server running, auth server running | Track A4 mostly complete |
| 11:40 | Create BuildConfig for test agent (Git source, on-cluster build) | Track B5 |
| 11:40 | Start test agent build on-cluster | Track B5 |
| 11:42 | Build failed — venv permission denied (finding #6) | Track B5 |
| 11:43 | Fix Containerfile: USER 0, chmod g=u, USER 1001 | Track B5 |
| 11:43 | Push fix, restart build | Track B5 |
| 11:45 | Build 2 completed successfully | Track B5 |
| 11:46 | MemoryHub deploy agent completed (full stack) | Track A4 |
| 11:47 | Deploy embedding model + gpt-oss-20b | Track A3 |
| 11:48 | Layer 1: MCPServerRegistration failed — wrong API group (finding #9) | Track C1 |
| 11:48 | Layer 1: Fixed with `mcp.kagenti.com/v1alpha1` | Track C1 |
| 11:49 | Layer 1: Gateway hostname mismatch — HTTPRoute not accepted (finding #9 extended) | Track C1 |
| 11:50 | Test agent deployed, health check passes, agent card visible | Track C3 |
| 11:51 | Model pods Error — vLLM `--task=embedding` deprecated, HF_HOME permission denied (finding #10) | Track A3 |
| 11:52 | Fix models: `vllm serve` syntax, `--task=embed`, `HF_HOME=/tmp/hf_cache` | Track A3 |
| 11:56 | Models still failing — vLLM `latest` also needs `/.cache/vllm` writable, `--device=cpu` not working | Track A3 |
| 11:58 | Fix: pin `vllm/vllm-openai:v0.8.5`, use `python3 -m vllm.entrypoints...`, set `HOME=/tmp`, `VLLM_CACHE_ROOT=/tmp/vllm_cache` | Track A3 |
| 12:00 | v0.8.5 doesn't know `gpt_oss` architecture; latest has cache permission issues | Track A3 |
| 12:02 | Switched to proven manifests from workshop-setup: RHOAI vLLM image (`rhaiis/vllm-cuda-rhel9:3`) for LLM, HuggingFace TEI for embedding | Track A3 |
| 12:03 | Updated agent credentials to point at correct service URLs in new namespaces | Track C3 |
| 12:05 | Switched to proven workshop-setup manifests (RHOAI vLLM + HuggingFace TEI) | Track A3 |
| 12:07 | Embedding model ready (TEI, 1/1 Running) | Track A3 |
| 12:07 | Configured MCP server with `MEMORYHUB_EMBEDDING_URL` | Track A4 |
| 12:08 | LLM failed — NVIDIA driver too old for RHOAI vLLM (CUDA 12.4 vs 12.8+ required) (finding #11) | Track A3 |
| 12:09 | Upgraded GPU Operator subscription from v24.9 → v26.3 channel | Track A2 |
| 12:20 | New GPU driver installed (v26.3), GPU allocatable again | Track A2 |
| 12:28 | gpt-oss-20b Ready (1/1) — model loaded, health checks passing | Track A3 |
| 12:30 | MemoryHub configured with embedding URL | Track A4 |
| 12:33 | A2A request reached agent but hit `coroutine has no attribute search` — DI async issue (finding #12) | Validation |
| 12:35 | Fix: lazy _MemoryProxy pattern for ADK Depends compatibility | Track B |
| 12:36 | Rebuild triggered (build 3) | Track B5 |
| 12:37 | Build 3 complete, agent restarted | Track B5 |
| 12:40 | A2A request: memory search WORKS (0 results), LLM call fails (vLLM restart race) | Validation |
| 12:45 | LLM fully loaded, /v1/models responds with gpt-oss-20b | Track A3 |
| 12:46 | Increased liveness probe initialDelaySeconds to 600s (triggers rollout) | Track A3 |
| 12:47 | Waiting for LLM model reload after rollout | Track A3 |
| 12:58 | LLM loaded but inference fails: `fp8e4nv not supported in this architecture` (finding #13) | Track A3 |
| 12:59 | Patched: removed `--kv-cache-dtype fp8_e4m3`, reduced `--max-model-len` to 8192 for A10G | Track A3 |
| 13:12 | LLM ready (1/1), inference working | Track A3 |
| 13:28 | **END-TO-END SUCCESS: Agent wrote memory to MemoryHub** (id=7fadd4e8...) | Validation |
| 13:29 | **Agent recalled 1 memory** when asked about containerization | Validation |
| 13:31 | **Pod restart test PASSED** — new pod found memory written before restart | Validation |
| 13:45 | Created g6e.4xlarge MachineSet for L40S GPU | GPU upgrade |
| 13:50 | L40S node Ready, NVIDIA drivers installed, 1x GPU allocatable | GPU upgrade |
| 13:55 | Deployed gpt-oss-20b on L40S with FP8 KV cache + 131K context | GPU upgrade |
| 14:05 | L40S inference working — FP8 KV cache works correctly | GPU upgrade |
| 14:11 | **L40S end-to-end test PASSED** — agent recalled memory via L40S-backed LLM | GPU upgrade |
| 14:12 | Scaled down A10G node | GPU upgrade |

### 7. MemoryHub auth server imagestream digest timing issue (#88)

**Symptom:** During deploy, the auth server pod's running digest temporarily differs from the imagestream digest, triggering a verification warning.

**Impact:** Non-blocking — the pod is running and healthy. Known issue (#88).

**Action:** Existing issue, no new filing needed.

---

### 8. OdhApplication CRD not present on kagenti-installed RHOAI (minimal profile)

**Symptom:** MemoryHub's deploy script tries to create an OdhApplication tile for the RHOAI dashboard, but the CRD doesn't exist because the minimal DSC profile removes the dashboard component.

**Impact:** Non-blocking — the tile creation is skipped, but the script should handle this gracefully.

**Action:** File issue on `redhat-ai-americas/memory-hub`. The deploy script should check for CRD existence before attempting to create the OdhApplication resource.

---

### 9. MCPServerRegistration API group is `mcp.kagenti.com`, not `mcp.kuadrant.io`

**Symptom:** Applying MCPServerRegistration with `apiVersion: mcp.kuadrant.io/v1alpha1` fails:
```
no matches for kind "MCPServerRegistration" in version "mcp.kuadrant.io/v1alpha1"
```

**Actual CRDs on cluster:** `mcpserverregistrations.mcp.kagenti.com`, `mcpgatewayextensions.mcp.kagenti.com`, `mcpvirtualservers.mcp.kagenti.com`

**Impact:** The design proposal and kagenti's own gateway docs reference the Kuadrant API group. The CRDs have been moved to `mcp.kagenti.com` — either recently or specific to OCP installs.

**Fix:** Use `apiVersion: mcp.kagenti.com/v1alpha1`. Also note the `path` field (defaults to `/mcp`) — MemoryHub serves at `/mcp/` so this needs to be set explicitly.

**Action:** Update our design proposal's YAML examples. Check if kagenti's gateway.md docs are stale.

**Additional finding:** The MCPServerRegistration controller requires the HTTPRoute to be actively accepted by the Gateway (parent status populated). On OCP, the `mcp-gateway` Gateway listeners are configured with Kind/dev hostnames (`mcp.127-0-0-1.sslip.io`, `*.mcp.local`), and the Istio gateway rejects routes that don't match these hostnames. This means registering external MCP servers requires either:
1. Reconfiguring the Gateway listeners with appropriate hostnames for the cluster
2. Adding the MCPServerRegistration in the same namespace as the broker (`mcp-system`)
3. Using the broker's direct config instead of the CRD path

**This is a significant finding for the design proposal** — Layer 1 gateway registration is harder than anticipated on production OCP clusters because the gateway hostnames are dev-oriented. Worth filing as a kagenti issue.

---

### 10. vLLM latest image: `--task=embedding` removed, `/.cache` not writable on OpenShift

**Symptom:** Embedding model fails with `unrecognized arguments: --task=embedding`. LLM fails with `PermissionError at /.cache when downloading`.

**Fixes:**
- Use `vllm serve <model>` command syntax (not `--model` flag)
- Use `--task=embed` (not `--task=embedding`)
- Set `HF_HOME=/tmp/hf_cache` env var so HuggingFace downloads go to a writable directory

**Key lesson:** Don't use upstream `vllm/vllm-openai` on OpenShift — use `registry.redhat.io/rhaiis/vllm-cuda-rhel9:3` (RHOAI's image, v0.13.0) for LLMs and `ghcr.io/huggingface/text-embeddings-inference:cpu-1.6` for embeddings. The upstream images have multiple cache-path permission issues on OpenShift's non-root UID model and the latest tag is too unstable. The RHOAI image is production-hardened for OpenShift.

**Action:** Not a kagenti or MemoryHub issue — document in our PoC for reproducibility. The working manifests live in `workshop-setup/model/`.

---

### 11. NVIDIA GPU Operator v24.9 driver too old for RHOAI vLLM v0.13.0

**Symptom:** vLLM (from `rhaiis/vllm-cuda-rhel9:3`) fails with:
```
RuntimeError: The NVIDIA driver on your system is too old (found version 12040)
```
GPU Operator v24.9 ships driver version 9.6 (CUDA 12.4). RHOAI's vLLM 0.13.0 requires CUDA 12.8+.

**Fix:** Upgrade GPU Operator subscription channel from `v24.9` to `v26.3`. The newer channel ships a driver compatible with CUDA 12.8+.

**Action:** Note for any kagenti + RHOAI model serving setup. The GPU Operator channel must match the RHOAI vLLM image's CUDA requirements. This is a compatibility matrix issue — worth documenting.

---

### 12. ADK Depends doesn't await async dependency callables

**Symptom:** Agent handler receives a coroutine object instead of the resolved dependency:
```
AttributeError: 'coroutine' object has no attribute 'search'
```

**Root cause:** `Depends.__call__` (line 48 in `dependencies.py`) calls the dependency callable synchronously and doesn't await the result. If the callable is `async def`, the return value is an unawaited coroutine.

**Fix:** Use a synchronous callable that returns a lazy-initializing proxy (`_MemoryProxy`). The proxy resolves the async `store.create()` on first method call.

**Action:** This is a gotcha for anyone writing custom Depends providers for ADK. The existing extension servers avoid it because they're `BaseExtensionServer` subclasses with a `lifespan()` method, not plain async callables. Worth documenting or fixing in the ADK — could file an issue suggesting that `Depends.__call__` detect and await coroutines.

---

### 13. gpt-oss-20b manifest uses FP8 KV cache, incompatible with A10G GPUs

**Symptom:** Inference fails with:
```
ValueError("type fp8e4nv not supported in this architecture. The supported fp8 dtypes are ('fp8e4b15', 'fp8e5')")
```
The `--kv-cache-dtype fp8_e4m3` flag requires Ada Lovelace (L40S, RTX 4090) or Hopper (H100) GPUs. The A10G (Ampere, compute capability 8.6) on g5 instances doesn't support it.

**Fix:** Remove `--kv-cache-dtype fp8_e4m3` from the args. Also reduce `--max-model-len` from 131072 to 8192 since the 20B model without FP8 KV cache needs more VRAM per token.

**Action:** The `workshop-setup/model/gpt-oss-20b.yaml` manifest was written for a cluster with L40S/H100 GPUs. Need a separate manifest or auto-detection for A10G/Ampere GPUs. Worth updating the workshop setup docs.

---

## Validation Results

| Layer | Test | Result |
|-------|------|--------|
| 1 | MCP Gateway registration | Blocked — gateway hostnames are dev-oriented (finding #9) |
| 2 | Keycloak identity federation | Not attempted (deferred to next session) |
| 3 | Agent writes memory via MemoryStore | **PASS** — memory written with ID 7fadd4e8-... |
| 3 | Agent recalls memory via semantic search | **PASS** — found 1 relevant memory |
| 3 | Memory survives pod restart | **PASS** — new pod found memory from before restart |
| All | MemoryStore DI integration with ADK Depends | **PASS** (after lazy proxy fix) |

## PRs to Submit

- [ ] **kagenti/kagenti**: Fix SPIFFE IdP setup job HTTP→HTTPS (#2)
- [ ] **kagenti/kagenti**: Make secret_values_file optional in playbook (#1)
- [ ] **kagenti/kagenti**: Update gateway docs — API group is `mcp.kagenti.com`, not `mcp.kuadrant.io` (#9)
- [ ] **kagenti/adk**: Document that Depends doesn't await async callables (#12)
- [ ] **redhat-ai-americas/memory-hub**: Parameterize cluster context in deploy-full.sh (#5)

## Issues to File

- [ ] **kagenti/kagenti**: SPIFFE IdP setup job connects via HTTP:80 but service only serves HTTPS:443
- [ ] **kagenti/kagenti**: Installer secret_values_file check inconsistent between wrapper and playbook
- [ ] **kagenti/kagenti**: MCP Gateway hostnames are Kind/dev defaults, can't register external MCP servers on OCP
- [ ] **redhat-ai-americas/memory-hub**: deploy-full.sh hardcodes mcp-rhoai context
- [ ] **redhat-ai-americas/memory-hub**: deploy-full.sh should check for OdhApplication CRD before creating tile
