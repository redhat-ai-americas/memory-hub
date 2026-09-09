# SOC Demo Talk Track (15-20 min video)

Hybrid format: web UI (constellation display) + terminal at key moments.
Stage directions in **[brackets]**. Approximate timings in the margin.

---

## 1. Cold Open (0:00 - 1:30)

**[Screen: Title card or the standby screen with the four agent cards visible]**

> Most SOC teams run a mix of tools. Your Tier 1 analyst uses one platform,
> forensics uses another, threat intel has their own stack. That's fine for
> humans because you have a war room, you have a shared wiki, you have
> Slack. But what happens when those analysts are AI agents?
>
> Each agent framework has its own memory model. LangGraph keeps state in a
> graph. Claude Code keeps context in a conversation. A FIPS-Agent keeps it
> in a session object. If your forensics agent discovers something critical
> at 3 AM, your incident commander running on a different framework has no
> way to know about it unless you build custom plumbing between every pair
> of frameworks. That doesn't scale.
>
> MemoryHub solves this. It's a shared memory layer that any agent on any
> framework can write to and read from. Today I'm going to walk through a
> full incident response scenario -- credential compromise at a fictional
> financial services company -- using four agents on four different
> frameworks, all sharing memory through MemoryHub.

**[Click REPLAY or press SPACE to start the scenario]**

---

## 2. The Setup (1:30 - 3:00)

**[Screen: Constellation display. Agents transition from OFFLINE to IDLE as
the scenario initializes. Point out the layout.]**

> Let me orient you to what you're looking at. In the center is the
> MemoryHub node -- that's the shared memory store. Around it, four agents,
> each on a different framework.
>
> At the top, our Tier 1 SOC Analyst, running on Claude Code with a cloud
> Claude model. On the left, Threat Intel on Hermes. On the right,
> Forensics on FIPS-Agent. And at the bottom, the Incident Commander on
> OpenClaw. Three of these four are running a local Gemma 4 model deployed
> on-cluster through OpenShift AI. Only the Tier 1 analyst uses a cloud
> API.
>
> The framework badges are color-coded so you can always tell who's who.
> And notice each agent card shows two IDs: an actor_id, which is the agent
> role, and a driver_id, which is the human operator on shift. That
> separation matters -- we'll see why during the shift change.

**[Switch to terminal briefly to show the seed memories]**

> Before the incident starts, MemoryHub already has institutional memory
> from past incidents. Let me show you what's been seeded.

**[Run: `python seed-memories.py --list` or show the 6 seed memories]**

> Six memories from prior work. An old incident report from four months
> ago. A team heuristic about service account patterns. A lesson learned
> about breakglass credential rotation. These are the kinds of things a
> human SOC team accumulates over years. We're giving that same
> institutional knowledge to the agents.

---

## 3. Phase 1: Detection (3:00 - 4:00)

**[Screen: Back to constellation. The Tier 1 agent activates.]**

> 02:14 AM. CrowdStrike fires an alert: anomalous service account logon
> from an IP that's never been associated with this account before. The
> Tier 1 agent picks it up.
>
> Watch the status pill change from IDLE to SEARCHING. The agent's first
> instinct -- just like a good human analyst -- is to check whether we've
> seen anything like this before.

**[The SVG line animates outward from Tier 1 to MemoryHub hub]**

> That search hits MemoryHub. And this is where it gets interesting.

---

## 4. Phase 2: Triage & Cross-Incident Pattern Match (4:00 - 6:30)

**[Screen: Constellation. Memory chip appears in the timeline strip.]**

> The agent finds a match. Four months ago, IR-2024-117, a different
> incident entirely, a different team investigated it. But the pattern is
> the same: service account anomaly, off-hours access, same staging path
> structure. That old investigation was handled by a forensics agent on a
> completely different framework, but because the memory lives in
> MemoryHub, the Tier 1 agent can read it.

**[Click the memory chip in the timeline to open the detail panel]**

> Look at the detail panel. You can see the full memory content, the
> weight (how important the authoring agent considered it), the framework
> it was written from, and the timestamp. The dashed border on this chip
> means it's a prior-incident memory, not something from today.
>
> Without this cross-incident context, a Tier 1 agent would likely classify
> this as a low-severity anomaly. Maybe it's a misconfigured service
> account, a developer testing after hours. But with the pattern match,
> the agent escalates to a full incident. That's the difference between
> catching a breach in 20 minutes and catching it in 20 days.

**[Switch to terminal: show the MemoryHub search call and result]**

