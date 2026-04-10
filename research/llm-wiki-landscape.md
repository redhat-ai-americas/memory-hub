Here is the full research report.

---

## Karpathy's LLM Wiki and the Community Response: Landscape Analysis

### 1. The Source: Karpathy's Original Post and Gist

On April 3, 2026, Andrej Karpathy posted on X about "LLM Knowledge Bases," describing how a large fraction of his recent token usage had shifted from manipulating code to manipulating knowledge. The next day he published a GitHub Gist titled "llm-wiki" that became an "idea file" -- not code, but an architecture spec intended to be copy-pasted into any LLM agent (Claude Code, Codex, Gemini CLI, etc.) as a starting instruction.

**Architecture (three-layer):**
- `raw/` -- immutable source material (PDFs, articles, web clips, images). The LLM reads but never modifies these.
- `wiki/` -- LLM-compiled markdown articles: summaries, entity pages, concept articles, timelines, cross-references, backlinks.
- `index.md` -- a master catalog of every wiki page with one-line summaries, sized to fit in a single context window. The LLM reads index.md first, then drills into specific articles.

**Key insight:** Knowledge is *compiled once and kept current*, not re-derived on every query. When a new source is added, the LLM reads it, integrates it into existing wiki articles, notes contradictions, and updates the index. Karpathy reported building ~100 articles and ~400,000 words without writing a single word himself.

He explicitly said: *"I think there is room here for an incredible new product instead of a hacky collection of scripts."*

**Impact:** The tweet got 16M+ views. The gist got 5,000+ stars in days, later growing to 1,200+ stars and 215+ forks with community extensions.

