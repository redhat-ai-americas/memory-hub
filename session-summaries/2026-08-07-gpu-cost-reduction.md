# Session Summary — 2026-08-07 · ops · GPU cost reduction (4 nodes to 1)

**Plan:** ad-hoc user request   **Commits:** none (ops-only, no code changes)
**Deployed:** cluster config change (MachineSet scaled)   **Model:** Opus 4.6 (1M)

## Plan vs. actual
Planned: audit GPU nodes and models, shut down unneeded LLMs, reduce to one GPU node. Shipped: exactly that. Slipped: none.
Scope: stayed in scope.

## Shipped
- Scaled 3 LLM deployments to 0: Gemma 4 (E4B-it), GPT-OSS 20B, Ministral 3 14B (`gemma-model`, `gpt-oss-model`, `mistral-model` namespaces)
- Removed GPU request from `granite-reranker` deployment so it runs on CPU, colocated with embedding on one node
- Cleaned up 8 failed pods across 5 namespaces
- Cordoned and drained 3 GPU nodes (`ip-10-0-19-78`, `ip-10-0-27-130`, `ip-10-0-43-216`)
- Scaled MachineSet `gpu-cluster-n7pd5-7kws6-worker-us-east-2a` from 4 to 1 (3 g6e.4xlarge instances terminated)

## Verification & confidence
- Verified both surviving services (embedding + reranker) running on `ip-10-0-47-1` before draining
- Confirmed 3 machines entered `Deleting` phase and the surviving machine stayed `Running`
- Confidence: high -- MachineSet state confirmed, no code to break

## Judgment calls & deviations
- Removed GPU request from reranker rather than trying to share the GPU (each service requested 1 full GPU; embedding uses 579 MiB, Gemma 4 uses 42 GB -- no room to share)
- Chose to scale MachineSet directly rather than waiting for cluster autoscaler (user requested manual drain to confirm node reduction)

## Backlog delta
No issues filed or closed. No memory changes.

## Drift & forward-collisions
- Backward -- SOC demo (`demos/soc-demo/`) was using Gemma 4 for inference in prior sessions. With Gemma 4 scaled to 0, the demo's LLM endpoint will need reconfiguration if resumed. No issue filed since the demo can use external LLM APIs.
- Forward -- none.

## For the reviewer
- Sanity-check: reranker-on-CPU performance. TEI reranker should work fine on CPU but latency will be higher than GPU. Worth a quick smoke test of search-with-rerank if reranking quality matters for current work.
- Thin verification: did not smoke-test the reranker endpoint after moving to CPU. The pod is Running but didn't verify inference responses.
- Wants guidance: none.

## Risks / watch-fors
- LLM deployments are at 0 replicas, not deleted. Scaling them back up will fail until the MachineSet is scaled back (no GPU nodes available for new LLM pods).
- Reranker latency on CPU may be noticeably slower for large result sets. Monitor if search quality degrades.