> Under the hood, this is a single SDK call. The agent sends a natural
> language query -- "service account anomaly off-hours" -- and MemoryHub
> returns semantically relevant memories across all projects the agent has
> access to. The agent didn't need to know about IR-2024-117. It didn't
> need to know which framework wrote that memory. It just searched, and
> the institutional knowledge was there.

---

## 5. Phase 3: Investigation (6:30 - 8:30)

**[Screen: Constellation. Forensics and Threat Intel activate in parallel.]**

> Now we're in full incident response. Two agents spin up simultaneously.
> Forensics is building a timeline -- lateral movement, credential
> harvesting, what the attacker touched. Threat Intel is looking at TTPs,
> trying to figure out who's behind this.

**[Both agents show SEARCHING then WRITING status. Memory chips appear.]**

> Watch the memory timeline at the bottom. Both agents are writing findings
> to MemoryHub as they go. Forensics writes a timeline reconstruction.
> Threat Intel writes an initial attribution assessment.
>
> And here's the key thing: Forensics finds a memory it wrote itself during
> IR-2024-117. A false positive filter for ai.exe that it developed four
> months ago. No human authored that operational knowledge -- the agent
> learned it from its own prior investigation and it's applying it now.
> That's agent self-learning through persistent memory.

**[Click the self-authored memory chip, note the "self-authored" indicator]**

> The detail panel marks this as self-authored. The same agent, same
> actor_id, wrote it months ago and is now reading it back. That's the
> kind of institutional knowledge that usually lives in a senior analyst's
> head and walks out the door when they leave.

---

## 6. Phase 4: Contradiction (8:30 - 11:00)

**[Screen: Constellation. This is the most visually dramatic phase.]**

> Phase 4 is where things get interesting. At 06:00, we have a shift
> change. The night shift operators hand off to the day shift.

**[Agent cards update: driver_ids change, status briefly shows HANDOFF]**

> Notice the driver_id fields just changed on every agent card. The agents
> are the same -- same actor_ids, same accumulated context -- but the
> humans overseeing them swapped out. MemoryHub tracks both. Every memory
> operation from this point forward is attributed to the new human
> operators, but the investigation context carries over seamlessly. No
> re-briefing, no "let me read you in on where we are."
>
> Now, the network analysis comes back. And it contradicts Threat Intel's
> initial attribution. The C2 infrastructure doesn't match the threat group
> that was initially fingered. A different agent framework, the IC on
> OpenClaw, surfaces this.

**[Hub flashes. Contradiction chip appears in red in the timeline.]**

> Watch what happens. MemoryHub doesn't overwrite the original assessment.
> It preserves both. The IC calls `report_contradiction`, and now both the
> original attribution and the contradicting network analysis exist side by
> side, linked.

**[Click the contradiction chip. Detail panel shows side-by-side comparison.]**

> The detail panel shows both assessments with a red divider between them.
> This is critical for incident response. You never want an AI agent
> silently overwriting a prior conclusion. Especially in a security
> context, you need the full chain of reasoning. What was believed, when
> it changed, and why.

**[Switch to terminal: show the report_contradiction SDK call]**

> One SDK call. `report_contradiction` takes the memory ID of the original
> assessment and a description of the observed contradiction. MemoryHub
> links them, increments a contradiction counter, and preserves both for
> the audit trail.

---

## 7. Phase 5: Containment & Quarantine (11:00 - 13:30)

**[Screen: Constellation. IC activates, reads the breakglass lesson.]**

> The IC is now coordinating containment. It needs to rotate compromised
> credentials. But before it acts, it searches MemoryHub for operational
> lessons. And it finds one from eight months ago: "Last time we rotated
> breakglass credentials, backup systems were down for six hours."

**[Memory chip lights up. IC status shows READING.]**

> That's a painful lesson someone learned the hard way. Now every agent,
> on any framework, benefits from it. The IC adjusts its containment plan
> to sequence the rotation with backup system verification.

**[Hub flashes red. A quarantine event fires.]**

> Now watch this. The forensics agent tries to write a memory that contains
> an actual service account credential -- the compromised password. MemoryHub
> blocks it. The hub flashes red, and you see a quarantine chip appear
> in the timeline.

**[Click the quarantine chip.]**

> The content was quarantined before it ever entered shared memory. PII and
> credential detection runs at the write boundary. The agent gets a
> notification, rewrites the memory with a vault pointer instead of the raw
> credential, and the corrected version goes through.
>
> This is governance built into the memory layer. You don't rely on each
> agent framework to implement its own credential filtering. MemoryHub
> enforces it centrally, regardless of which framework is writing.

---

## 8. Phase 6: Audit Trail (13:30 - 15:00)

