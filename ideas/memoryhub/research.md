# Landscape Research (April 2026)

A survey of what's out there and where the gaps are. This isn't exhaustive, but it covers the major players and the academic work that's most relevant to what we're building.

## Existing solutions

**Mem0** (51.8k stars, Apache 2.0) is the most popular open-source memory layer right now. It has a hybrid vector+graph+KV architecture, MCP support, and an enterprise cloud offering with SOC2/HIPAA compliance. The problem for us: graph memory, analytics, and governance features are cloud-only. There's no Kubernetes operator, no multi-agent coordination, and no temporal awareness. It's a good product for individual agent memory, but it doesn't solve the organizational memory problem.

**Letta/MemGPT** (21.9k stars, Apache 2.0) takes a unique approach from a NeurIPS 2023 paper — the LLM manages its own memory, maintaining editable memory blocks. Interesting conceptually, but it's Docker-centric with no compliance framework, no multi-agent shared memory, and memory operations consume tokens (which adds up). The self-managing memory idea is clever, though, and worth keeping in mind.

**Zep/Graphiti** positions itself as an enterprise "context engineering" platform built on Graphiti (MIT), their temporal knowledge graph engine. They have the strongest temporal model in the market — bi-temporal validity intervals, hybrid retrieval without LLM calls at query time. If any existing solution is closest to what we want for temporal awareness, it's Zep. But it requires Neo4j, the full platform is commercial SaaS, and there's no K8s operator story.

**Cognee** (14.9k stars, Apache 2.0) is a knowledge engine with an ECL pipeline, two-layer memory, 14 retrieval modes, and self-improving memory via pruning and reweighting. They raised $7.5M in seed funding, so they're well-resourced. But it's a young project with no enterprise compliance story and no Kubernetes narrative.

**Hindsight** (7.1k stars, MIT) emphasizes learning — retain, recall, reflect — plus auto-updating mental models. It's the first solution to cross 90% on LongMemEval, which is impressive. But the OSS/commercial boundary is unclear and there's no enterprise compliance.

**Redis Agent Memory Server** (218 stars, MIT) has a clean two-tier working+long-term memory with REST+MCP interface. It's a natural Kubernetes fit since the Redis Operator exists. But it's very early stage with no graph memory and no governance.

## Key academic work

The **"Governed Memory" paper** (March 2026, arXiv:2603.17787) is the most directly relevant academic work to what we're building. It addresses memory governance for multi-agent systems and reports 99.6% fact recall with zero cross-entity leakage. It's in production at Personize.ai. We need to read this in detail — it likely has architectural insights we can learn from.

**"Multi-Agent Memory from Computer Architecture Perspective"** (arXiv:2603.10062) frames agent memory as a CS architecture problem with shared vs. distributed paradigms. Useful mental model even if we don't adopt their specific approach.

**MAGMA** (arXiv:2601.03236) proposes a multi-graph architecture for semantic, temporal, causal, and entity relations. The multi-graph approach resonates with our multi-tier vision, though we're thinking in terms of storage backends rather than graph types.

ICLR 2026 had a dedicated workshop on agent memory ("MemAgents"), which signals that the field has reached critical mass in the research community. The timing is good — we're building something the academic community is actively theorizing about.

## Kubernetes landscape

**Kubernetes Agent Sandbox** (SIG Apps) introduced a new AgentSandbox CRD for stateful agent workloads. It's focused on agent execution infrastructure, not memory. Relevant as adjacent infrastructure but not competitive.

**Kagenti** (Red Hat Emerging Technologies) is a K8s-native agent deployment system with a Component CRD, identity sidecars, and zero-trust networking. It handles the "how do agents run" question but has no memory component. MemoryHub would be a natural complement to Kagenti.

**OpenShift AI** itself integrates Llama Stack with built-in memory/tools/RAG concepts, a provider model for backends, and KServe for serving. It has the agent infrastructure but no dedicated memory component. This is exactly the gap MemoryHub fills.

## The whitespace

Nobody has built a Kubernetes-native agent memory operator. Nobody ships multi-agent memory governance in open source. Nobody provides memory-specific observability through standard K8s monitoring. Nobody offers FIPS-compliant memory with forensics capabilities.

OpenShift AI has the agent infra but no memory component. Kagenti has the deployment model but no memory. The academic community is publishing papers about governed memory but nobody's shipping it as infrastructure.

MemoryHub sits right in this gap.
