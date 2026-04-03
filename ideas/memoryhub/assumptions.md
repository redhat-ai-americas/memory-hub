# Assumptions

These are things we're treating as true but haven't validated. Each one is a potential surprise if it turns out to be wrong.

**OpenShift AI will continue its trajectory toward supporting multi-agent workloads.** The signals are strong — Kagenti, Llama Stack integration, the Agent Sandbox CRD in SIG Apps — but RHOAI's roadmap could shift. If multi-agent support stalls or takes a different architectural direction, MemoryHub's value proposition changes.

**The RHOAI engineering team will be receptive to a well-proven memory component.** This is not guaranteed. They might have their own plans for memory, they might think it's too early, or they might prefer a different architectural approach. The mitigation is straightforward: build something that works so well on its own that the conversation is easy. But we should be prepared for "not right now" as an answer.

**Milvus and Neo4j are viable on OpenShift.** Both have operators or Helm charts, and both run in containers. But we haven't validated FIPS compliance for either one. If Milvus doesn't support FIPS, pgvector on PostgreSQL is the fallback (PostgreSQL has solid FIPS support on RHEL). If Neo4j doesn't support FIPS... we're less sure about alternatives for graph storage. This needs validation early.

**Grafana's node graph panel is sufficient for memory relationship visualization.** We've seen it work for small datasets, but we haven't tested it with thousands of memory nodes and their relationships. If it doesn't scale visually, we might need a different approach to the graph visualization — but Grafana remains the platform either way.

**MCP will continue to gain adoption as the standard agent tool protocol.** Every major AI tool vendor has adopted or announced MCP support. This feels like a safe bet, but protocol standards can fragment. If MCP forks or a competitor emerges, we'd need to support multiple interfaces.

**Enterprises will increasingly need agent memory governance as AI agent deployments scale.** The EU AI Act enforcement starting August 2026 may accelerate this. We're betting on a market that's emerging but not yet established. If enterprises don't scale agent deployments as fast as expected, the urgency for governance decreases.

**Memory promotion (user to organizational) can be done effectively by an LLM agent analyzing patterns.** This is conceptually sound — "30 users all taught their agents the same thing" is a detectable pattern. But we haven't proven it works at scale, and the quality of promoted memories is critical. A bad organizational memory that propagates to every agent is worse than no organizational memory at all.