**[Screen: Detail panel showing the audit table]**

> Let's look at the audit trail. Every memory operation -- every search,
> write, read, contradiction report -- is logged with the actor_id (the
> agent role), the driver_id (the human on shift), the timestamp, and the
> operation type.

**[Scroll through the audit entries. Point out the shift change boundary.]**

> You can see the shift change right here. Before 06:00, all operations
> are attributed to the night shift operators. After 06:00, the day
> shift. But the investigation is continuous. If this were a real incident
> and legal needed to reconstruct who knew what and when, this audit trail
> gives you that.
>
> The actor/driver separation also answers a question regulators care
> about: was a human in the loop? Every agent action traces back to a
> responsible human through the driver_id. The agent can't operate without
> one.

---

## 9. Phase 7: Post-Incident Learning (15:00 - 16:30)

**[Screen: Constellation. IC writes final lessons learned.]**

> The incident is contained. Now the IC writes lessons learned back to
> MemoryHub. The breakglass sequencing that worked. The contradiction
> pattern that flagged a misattribution. The cross-incident search that
> caught the breach early.

**[Final memory chips appear in the timeline. Memory count increments.]**

> These lessons are now available to any agent, on any framework, on the
> next incident. The next time a Tier 1 agent on Claude Code sees a
> service account anomaly, it won't just find IR-2024-117. It'll find
> this incident too. The institutional knowledge compounds.

---

## 10. Architecture Recap (16:30 - 18:00)

**[Switch to terminal or a slide showing the component diagram]**

> Let me pull back and show you what's running under the hood.
>
> MemoryHub is deployed on OpenShift. PostgreSQL with pgvector for storage
> and semantic search. An MCP server that any agent framework can connect
> to using the standard Model Context Protocol. An SDK for Python clients
> that wraps the MCP calls.
>
> The four agents connect to the same MemoryHub instance. They don't know
> about each other. They don't need custom integrations between frameworks.
> They just read and write memories through a common API. MemoryHub handles
> the access control, the semantic indexing, the contradiction tracking,
> and the audit trail.
>
> Three of the four agents are running Gemma 4 on-cluster through
> OpenShift AI's vLLM serving. No data leaves the cluster for those three.
> The Tier 1 agent uses a cloud Claude model to show that MemoryHub works
> across deployment models too -- cloud and on-prem agents sharing the same
> memory.

---

## 11. Close (18:00 - 19:00)

**[Screen: Constellation in final state, all 7 phase indicators lit]**

> Four agents. Four frameworks. One shared memory.
>
> The value proposition is straightforward. If you're building AI-assisted
> security operations -- or any multi-agent system -- your agents need to
> share context. Without shared memory, every agent starts from zero on
> every incident. With MemoryHub, they inherit the institutional knowledge
> of every agent that came before them, regardless of framework.
>
> Cross-incident pattern recognition. Self-learning from prior
> investigations. Contradiction preservation instead of silent overwrites.
> Credential quarantine at the memory boundary. Full audit trail with
> human accountability.
>
> This is what agent memory infrastructure looks like.

---

## Production Notes

### Key visual moments to frame tightly

1. **Cross-incident search hit** (Phase 2) -- the SVG line animating from Tier 1 to
   the hub, then the dashed-border memory chip appearing. This is the "hero moment."
2. **Contradiction side-by-side** (Phase 4) -- the red-bordered detail panel with
   both assessments visible. Dramatic and immediately legible.
3. **Quarantine flash** (Phase 5) -- the hub pulsing red. Short but visceral.
4. **Shift change** (Phase 4) -- driver_id fields updating simultaneously across
   all four agent cards.

### Terminal segments to prepare

- Seed memories listing (Phase 2 setup)
- MemoryHub search SDK call + result (Phase 2)
- `report_contradiction` SDK call (Phase 4)
- Optionally: `harness.py` invocation showing the agent calls in real time

### Pacing guidance

- Phases 1-2 (detection through pattern match): spend the most time here. This is
  the "aha" moment. If the viewer understands one thing, it should be cross-incident
  search.
- Phase 4 (contradiction): second most important. Viewers from regulated industries
  will immediately see the audit value.
- Phases 3, 5, 6, 7: move briskly. The concepts land fast once the audience
  understands the memory model.

### Things to avoid

- Don't over-explain MCP. Say "standard protocol" and move on. The audience
  cares about the capability, not the transport layer.
- Don't dwell on framework differences. The point is that they don't matter.
- Don't show raw JSON unless it clarifies something. The UI is more compelling.
- Don't say "AI agent" when "agent" alone is clear from context.
