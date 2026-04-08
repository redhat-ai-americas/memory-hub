# Scenarios and Integration Patterns

This document collects test scenarios, integration ideas, and open questions for MemoryHub. It informs which example agents and integrations we build to prove the system's value.

## Integration Surface

MemoryHub reaches agents through several paths, each with different characteristics.

**MCP Server (primary).** Any MCP-compatible agent connects directly. This covers Claude Code, LibreChat, and any agent framework with MCP client support. The agent calls tools explicitly — it decides when to read, write, or search memory.

**Custom Agent SDK.** Agents we build ourselves can use a Python SDK wrapping the service layer directly (no MCP overhead). This is the path for our own healthcare agents, research agents, and the curator agent. The SDK can hook into agent loops at specific points (before tool calls, after user messages, on task completion).

**LlamaStack / Framework Integration.** For agents running on OpenShift AI via LlamaStack, we need a way to inject memory into the stream without the agent explicitly calling tools. This is where FastMCP's sampling pattern could help — the MCP server could intercept the agent's context assembly and inject relevant memories before the LLM sees the prompt. This needs design work; the sampling handler lets the server request LLM calls, but the reverse (server injecting into client context) isn't standard MCP. A middleware or provider pattern on the LlamaStack side might be needed.

**Commercial Agents (Gemini, ChatGPT, etc.).** Web-based agents that support MCP can connect to our server directly. For those that don't, a browser extension or proxy could bridge the gap, but that's speculative. The near-term play is: agents that support MCP get full MemoryHub capability; others don't.

## Scenario Categories

### 1. Personal Agent Memory (Claude Code, Gemini, etc.)

The simplest scenario: an individual developer's agent accumulates knowledge over time.

**Scenario: "The agent that remembers."** A developer uses Claude Code with MemoryHub connected. Over weeks of work, the agent learns their preferences (Podman, FastAPI, pytest patterns), project context, and working style. When the developer starts a new project, the agent doesn't ask "what framework do you prefer?" — it already knows. When their preferences change, the agent detects the drift and asks about it.

**Test approach:** Give Claude Code the MemoryHub MCP server. Work on a real project for several sessions. Evaluate: does the agent use memory naturally? Does it write useful memories? Does search surface the right context? Does the agent get overwhelmed with irrelevant memories?

**Questions:**
- How does Claude Code's existing memory (`.claude/memory/`) interact with MemoryHub? Complementary, redundant, or conflicting?
- What's the right injection strategy? Should the agent search memory at the start of every conversation, or only when it seems relevant?
- How do we handle a cold start gracefully? First session has no memories — the agent shouldn't be awkward about that.

### 2. Specialized Agent Workflows

Agents built for specific tasks where memory provides continuity and institutional knowledge.

**Scenario: "Healthcare clinical workflow."** A healthcare agent assists with parts of a clinical workflow — maybe reviewing patient histories, surfacing relevant protocols, or checking drug interactions. Memory stores institutional protocols, learned patterns from previous cases (de-identified), and practitioner preferences. When a new protocol is published, organizational memory updates and the agent surfaces it proactively during relevant workflows.

**Test approach:** Build a mock clinical workflow agent with synthetic (non-real) patient data. Seed organizational memories with protocols. Test that the agent correctly surfaces relevant protocols, respects scope boundaries (patient data stays in patient scope), and adapts when protocols change.

**Questions:**
- How do we handle PHI? Patient-specific memories need the strictest governance. Can we demonstrate HIPAA-compatible memory isolation without building a full compliance framework?
- Is memory useful for protocol adherence, or is RAG over a protocol document store more appropriate? Where's the boundary?
- What does the forensics story look like here? "Why did the agent recommend treatment X?" needs to reconstruct the exact memory state that influenced the decision.

**Scenario: "Research agent."** An agent helps a researcher explore a topic — searching papers, summarizing findings, tracking hypotheses. Memory persists the research state across sessions: what's been explored, what hypotheses were formed, what evidence supports or contradicts them. The version history shows how the researcher's understanding evolved.

**Test approach:** Use the agent for a multi-session research task. Evaluate: does memory provide useful continuity? Does the version history tell a coherent story of the research process?

**Questions:**
- Should the agent maintain a "research graph" in memory (concepts, relationships, evidence chains)? That's a natural fit for our tree model with branches.
- How do we handle conflicting information from different sources? The contradiction reporting mechanism could be useful here.

**Scenario: "Infrastructure operations agent."** An agent assists with OpenShift cluster management — deployments, troubleshooting, capacity planning. Memory stores known issues, past incident resolutions, cluster-specific configuration quirks, and team runbooks. When a similar issue recurs, the agent says "this looks like the memory leak we saw in March — here's what worked last time."

**Test approach:** Seed memories with synthetic incident history. Simulate recurring issues. Evaluate: does the agent recognize patterns and surface relevant past resolutions?

### 3. Collaborative / Cross-Cutting Scenarios

The most differentiated scenarios — where organizational memory creates value across agents and users.

**Scenario: "The connector."** A developer is starting work on a notification service. MemoryHub's organizational memory knows that another team recently built something similar. The agent says: "Just so you know, one of your colleagues is working on something similar. Would you like me to reach out and see if they want to collaborate?" The agent doesn't reveal who it is (privacy), but if the other person agrees, it facilitates the introduction.

