# When Agent Memory Becomes a Platform Concern

**Wes Jackson | April 2026**

---

There are two kinds of people building with AI agents right now.

The first group builds *with* agents. They use Claude Code, Cursor, or Copilot as individual productivity tools. Their agents run locally, maintain context across sessions through files on disk, and serve a single developer on a single machine. This is a large and growing population, and their needs are well served by the current generation of agent harnesses.

The second group builds *systems of agents* for enterprise platforms. Their agents run as containers in Kubernetes clusters, coordinate across teams, and operate under governance requirements that no single-user tool was designed to meet. For this group, the question of where agent memory lives is not a feature request. It is an infrastructure decision.

## The harness tier and the platform tier

As agent architectures mature, their capabilities are splitting into two tiers in a pattern that distributed systems engineers have seen before. Consider how each concern evolves as you move from a single developer's laptop to a fleet of agents on a platform.

Tools started as local function calls wired into the agent loop. MCP emerged when cross-agent interoperability became necessary. Knowledge started as local context files and RAG over personal documents. Enterprise RAG with access controls followed when organizations needed shared retrieval. Authentication started as hardcoded API keys in environment variables. OAuth and OIDC integration followed when agents needed to act on behalf of users within governed systems.

Memory is on the same trajectory. Local, per-agent memory in the harness works well today. Governed, shared memory across agents and harnesses does not yet exist as a standard platform capability, but the pressure for it is building.

Gartner's August 2025 "Innovation Insight: AI Agent Development Frameworks" [lists memory management](https://solace.com/blog/ai-agent-dev-frameworks-gartner/) as a core framework capability alongside planning, tool use, and multi-agent coordination. But even Gartner treats memory as a framework concern, not yet as a platform concern. That framing captures where the industry is. It does not capture where the industry is going.

## Why this is not just RAG

Someone will reasonably argue that enterprise RAG already fills the gap for multi-agent knowledge sharing. It does not, and the distinction matters.

RAG retrieves documents. It answers the question, "What does the manual say?" Governed shared memory tracks a fundamentally different kind of knowledge: learned preferences, operational decisions, provenance chains, access-controlled observations, and contradiction signals between agents that have drawn different conclusions from the same evidence. Memory answers the question, "What has this agent, or this team of agents, learned?"

The retrieval mechanism can overlap (vector search appears in both), but the data model is different. RAG indexes static corpora. Memory is dynamic, append-heavy, branching, and governed. It needs consistency semantics, access control, audit trails, and retention policies. These are database concerns, not search concerns.

## Two writers making the case

Harrison Chase recently argued in ["Your Harness, Your Memory"](https://www.langchain.com/blog/your-harness-your-memory) that memory creates lock-in that model quality alone cannot. An email assistant that loses its accumulated preferences requires complete retraining, not because the model changed, but because the memory vanished. Chase's conclusion: own your memory in an open harness.

Sarah Wooders of Letta made a complementary argument: memory is not a plugin you bolt onto an agent. It is the harness itself. ["Asking to plug memory into an agent harness is like asking to plug driving into a car."](https://x.com/sarahwooders/status/2040121230473457921) The harness controls what enters the context window, what survives compaction, and how memory metadata is presented to the model. An external service cannot make those decisions.

Both are correct for the single-agent, single-user tier. Their arguments also implicitly reveal the gap: neither addresses what happens when multiple agents, across multiple harnesses, need to share governed knowledge on an enterprise platform. The harness owns context management. It does not follow that the harness should own the knowledge itself.

## Early investor signal

The investment landscape is starting to reflect this shift, modestly but notably for how early the category is. [Mem0 raised $24M](https://techcrunch.com/2025/10/28/mem0-raises-24m-from-yc-peak-xv-and-basis-set-to-build-the-memory-layer-for-ai-apps/) from Y Combinator, Peak XV, and Basis Set. [Letta raised a $10M seed](https://www.prnewswire.com/news-releases/berkeley-ai-research-lab-spinout-letta-raises-10m-seed-financing-led-by-felicis-to-build-ai-with-memory-302257004.html) led by Felicis. [Cognee raised 7.5M euros in Berlin](https://www.cognee.ai/blog/cognee-news/cognee-raises-seven-million-five-hundred-thousand-dollars-seed). [Supermemory raised roughly $3M](https://techcrunch.com/2025/10/06/a-19-year-old-nabs-backing-from-google-execs-for-his-ai-memory-startup-supermemory/) with Jeff Dean on the cap table. [Interloom raised $16.5M in Munich](https://fortune.com/2026/03/23/interloom-ai-agents-raises-16-million-venture-funding/). That is over $60M into pure-play agent memory startups, a category that barely had a name eighteen months ago.

The numbers are modest against the billions flowing into agentic AI broadly. The signal is in who is investing and how they are framing it. [Bessemer's AI Infrastructure Roadmap](https://www.bvp.com/atlas/ai-infrastructure-roadmap-five-frontiers-for-2026) explicitly identifies the memory and context layer as a differentiation frontier for 2026. When tier-one firms start writing thesis posts about a category, capital formation tends to accelerate.

## The platform choice point

For organizations deploying agents at scale, where you put agent memory is an infrastructure decision with the same weight as where you put your data, your APIs, or your container workloads. Portability, governance, interoperability, and freedom to change providers all matter.

Cloudflare's [Project Think](https://blog.cloudflare.com/project-think/) is an architecturally impressive example of what platform-native memory looks like: per-agent SQLite on Durable Objects, tree-structured conversation history, typed memory providers, and zero-cost-when-idle economics. It is a compelling offering for teams committed to the Cloudflare platform. It also only runs on Cloudflare, with no mechanism for cross-platform portability or multi-agent sharing across environments.

That is a valid choice. It is not the only valid choice.

At the other end of the spectrum, Multica --- an open-source platform that manages coding agents across ten providers on a shared kanban board --- illustrates the demand side of the same gap. Multica has mature task orchestration, multi-provider dispatch, and human-agent collaboration. It does not have persistent cross-agent memory. The team tracks this explicitly as an open issue: "Agents have no persistent memory across issues. Each task starts fresh." The orchestration layer is production-ready. The memory layer does not yet exist.

Enterprises running agents across multiple platforms and multiple harnesses need memory that follows the protocol, not the platform. An open-source, platform-level memory layer built on open standards (MCP for transport, standard database primitives for governance) gives organizations the flexibility to avoid lock-in. This is not about any single provider's approach being wrong. It is about enterprises applying the same rigor to agent memory that they apply to every other infrastructure decision: where does the data live, who controls it, and what happens when you need to move?

## What comes next

The field has not yet decided whether agent memory is a harness feature or platform infrastructure. For developers building with a single agent on a laptop, the distinction is academic. For organizations building systems of agents on enterprise platforms, it is consequential.

The harness tier is well served today. The platform tier is mostly open ground. The companies and investors who see the platform layer early, and build bridges instead of moats, will shape what comes next.

---

*Wes Jackson builds governed memory infrastructure for AI agents on enterprise platforms.*
*[GitHub](https://github.com/rdwj) | [LinkedIn](https://linkedin.com/in/profjackson)*
