# What Agent Memory Really Is

A guide for someone new to agentic memory — especially someone who has already Googled "agent memory" and come back with markdown files, vector databases, and gifs of graph nodes bouncing around. This document explains what memory actually is to an agent, where it lives, and how to decide what kind you need. It is deliberately honest about when you don't need MemoryHub.

## Start with a thought experiment

An agent is working in your repo right now, and somewhere in its context sits the line "prefers Podman over Docker." Question: does it matter where that line came from?

It does not. Whether it was pasted from a CLAUDE.md file, retrieved from a vector database, or assembled by traversing a knowledge graph, the model sees the same tokens and behaves identically. At the moment of inference, memory has no provenance, no storage engine, no schema. It's just context.

This is the most clarifying fact in the field, and most of what the internet calls "agent memory" obscures it. The model never remembers anything. **Memory is not a storage problem; it is a context-assembly policy problem.** The entire discipline lives in the questions *around* the moment of inference:

- Out of everything ever learned, how did *these* items get selected for *this* moment?
- Who was allowed to see them, and who wrote them?
- What happens when two of them disagree?
- What gets kept when the session ends, and who decides?
- Six months from now, can you reconstruct what the agent knew when it acted?

Different memory systems are just different answers to these questions. Judge them on the answers, not on the visualization.

## Two principles that generalize

**1. 100% of what it needs, 0% of what it doesn't.** This applies to all context, whether it arrives via RAG, memory retrieval, or a hand-written rule file. Omit something the agent needs and no retrieval cleverness saves you — the model can't reason from context it doesn't have. Stuff the context with garbage overlap and model performance degrades even when the right facts are present. Everything in a memory system — relevance ranking, weights, stubs, token budgets, compaction, focus biasing — exists in service of this ratio. A memory system's real product is *signal quality at assembly time*.

**2. Work backwards from the forensic investigation.** Imagine something went wrong and you're the one reconstructing it. Who or what did the thing — a person or an agent? What memories were in that agent's context at the time? Who or what wrote them, and when? Were any of them in conflict with other memories? Did storing them violate a policy? Which *other* agents had access to the same memories, and should their actions be reviewed too? If your memory architecture can answer that chain of questions, it can survive a regulated environment. If it can't, you've scoped yourself to use cases where nobody will ever ask.

The second principle is the honest dividing line in the whole landscape, so let's apply it.

## Memory lives in the harness

The **harness** is whatever assembles the model's context and mediates its actions: Claude Code, OpenClaw, a LangGraph application, a custom loop. Memory is implemented *in the harness* — as some combination of:

- **Rule/context files** loaded at session start (CLAUDE.md and friends)
- **Hooks** that inject retrieved memories at session start or per turn
- **Retrieval calls** the agent makes mid-session when it hits something unfamiliar
- **Write-back** — capturing decisions, preferences, and outcomes during or after the session
- **Compaction** — compressing a long history into something that still fits

Each of these components has a **locality choice**: it can be backed by local files on the machine, or by a shared platform over the network. That locality choice — not vectors vs. graphs vs. markdown — is the decision that actually changes how you manage memory.

**Local memory** (files on disk) is fast, free, private, fully inspectable, and version-controlled with tools you already have. It requires essentially no management, because its blast radius is one person: if your notes are wrong, you fix your notes. Its limits are structural, not qualitative — one writer, one reader, one machine, no access control, no audit, and an index that must fit in a context window.

**Platform memory** (a service like MemoryHub) is shared, durable, access-controlled, and queryable — and it *demands* management precisely because it's shared. Now a wrong memory misleads every agent that reads it, so you need curation. Now memories cross user boundaries, so you need scopes and RBAC. Now two agents learn contradictory things, so you need contradiction detection and resolution. Now an auditor can ask the forensic chain of questions, so you need identity (who wrote this — which agent, on whose behalf?), versioning, and an audit trail. Governance isn't overhead bolted onto platform memory; it's what makes shared memory safe to share.

Most real deployments are hybrid: local files for personal, machine-specific context; the platform for anything another agent or person needs, with hooks bridging the two so the agent experiences one assembled context.

## The ladder: matching the tool to the situation

**One developer, one machine, coding.** Use your harness's built-in memory — Claude Code's CLAUDE.md and memory system, or the equivalent in your harness — and you are well-served. It's local, zero-setup, and the forensic question never comes up because you are the only actor. Adding a memory platform here is pure overhead.

**Still just you, but beyond coding.** You want your harness (Claude Code, OpenClaw, whatever) to accumulate knowledge across domains — research, writing, projects. This is the [llm-wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) / Obsidian territory: agent-maintained markdown, compiled once and kept current, with an index the agent reads first. It works well, it's yours, and it's the right answer. Note what makes it work: one writer, one reader, moderate scale.

**A team of developers on a shared project in a controlled environment.** Six or seven people, each running coding agents, in a codebase where changes are reviewed and access matters. Now agents learn things that other people's agents need ("this deploy script destroys the DB if you run it wrong"), memories need an owner and a scope, and "who told the agent to do that?" is a question your security team will actually ask. Markdown in the repo covers some of it (this project does both — see [hooks-integration.md](hooks-integration.md)); shared operational memory with identity and access control does not fit in a git repo.

**A fleet of agents running an operational process.** Factory automation, incident response, logistics: many agents, operational facts that change hourly, no human in the write path. Shared memory is the coordination fabric itself. You need concurrent governed writes, freshness (temporal expiry — yesterday's line speed is not a fact anymore), and contradiction handling as routine operations, not exceptions.

**Agents in a regulated process.** Healthcare, finance, government. Everything from the previous rung, plus the forensic chain of questions is now a *legal requirement*, memory content is itself sensitive (PII/PHI scanning at write time), and "delete this person's data everywhere, provably" must be executable.

llm-wiki and Obsidian answer the first two rungs well and the last three not at all — no identity, no access control, no concurrent writes, no policy enforcement, no audit. That's not a criticism; they were never designed for it. The mistake is only in reaching for them past their rung — or reaching for a platform when you're on rung one.

## What about vectors and graphs?

They're retrieval mechanics, not the point. A vector index answers "what's semantically similar to what I'm doing right now?" at scales where reading an index file stops working. Graph relationships answer questions similarity can't: "what does this conflict with?", "where did this come from?", "what supersedes it?" — which is why the forensic chain of questions eventually pulls a provenance/relationship structure into any serious platform. But an animated graph visualization is flair; your agent never sees it. Evaluate memory backends by asking what selection, governance, and audit questions they can answer, not what they look like.

## Where MemoryHub sits

MemoryHub is the platform side of the harness: centralized, governed memory that agents reach over MCP (or the SDK/CLI), with local rule files and hooks bridging to whatever harness you run. Its design maps directly onto the two principles:

- Signal quality at assembly: [two-vector retrieval](../design/two-vector-retrieval.md) (query + session focus), weight-based stub/full injection, token budgets, temporal expiry.
- The forensic chain: [scoped access control and RBAC](../design/governance.md), owner/actor/driver [identity](../identity-model/README.md) (which agent acted, on whose behalf), [versioned memories with provenance](../design/memory-tree.md), write-time [curation with PII/secrets scanning](../design/curator-agent.md), contradiction reports, and audit logging.

Start with the [agent integration guide](agent-integration-guide.md) to wire up a harness, and [ARCHITECTURE.md](../ARCHITECTURE.md) for the system view. For the research behind these positions — the graph-memory landscape, benchmarks and their caveats, and the compiled-knowledge (llm-wiki) ecosystem — see [research/](../../research/README.md).