This requires:
- Organizational memory that captures what teams/people are working on (from project-scoped memories)
- A matching/relevance engine that detects overlap between different users' work
- A communication channel (Slack integration) for the agent to broker introductions
- Privacy controls: the agent doesn't reveal names or project details without consent

**Test approach:** Set up two users with overlapping project-scoped memories. Have one user's agent detect the overlap and initiate the introduction flow. This is a demo scenario — the communication would be mocked or use a test Slack channel.

**Questions:**
- Who decides what constitutes "relevant overlap"? The curator agent analyzing organizational memory? A dedicated matching agent?
- How aggressive should the proactive surfacing be? "You might want to know about X" is helpful; "Did you know about X, Y, Z, and also W?" is annoying.
- Privacy model: the agent knows about both projects, but can it reveal that knowledge? Organizational memory is read-accessible, but contextual linking ("person A's project relates to person B's project") is a different kind of inference.

**Scenario: "The institutional knowledge base."** A new employee joins. Their agent bootstraps from organizational and role-based memory: "Engineers in this org use Podman, prefer FastAPI, require FIPS compliance, and always scan for secrets before committing." The new hire's agent is immediately productive, following established patterns without the new hire having to discover them.

**Test approach:** Create a rich set of organizational and role memories. Simulate a "new user" agent with no user-scoped memories. Evaluate: does the agent correctly apply organizational context? Does it feel helpful or preachy?

**Scenario: "The resource recommender."** A user starts a research project using Gemini. MemoryHub knows about a relevant NotebookLM project that's open to all employees. The agent says: "There's an existing research notebook on this topic that other employees maintain. Want to check it out before starting from scratch?" This saves duplication and encourages knowledge sharing.

This requires:
- Organizational memory about shared resources (NotebookLM projects, wikis, repositories)
- Relevance matching between the user's current task and available resources
- A way for the agent to surface this proactively (sampling pattern or context injection)

**Questions:**
- How do shared resources get into memory? An ingestion pipeline scanning internal wikis/docs? Manual curation? A combination?
- How do we keep resource recommendations current? A shared resource that was archived or moved should stop being recommended.

### 4. Memory Observability and Forensics

Not agent workflows per se, but scenarios where the memory system itself is the subject.

**Scenario: "The forensic investigator."** After an incident (agent took an unexpected action), a security analyst uses Grafana to reconstruct what memories were in the agent's context at the time. They trace: which memories were retrieved, what version was current, whether any memories had been recently modified, and whether the action was consistent with the memory state.

**Test approach:** Create a sequence of memory operations with timestamps. Use get_memory_history and search with current_only=false to reconstruct past state. Build a Grafana dashboard mockup showing the timeline.

**Scenario: "The policy auditor."** An auditor reviews all organizational and enterprise memories for compliance. They search for memories containing policy statements, check that they're properly sourced (provenance branches), and verify that conflicting policies don't exist.

**Test approach:** Seed a mix of well-formed and poorly-formed policy memories. Build search queries that surface governance issues.

## Integration Architecture Questions

**MCP vs SDK vs Stream Injection — when to use which?**

| Integration | Best for | Mechanism |
|-------------|----------|-----------|
| MCP Server | Commercial agents, Claude Code, any MCP client | Agent explicitly calls tools |
| Python SDK | Custom agents we build, tight integration | Direct service calls in agent loop |
| Stream injection | LlamaStack agents, context-assembled agents | Middleware injects memory before LLM call |
| Sampling pattern | Server-initiated memory surfacing | FastMCP sampling handler triggers proactive suggestions |

**The proactive surfacing problem.** Most of our scenarios are reactive — the agent searches memory when it needs context. The connector and resource recommender scenarios require *proactive* surfacing — the system detects relevance and injects it without being asked. Options:

1. **Polling.** The agent periodically searches memory for relevant context. Simple but wasteful.
2. **Event-driven.** When organizational memory changes, notify relevant agents. Requires a pub/sub mechanism.
3. **Context middleware.** On every LLM call, a middleware layer checks memory for relevant context and injects it. Works for LlamaStack-style architectures but adds latency.
4. **Sampling.** The MCP server uses FastMCP's sampling handler to request an LLM call when it detects something the agent should know about. The server initiates, not the agent.

The sampling pattern (4) is the most interesting for MCP-based agents. The server could maintain a "notification queue" of organizational changes, and when an agent connects, use sampling to say "before we continue, you should know that X changed." This needs prototyping.

**Multi-agent coordination.** In the connector scenario, two users' agents need to interact through MemoryHub without directly communicating. The memory system is the coordination layer — Agent A writes a project-scoped memory, the curator detects overlap with Agent B's project memories, and Agent B's memory search surfaces the connection. No direct agent-to-agent communication needed.

## Priority for Building

**Near-term (Phase 1 demo enhancement):**
1. Claude Code integration — connect MemoryHub to a real Claude Code session and work with it
2. Seed realistic organizational memories for a demo narrative

**Medium-term (Phase 2-3):**
3. Build one specialized agent (infrastructure ops is probably the most accessible)
4. Prototype the connector scenario with mock Slack integration
5. Explore LlamaStack integration path

**Longer-term (Phase 4+):**
6. Healthcare workflow with governance demonstration
7. Gemini / external agent integration
8. SDK development for custom agent loops
9. Proactive surfacing via sampling pattern prototype