**References:**
- [Karpathy's tweet on X](https://x.com/karpathy/status/2039805659525644595)
- [The llm-wiki Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [VentureBeat coverage](https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an)

---

### 2. Direct Responses: GitHub Projects Built in Response

A wave of implementations appeared within days. Here are the most notable:

**lucasastorian/llmwiki** ([GitHub](https://github.com/lucasastorian/llmwiki), [llmwiki.app](https://llmwiki.app/))
- The most polished open-source implementation. Ships an MCP server that Claude.ai connects to directly.
- Upload PDFs, articles, office documents; they get converted to high-quality markdown and indexed.
- Claude reads sources, writes wiki pages, maintains cross-references and citations.
- **Personal-only.** No multi-user or governance. Web app with local storage.
- Hit the Hacker News front page as a [Show HN](https://news.ycombinator.com/item?id=47656181).

**MehmetGoekce/llm-wiki** ([GitHub](https://github.com/MehmetGoekce/llm-wiki))
- L1/L2 cache architecture. Supports both Logseq and Obsidian.
- Uses Claude Code as the agent. The author wrote a detailed [Substack post](https://mehmetgoekce.substack.com/p/i-built-karpathys-llm-wiki-with-claude) on the build process.
- **Personal-only.** No access control.

**Pratiyush/llm-wiki** ([GitHub](https://github.com/Pratiyush/llm-wiki))
- Captures knowledge from Claude Code, Codex CLI, Copilot, Cursor, and Gemini sessions.
- Positioned as "implemented and shipped" rather than a concept.
- **Personal-only.**

**kfchou/wiki-skills** ([GitHub](https://github.com/kfchou/wiki-skills))
- Claude Code skills/plugin that implements the pattern. Drop-in skills you add to `.claude/skills/`.
- **Personal-only.**

**Astro-Han/karpathy-llm-wiki** ([GitHub](https://github.com/Astro-Han/karpathy-llm-wiki))
- "One skill to build your own Karpathy-style LLM wiki."
- **Personal-only.**

**ussumant/llm-wiki-compiler** ([GitHub](https://github.com/ussumant/llm-wiki-compiler))
- Claude Code plugin that compiles markdown knowledge files into a topic-based wiki. Tested on 155K words across 68 files.
- **Personal-only.**

**swarajbachu/cachezero** (Show HN: [CacheZero](https://news.ycombinator.com/item?id=47667723))
- Single NPM install CLI tool implementing the pattern.
- **Personal-only.**

**hellohejinyu/llm-wiki** ([GitHub](https://github.com/hellohejinyu/llm-wiki))
- LLM-powered personal wiki CLI.
- **Personal-only.**

**LLM Wiki v2** ([Gist by rohitg00](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2))
- Not code but an extended idea file. Addresses multi-user synchronization, conflict resolution, access control, and governance/auditing. Draws lessons from building "agentmemory," a persistent memory engine for coding agents.
- This is the most thoughtful extension toward multi-user governance I found in the direct-response ecosystem.

**Maturity assessment:** All of the above are early-stage, personal-use tools. None have multi-user support, governance, or access control (except the v2 gist which is a design spec, not an implementation). Most are days to weeks old.

---

### 3. Hacker News Discussion Themes

The Karpathy gist post hit HN front page ([47640875](https://news.ycombinator.com/item?id=47640875), 158 points, 45+ comments). Key themes:

- **"This is just RAG with extra steps"** -- Several commenters argued the compile-then-query pattern is functionally equivalent to retrieval-augmented generation, just with a persistent intermediate representation.
- **Model collapse risk** -- Referenced the 2024 Nature paper (Shumailov et al., 567 citations) showing AI outputs degrade when models train on their own output. Counter-argument: this isn't training, it's using an already-trained LLM to organize information for human consumption.
- **Context window will make this obsolete** -- Some argued 10M-token context windows eliminate the need for compiled intermediate layers.
- **The value of friction** -- Several PKM power users argued manual synthesis is the point; outsourcing it undermines learning. "The process of writing docs updates your own mental models."
- **Scaling concerns** -- "A critical point exists beyond which agents can't keep wikis updated anymore, and developers can't comprehend them."
- **Ownership advantage** -- File-based approach preserves user ownership vs. platform-controlled memory systems (ChatGPT memory, Claude memory).

---

### 4. Obsidian + AI Agent Ecosystem

This is where the most energy is right now.

**Obsidian Skills** by Steph Ango / kepano ([GitHub](https://github.com/kepano/obsidian-skills))
- Official, from Obsidian's CEO. 13.9k+ GitHub stars, MIT license.
- Five agent skills: Markdown, Bases (.base files), JSON Canvas, CLI, web content extraction.
- Not plugins -- they're portable markdown rulebooks that teach AI agents (Claude Code, Codex CLI, etc.) about Obsidian-specific syntax (wikilinks, callouts, frontmatter, etc.).
- **Personal-only.** No multi-user, no governance. But the most authoritative integration point.

**obsidian-ai-agent** by m-rgba ([GitHub](https://github.com/m-rgba/obsidian-ai-agent))
- Full Claude Code agent embedded in Obsidian's sidebar. AI can read, write, search, and execute bash commands in your vault.
- Currently uses elevated permissions (bypasses permission checks). Fine-grained access control planned.
- **Personal-only.** Active development.

**Claudian** by YishenTu ([GitHub](https://github.com/YishenTu/claudian))
- Embeds Claude Code, Codex, and other agents in Obsidian via Agent SDK. Sidebar chat, file read/write, vision support, slash commands, MCP server support.
- **Personal-only.**

**Cortex** (Obsidian Forum [thread](https://forum.obsidian.md/t/plugin-cortex-an-ai-obsidian-vault-agent-powered-by-claude-code/112430))
- Claude Code agent in a side panel that reads, writes, creates, moves, and organizes notes.
- **Personal-only.**

**obsidian-llm-plugin** by hardbyte ([GitHub](https://github.com/hardbyte/obsidian-llm-plugin))
- Integrates with LLM CLI tools (Claude, Codex, OpenCode, Gemini) for AI-powered vault assistance.
- **Personal-only.**

**ChatGPT MD** ([Blog post](https://www.blog.brightcoding.dev/2026/03/25/chatgpt-md-the-ai-assistant-your-obsidian-vault-needs))
- LLM integration with local and cloud models, tool calling, and intelligent agents inside Obsidian.
- **Personal-only.**

**Assessment:** The Obsidian ecosystem is exploding with AI integrations, but they are all personal-only, single-user, and have no governance layer. Obsidian itself is a local-first tool without native multi-user support, so this is by design.

---

### 5. The Broader "Knowledge Engineering" Trend

**Agentic Knowledge Management (AKM)** is the term gaining traction. Sebastien Dubois ([dsebastien.net](https://www.dsebastien.net/agentic-knowledge-management-the-next-evolution-of-pkm/)) has been the most vocal advocate, describing it as the inevitable evolution of PKM: AI agents that proactively monitor your knowledge base, understand your intent, and propose/execute actions before you ask. He manages an 8,000-note Obsidian vault with 64,000+ internal links.

**AI4PKM** ([jykim.github.io/AI4PKM](https://jykim.github.io/AI4PKM/))
- Community of Korean IT engineers in Seattle, started early 2025. Uses Obsidian as front-end, Cursor for collaborative editing, Claude Code for agentic processing.
- Evolving from individual "second brains" toward a *network of connected second brains*.
- By October 2025 they had an "On-demand Knowledge Task Processing" system.

**Meta's Tribal Knowledge Mapping** ([Engineering at Meta](https://engineering.fb.com/2026/04/06/developer-tools/how-meta-used-ai-to-map-tribal-knowledge-in-large-scale-data-pipelines/))
- A swarm of 50+ specialized AI agents systematically read 4,100+ files across three repos, producing 59 structured context files encoding tribal knowledge that previously lived only in engineers' heads.
- Documented 50+ "non-obvious patterns" (hidden naming conventions, append-only rules, etc.).
- Reduced research time from ~2 days to ~30 minutes. 40% fewer AI agent tool calls per task.
- This is the most compelling enterprise example of the "LLM compiles knowledge" pattern applied at scale.

**KPMG: Knowledge Engineering as Strategic Imperative** ([KPMG article](https://kpmg.com/us/en/articles/2026/why-knowledge-engineering-is-the-key-to-ai-agent-value.html))
- Positions knowledge engineering (ontologies, knowledge graphs, structured schemas) as the bridge between human expertise and AI agent effectiveness.

---

### 6. Products in the Space

**Established players with AI features:**

| Product | AI Capabilities | Multi-user | Governance | Maturity |
|---------|----------------|------------|------------|----------|
| **Notion AI** | AI Q&A over workspace, auto-summarization, writing assistance | Yes (team/enterprise) | Workspace permissions, enterprise SSO | Mature |
| **Mem 2.0** | AI-driven recall over notes, chat-based retrieval, de-emphasized manual organization | Personal-only | None | Moderate |
| **Reflect** | GPT-4 + Whisper for voice notes, AI outlining, end-to-end encryption | Personal-only | E2E encryption | Moderate |
| **Capacities** | AI chat with notes, contextual responses from knowledge base, backlinks, mind maps | Personal-only | None | Moderate |
| **Tana** | Supertags with schema, AI auto-tagging, summarization, content generation | Personal + team | Tag-based structure | Moderate |

**New entrants explicitly building the Karpathy vision:**

| Product | Approach | Multi-user | Governance | Maturity |
|---------|----------|------------|------------|----------|
| **LLM Wiki (llmwiki.app)** | Open-source, MCP-based, Claude integration | No | None | Very early |
| **Dume.ai** | AI executive assistant, agent builder for workflow automation, document compilation | Team-capable | Workspace-level | Early-moderate |
| **Remio.ai** | AI note-taker with "Dream Engine" overnight processing, contextual surfacing | Personal | None | Pre-launch/beta |
| **REM Labs** | AI-native PKM, automated capture/synthesis/retrieval, pre-meeting briefings | Personal | None | Early |
| **Waykee Cortex** | Hierarchical context engine for AI agents, combines Knowledge + Work layers, open source, model-agnostic | Team-capable | Hierarchical inheritance, role-based | Early |
| **CacheZero** | Single NPM install CLI implementing the pattern | No | None | Very early |

---

### 7. Enterprise/Team/Governed Versions

This is the least developed area but the most commercially interesting:

**Waykee Cortex** ([waykee.com](https://waykee.com/))
- The strongest candidate for "multi-user governed LLM wiki." Uses strict hierarchical inheritance (System -> Module -> Screen) that is industry-agnostic. Combines a Knowledge layer (what exists) with a Work layer (tasks, bugs, milestones), where issues inherit dual-context automatically.
- Open source, model-agnostic. One API call for full organizational context.
- Still early but architecturally the most thoughtful team-oriented approach.

**Microsoft's 2026 Knowledge Management Roadmap** ([Windows News](https://windowsnews.ai/article/enterprise-ai-knowledge-management-2026-microsofts-shift-from-search-to-governed-agent-workflows.410816))
- Shifting from information retrieval to workflow automation through governed agent systems. SharePoint + Copilot + governed agent workflows.
- Not a wiki compiler per se, but the enterprise version of the same idea: agents that maintain and act on organizational knowledge.

**Databricks Agent Bricks Knowledge Assistant** ([Databricks blog](https://www.databricks.com/blog/agent-bricks-knowledge-assistant-now-generally-available-turning-enterprise-knowledge-answers))
- GA as of January 2026. Agents that answer questions grounded in enterprise documents with citations.
- Unity Catalog provides governance (enterprise security, compliance boundaries).
- Integrates with Microsoft Teams, Copilot Studio, Power Platform.
- This is the closest to an enterprise-governed version, but it's RAG-based, not wiki-compilation-based.

**Academic Research on Multi-User Agent Memory:**

- **"Collaborative Memory"** (Rezazadeh et al., [arXiv:2505.18279](https://arxiv.org/abs/2505.18279)) -- Framework with two memory tiers (private + shared), bipartite access control graphs, immutable provenance. 61% reduction in resource usage in collaborative scenarios.
- **"Memory as a Service" (MaaS)** ([arXiv:2506.22815](https://arxiv.org/abs/2506.22815)) -- Decouples memory from agents, treats it as independently callable, governable service modules. Inspired by Data-as-a-Service.
- **A-MEM** ([NeurIPS 2025](https://arxiv.org/abs/2502.12110)) -- Agentic Memory system using Zettelkasten-like self-organizing memory with dynamic indexing and linking. Superior performance across six foundation models.

---

### 8. Key Gaps and Observations

**What exists:** Personal single-user implementations of the Karpathy pattern are abundant. The Obsidian + Claude Code integration path is the most popular. Open-source tools are days-to-weeks old and mostly hobby projects.

**What does not exist yet:**
- A production-quality multi-user LLM wiki with governance, access control, and audit trails
- Conflict resolution for concurrent agent edits (the HN thread flagged race conditions as a fundamental problem with filesystem-based wikis)
- A "compiled wiki" product that bridges personal and team use (the LLM Wiki v2 gist spec describes this but nobody has built it)
- Enterprise-grade versions with SSO, RBAC, compliance, and audit logging

**The commercial opportunity** that Karpathy identified is real and largely unclaimed. The closest things are Waykee Cortex (team-focused, hierarchical, but early) and Databricks Knowledge Assistant (enterprise, governed, but RAG-based rather than compilation-based). Nobody has shipped the full vision: multi-user, governed, compilation-based knowledge engineering with AI agents maintaining a living wiki.

**Relevance to MemoryHub:** The Karpathy pattern's three-layer architecture (raw sources -> compiled wiki -> index) maps surprisingly well to what MemoryHub already does with structured memory, versioning, and scoped access control (user/project/organizational/enterprise). The gap in this space -- multi-user governance, access control, contradiction detection, audit trails -- is exactly what MemoryHub is building. The community is validating the demand; nobody is filling the governed/multi-user niche yet.

Sources:
- [Karpathy's llm-wiki Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [Karpathy's X post](https://x.com/karpathy/status/2039805659525644595)
- [VentureBeat: Karpathy LLM Knowledge Base](https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an)
- [LLM Wiki (llmwiki.app)](https://llmwiki.app/)
- [Show HN: LLM Wiki](https://news.ycombinator.com/item?id=47656181)
- [Show HN: CacheZero](https://news.ycombinator.com/item?id=47667723)
- [HN Discussion: LLM Wiki idea file](https://news.ycombinator.com/item?id=47640875)
- [LLM Wiki v2 Gist](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)
- [MindStudio: How to Build with Claude Code](https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-knowledge-base-claude-code)
- [Obsidian Skills (kepano)](https://github.com/kepano/obsidian-skills)
- [obsidian-ai-agent (m-rgba)](https://github.com/m-rgba/obsidian-ai-agent)
- [Claudian](https://github.com/YishenTu/claudian)
- [Waykee Cortex](https://waykee.com/)
- [Dume.ai](https://www.dume.ai/blog/what-is-andrej-karpathys-llm-wiki-how-to-get-the-same-results-without-code-using-dume-cowork)
- [Remio.ai](https://www.remio.ai/)
- [REM Labs: End of Manual PKM](https://remlabs.ai/blog/ai-knowledge-management-2026)
- [dsebastien: Agentic Knowledge Management](https://www.dsebastien.net/agentic-knowledge-management-the-next-evolution-of-pkm/)
- [AI4PKM](https://jykim.github.io/AI4PKM/)
- [Meta: Tribal Knowledge Mapping](https://engineering.fb.com/2026/04/06/developer-tools/how-meta-used-ai-to-map-tribal-knowledge-in-large-scale-data-pipelines/)
- [KPMG: Knowledge Engineering for AI Agents](https://kpmg.com/us/en/articles/2026/why-knowledge-engineering-is-the-key-to-ai-agent-value.html)
- [Microsoft Enterprise Knowledge Management 2026](https://windowsnews.ai/article/enterprise-ai-knowledge-management-2026-microsofts-shift-from-search-to-governed-agent-workflows.410816)
- [Databricks Knowledge Assistant GA](https://www.databricks.com/blog/agent-bricks-knowledge-assistant-now-generally-available-turning-enterprise-knowledge-answers)
- [The New Stack: 6 Agentic KB Patterns](https://thenewstack.io/agentic-knowledge-base-patterns/)
- [Collaborative Memory (arXiv:2505.18279)](https://arxiv.org/abs/2505.18279)
- [Memory as a Service (arXiv:2506.22815)](https://arxiv.org/abs/2506.22815)
- [A-MEM: Agentic Memory (arXiv:2502.12110)](https://arxiv.org/abs/2502.12110)
- [Analytics Vidhya: LLM Wiki Revolution](https://www.analyticsvidhya.com/blog/2026/04/llm-wiki-by-andrej-karpathy/)
- [Atlan: LLM Wiki vs RAG](https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/)
