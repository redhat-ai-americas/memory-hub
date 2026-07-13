# Cluster Capacity -- mcp-rhoai

## Node Inventory (2026-07-12)

| MachineSet | Instance Type | Replicas | CPU | RAM | GPU | Notes |
|---|---|---|---|---|---|---|
| cluster-n7pd5-7kws6-worker-us-east-2a | (standard) | 2 | 16 | 64Gi | - | General workloads |
| gpu-cluster-n7pd5-7kws6-worker-us-east-2a | (GPU) | 2 | 16 | 128Gi | 1x per node | Embedding, reranker, vLLM |
| a100-cluster-n7pd5-7kws6-worker-us-east-2a | (A100) | 0 | - | - | - | Scaled to 0 |
| eval-gpu-cluster-n7pd5-7kws6-worker-us-east-2a | (eval GPU) | 0 | - | - | - | Scaled to 0 |
| h200-cluster-n7pd5-7kws6-worker-us-east-2a | (H200) | 0 | - | - | - | Scaled to 0 |

3 control-plane nodes (4 CPU, 16Gi each).

## Capacity Decision (2026-07-12)

**Context:** Eval jobs need 450m CPU. Two standard workers were at 98-99% CPU
allocation, blocking job scheduling.

**Actions taken:**
- Scaled `llamastack` deployment to 0 (34 orphaned/crashed pods from prior
  project, all non-functional). Freed ~1500m on ip-10-0-5-112.
- Scaled `librechat-fips` to 0 (all 3 components: app, mongodb, meilisearch).
  Freed ~500m on ip-10-0-50-241. LibreChat not needed for current work.

**Result:** ~2000m CPU freed across standard workers. No new nodes required.
GPU nodes (2x, at 3% and 29% CPU) are not constrained.

**Not done:**
- No new GPU node (g6e with L40S) added -- not GPU constrained.
- No new standard worker added -- freed capacity is sufficient.

**To restore later:**
```bash
oc scale deployment/llama-stack --replicas=1 --context mcp-rhoai -n llamastack
oc scale deployment/librechat-librechat --replicas=1 --context mcp-rhoai -n librechat-fips
oc scale deployment/librechat-mongodb --replicas=1 --context mcp-rhoai -n librechat-fips
oc scale statefulset/librechat-meilisearch --replicas=1 --context mcp-rhoai -n librechat-fips
```
