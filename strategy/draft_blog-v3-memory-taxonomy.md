# Agent Memory Is Plural

*Four memory types, three storage shapes, one governance dimension, and the lines that decide what your harness builds versus what your platform should provide.*

> **[Medium subtitle field. Paste the italic line above into Medium's "subtitle" input, then delete this block before publishing.]**

![IMAGE PROMPT: A clean, editorial-style isometric illustration of an agent platform decomposed into multiple distinct subsystems sitting side by side: one labeled-area for governed memory (database cylinders with audit-trail glyphs and access gates), one for conversation persistence (a stack of chat-thread cards), one for compaction (a funnel narrowing a long scroll into a short summary tile), one for sandbox forensics (a glass-walled execution chamber with a logging tap). Above them, a thin "harness" layer with a small "working memory" cache embedded in it. Cool slate-and-blue palette with one warm accent color on the governed-memory subsystem. Sophisticated, minimal, no robots or faces, no text labels, no logos. Suitable as a Medium hero image for a thought-leadership post on agent infrastructure.](placeholder-hero.png)

A few weeks ago I [argued](https://medium.com/@wjackson_63436/when-agent-memory-becomes-a-platform-concern-4b6cd23af47f) that agent memory was splitting into a harness tier and a platform tier, and that organizations running agents at scale would have to make an infrastructure decision about where memory lives. That post left a question open. If platform memory is its own tier, what actually goes inside it? And how does the harness itself change shape once the platform takes on responsibilities the harness used to own?

The shorter the answer, the more wrong it is.

In the last two months, three serious memory systems have shipped or been announced. Oracle AI Agent Memory, ByteDance's [OpenViking](https://github.com/volcengine/OpenViking), and Cloudflare's [Project Think](https://blog.cloudflare.com/project-think/) each bundle "agent memory" into something concrete enough to deploy. They do not bundle the same things. Oracle includes conversation threads, message history, and durable extracted memories in a single SDK on a single database. OpenViking treats resources, memories, and skills as siblings in a filesystem-shaped namespace. Project Think wires per-agent SQLite into the harness runtime and keeps memory inside the agent loop.

The disagreement is not about which one is right. It is about what "agent memory" means in the first place. The category is one word covering at least three independent design dimensions, four different platform components, and a harness whose responsibilities have started getting fulfilled by services it does not own. This post is the cuts.

## Three orthogonal cuts

When a vendor or a paper says "agent memory," they usually mean one of these:

**Memory types**, the cognitive-science taxonomy. Working memory is the agent's active scratchpad and current-turn state. Semantic memory is durable facts about users, entities, and the world. Episodic memory is specific past experiences the agent can recall. Procedural memory is rules and learned procedures. This is the taxonomy [LangMem](https://blog.langchain.com/langmem-sdk-launch/) ships, that MAGMA's multi-graph proposal uses, and that [Oracle's recent post](https://blogs.oracle.com/developers/oracle-ai-agent-memory-a-governed-unified-memory-core-for-enterprise-ai-agents) articulates most cleanly: "These are not four different systems. They are four access patterns over the same underlying state."

**Access patterns**, the retrieval taxonomy. Top-k similarity over an embedding space. Exact-key lookup. Graph traversal with score propagation. Chronological scan with recency weighting. Two-stage retrieval where an LLM rewrites a query into typed sub-queries before the index is touched. This is what Mem0, Zep, OpenViking, and Letta differentiate on: not what they store, but how they search it.

**Storage shapes**, the database taxonomy. Vector indices, knowledge graphs, key-value stores, structured documents, files in a hierarchy, relational rows. The shape determines what is cheap and what is expensive. Vector indices are cheap for fuzzy similarity and expensive for temporal ordering. Graphs are cheap for relationships and expensive for full-text. Files are cheap for human inspection and expensive for cross-row queries.

These three cuts are orthogonal. Procedural memory can be stored as a key-value pair or as a vector. Episodic memory can be retrieved by similarity or by timestamp. A vector index can serve semantic recall, episodic search, or full-text fallback depending on what you put in it. Arguments about whether the right taxonomy has three categories or four or eight are arguments along one axis as if the other two did not exist.

The honest answer is that you need all three lenses. Pick the one that explains the trade-off you face. If you are arguing about cost, the storage shape matters most. If you are arguing about what the agent should retrieve, the access pattern matters most. If you are arguing about what to extract from a conversation in the first place, the cognitive type matters most.

![IMAGE PROMPT: An editorial diagram showing three transparent, overlapping geometric volumes intersecting in three-dimensional space, each in a slightly different cool tone (one labeled in the metaphor for "type", one for "access pattern", one for "storage shape"). The overlapping region in the center sits in a warm accent color, suggesting that any specific memory record sits at the intersection of all three. Cool slate-and-blue palette with one warm accent on the central intersection. No text labels, no logos.](placeholder-three-cuts.png)

## The fourth axis nobody puts in the diagram

Cutting across all three is governance. Who can read this memory, who can write it, what is the retention policy, how do we audit changes, how do we delete on request. This axis does not appear in cognitive-science taxonomies because it is an enterprise concern, not a model-of-the-mind concern. It is also the axis that turns "agent memory" from a research topic into a procurement decision.

A given memory record sits at the intersection. A procedural rule (type) about a specific customer (semantic content) retrieved by exact key (access pattern) stored as JSON (storage shape) under project scope with a ninety-day retention and full audit trail (governance). All four describe it. None of the four is the dimension. Calling the record "procedural" tells a developer how the agent uses it. Calling it "project-scoped, project-write, organizational-read" tells the platform how to handle it. Both are true, and the second is the one your security review will care about.

This is the part of the picture most cognitive-science-flavored taxonomies leave on the cutting-room floor. It is also the dimension that determines what kind of substrate you can ship.

## The structural fact

Tap your knee with a doctor's hammer. A signal travels to your spinal cord and forks. One branch flexes the quadriceps and kicks your foot out. The other goes to the brain, which spends a few hundred milliseconds asking what happened and whether it mattered. By then the kick is over. The reflex had to happen at the cord because the brain was too slow.

That is a useful frame for thinking about the harness, but it is not the load-bearing argument. The load-bearing argument is sharper.

**Working memory has exactly one place to live: the prompt the harness builds for the model on this turn.** Anywhere else is invisible to inference. This is not a design choice. It is a definitional constraint of how transformers work. Every inference call processes one input token sequence, generates output, and discards everything that was not in that sequence. CLAUDE.md exists on disk. To the model running this turn, it does not exist on disk. It exists either in training data (a hazy, weight-encoded recollection), or in this turn's prompt because the harness pulled it in, or it exists nowhere as far as inference is concerned. A skill, a local tool, an external memory service, a RAG corpus, a knowledge graph: these are all the same shape from the model's perspective. They are stubs the model has been told about (in context), and their content reaches the model only when they are invoked and the result is folded back into context.

The harness owns the act of assembling that context for each turn because the assembly is the only path by which any data outside training can reach the model.

Durable memory is the opposite. It can live almost anywhere. A markdown file in your repo. A SQLite database on a laptop. A vector index in pgvector. A managed service like Mem0, Letta, or Zep. A filesystem-shaped namespace like OpenViking. A converged database like Oracle. A Durable Object inside the harness runtime, like Cloudflare's Project Think. Each of these is a real choice, and the variety is the point. The platform side is where every architectural fork lives.

This asymmetry is the core fact of agent memory architecture. The harness side has no fork because there is no fork to take: working memory must end up in context, and context is what the harness assembles. The platform side has every fork because every existing memory product is one possible answer to a real design question. Most of the noisy debates in the category right now are debates inside the platform side, between answers that have already accepted the same constraint about the harness side.

Define the harness, then, not as a place but as a **responsibility set**. It is the runtime scaffolding required to turn an LLM into an agent: context assembly, tool routing, memory access, conversation lifecycle, compaction policy, the I/O path to a user or task. Some of those responsibilities are pure-local because they have to be (context assembly, current-turn state, prompt composition). Others can be implemented locally or fulfilled by a platform service that any harness can call. Memory access is the canonical example: durable memory storage lives in a platform service, but the responsibility for *when to call it* and *what to do with results* stays with the harness. Compaction looks like it is heading the same way. The harness is doing more than orchestration. It is making domain decisions that require an understanding of the agent's task.

The relationship between the harness's fast path and the platform's slower paths follows a familiar engineering pattern. **Act now, log later.** The harness writes to its in-process buffer synchronously and returns. The audit and forensics taps are separate writes, often asynchronous, to separate services with their own retention policy. The reflex completes before the brain gets the report. Forensics gets the report when it gets it. Engineers who have run any observability stack will recognize the pattern. The act path must succeed regardless of whether the log path succeeds. The two are decoupled by design.

```
   PLATFORM TIER  (the slow path)  ·  durable, governed, cross-agent
   ──────────────────────────────────────────────────────────────────
     encryption    embedding    retention    audit
     RBAC          scope        contradiction detection
     multi-tenant isolation     cross-agent reads
     compliance review

   ──────────── act now, log later ─────────────────────────────────

     KV cache     tool scratch    per-turn buffer
     compaction policy            token-budget management
     context assembly             prompt composition
     sub-ms access · no network hop · ephemeral
   ──────────────────────────────────────────────────────────────────
   HARNESS TIER  (the fast path)  ·  ephemeral, fast, per-call
```

## But "platform" is not one thing

Here is where most write-ups stop. They should not.

"Platform memory" sounds like one component. It is at least four. An enterprise agent platform that wants to outgrow a single harness and a single workload needs distinct services for at least these concerns:

**Governed durable memory.** What the agent learns. Semantic facts, episodic experiences, procedural rules. Scope-based access control, contradiction detection, retention, audit, branch-typed provenance. This is what MemoryHub, Mem0, Letta, Zep, and Oracle AI Agent Memory all build, with different bets on substrate and governance shape. The boundary of this component is "facts the agent has learned that future agents will read."

**Conversation persistence and resume.** The ability to come back to a thread tomorrow and continue where you left off. The interesting unit is a conversation, not a fact. The lifecycle is different (conversations end), the access patterns are different (chronological, threaded, with attachments), and the consumers are different (often human reviewers, not future agents). This belongs in the orchestration layer next to task dispatch and routing, not inside the memory store. In the platform plans we are working on, it lives in orchestration services like kagenti or LlamaStack rather than in the durable memory store.

**Context compaction.** Turning a long-running thread into a working summary the agent can fit in its window. Microsoft Research's [Memento work](https://arxiv.org/abs/2604.09852) showed that re-summarizing model-compressed output loses information through a hidden KV-cache channel, which means compaction is partly a model-side concern. Compaction also benefits from inference-engine awareness: a compaction service that knows the active model family and the underlying vLLM/KV-cache strategy can leave portions of the thread strategically uncompacted to minimize reasoning load on resume. That kind of intelligence is hard to embed in the harness and is exactly what a shared platform service can amortize across many agents. The decision to compact stays harness-side; the algorithm and the durable summary live in the platform; the result lands back in context at the harness's assembly step.

**Working-memory forensics and sandbox logging.** Even though working memory is harness-owned and ephemeral, regulators, security teams, and incident responders need to reconstruct what an agent reasoned over at a given moment. The same logic applies to code-execution sandbox logs (what did the agent run, what did it read, what did it write), tool-call audit trails, and prompt-and-context capture for post-hoc analysis. Why did the agent refuse this request? Because the safety check thought it was being attacked. That answer requires forensics. These are governance requirements on harness-owned state, captured to a separate forensics store with its own retention policy. They are not durable memory and they should not be in the memory store, but they are not nothing.

There is a useful distinction across these four. Three of them (memory, persistence, compaction) are **feeders**: their job is to make content available for some future turn's context assembly. They do not push content to the model. They make content available for the harness to pull in. The fourth (forensics) is a **recorder**: it observes what happened and persists it for later review without influencing future inferences. Feeders shape future inferences. Recorders reconstruct past ones. Confusing the two leads to architectures where audit logs end up in the agent's retrieval path or where memory ends up in the compliance reviewer's pipeline. Both are bad outcomes.

There is also a useful observation about how these components relate to the harness. They exist because harness responsibilities are increasingly fulfilled by platform services with standardized contracts. Memory access is harness-side, but the service that backs it is platform-side. Compaction policy is harness-side, but the algorithm and storage can be platform-side. Conversation resume logic is harness-side, but the thread store is platform-side. The pattern is the same one MCP introduced for tools: a standardized platform service, with the harness as consumer. Memory was the first harness responsibility to get a standard contract. Compaction is heading the same way. Conversation persistence is in the same shape.

The temptation to bundle these into a single artifact is real. Oracle bundles governed memory and conversation persistence and partial compaction into a single SDK. Project Think bundles all of them into the harness runtime. OpenViking treats resources, memories, and skills as one filesystem-shaped layer. Each bundling reflects a bet about which boundaries will hold. Time will sort out which bets pay off, but the cost asymmetry is clear: separating components that could have been combined is cheap to undo, while combining components that should have been separate is expensive to undo.

![IMAGE PROMPT: An editorial overhead-style diagram showing a horizontal row of four discrete boxes labeled (in the metaphor, not as text) for governed memory, conversation persistence, compaction, and sandbox forensics. Above the four boxes, a thin layer labeled "harness" sits across all of them with a small embedded "working memory" tile. Each of the four boxes has its own distinct icon set: a database stack with gates for governed memory, chat-thread cards for conversation, a funnel for compaction, and a glass-walled chamber with a logging tap for forensics. Cool slate-and-blue palette with one warm accent color on governed memory. No text labels, no logos.](placeholder-four-components.png)

## Bring your differentiation, reuse the hardened platform

For a developer, this all comes down to a sourcing decision. **Bring your differentiation, reuse the hardened platform.** That has been the value proposition of cloud platforms for a decade (Heroku, Vercel, managed Kubernetes, serverless), and it applies cleanly to agent infrastructure. The platform is most valuable in places where the work is non-differentiating, hard to do well, and expensive to redo per tenant. Multi-tenant isolation, audit trails, retention policies, RBAC, encryption at rest and in transit, FIPS-validated crypto, deletion-with-evidence. None of those are differentiated agent behavior. All of them are required. None are cheap to build alone.

The amplifier in regulated industries is compliance review. In healthcare and defense, the compliance review is often the longest pole in the deployment. Six to twelve months for a custom-built memory store with custom audit and custom isolation. If the platform has already passed review for those concerns, an agent that uses the platform inherits the review. The agent's review covers only the differentiated parts: capability logic, prompts, tool selection, business decisions. That is a smaller surface to defend. In some shops it is the difference between shipping in a quarter and shipping in a year.

That framing also clarifies the harness-vs-platform line. It is not a sales pitch for any single vendor. It is a sourcing decision. Same way a developer chooses whether to run their own Postgres or use a managed database, whether to run their own Vault or use a hosted secrets manager, whether to run their own Kafka or use a managed event bus. The trade is operational burden against differentiation budget. Platform-service-backed harness responsibilities let developers buy the operational burden out and keep the differentiation budget for the parts of the agent that no platform can build for them: the capability that makes this agent useful for this particular task.

Three concrete prescriptions follow.

If you are picking a memory system, ask which of the four components it actually solves. "We have agent memory" is no longer specific enough as a buying criterion. Does the system handle conversation resume, or just durable facts? Does it provide compaction policy, or just compaction storage? Where does sandbox-execution logging live, and is it the same retention policy as durable memory or a different one? The answers vary by vendor, and the differences are not in the marketing.

If you are building one, decide the scope of "memory" carefully and explicitly. The temptation to pull conversation history, compaction, and forensics into the same artifact is real because it ships faster and feels more product-like. The cost is coupling things that should evolve independently. Conversation modeling will change when you adopt a new harness. Durable-memory schemas will change when your governance requirements grow. Compaction policy will change when the underlying models start managing more of their own context. Forensics retention will change when a regulator publishes a new rule. If those four are one artifact, you change all four to change one.

If you are an architect choosing where to place these components in an enterprise platform, draw the lines on paper before you write the YAML. The cognitive-science taxonomy is useful for explaining what the system does. The access-pattern taxonomy is useful for explaining how it retrieves. The storage-shape taxonomy is useful for explaining what it costs. The governance dimension is useful for explaining who is responsible. The harness/platform line is useful for explaining what runs where. None of these on their own answers the platform question, which is: when something needs to change, what else has to change with it?

## Bridges, not moats, again

The previous post closed on a deliberate phrase. Companies and investors who see the platform layer early, and build bridges instead of moats, will shape what comes next. The same applies inside the platform. Governed durable memory, conversation persistence, compaction, and forensics each deserve clean component boundaries. Memory access patterns, compaction policy, and conversation resume logic each deserve clean responsibility lines back to the harness that consumes them.

The harness tier is well-served today. The platform tier is plural, and the vendors and architects who treat it as plural will be the ones whose architecture survives the next two years.

*If your team is making one of these calls right now, I would be interested to hear which boundaries you have already drawn and which ones you are still deferring.*

---

*Wes Jackson builds infrastructure for AI agents on enterprise platforms.*
*[GitHub](https://github.com/rdwj) | [LinkedIn](https://linkedin.com/in/profjackson)*
