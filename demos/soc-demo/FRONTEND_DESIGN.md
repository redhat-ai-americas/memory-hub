# SOC Demo Frontend — Design Brief for Claude Designer

## What this is

A web-based visualization for the MemoryHub SOC demo. Four AI agents
from different frameworks (Claude Code, FIPS-Agent, OpenClaw, Hermes)
respond to a cybersecurity incident together, sharing memory through
MemoryHub. The frontend makes visible what terminal output can't: the
information flow between agents, the shared memory growing in real time,
and the specific moments where memory changes the outcome.

## The audience

Security decision-makers at conferences (RSA, Black Hat, CISA briefings).
SOC managers, CISOs, threat hunters, IR responders. They are technically
sophisticated, deeply allergic to AI hype, and want to see real
infrastructure, not mockups. The frontend should feel like an operational
dashboard, not a marketing demo.

## What the frontend replaces

Currently the demo runs as a Python script producing rich terminal output
via `asciinema` recording. It works, but:

- The audience can't see the agent coordination topology
- Memory operations (search, write, contradict) are text blocks, not
  visual events
- The cross-framework interoperability -- the whole point -- is only
  visible as framework labels in brackets
- The shift change (driver_id swap) is a table, not a transition

## The five visual moments that matter

These are the moments the RSA demo script identifies as landing points.
The frontend design should make each one visually unmistakable.

### 1. Cross-incident pattern recognition (the killer moment)

The Tier 1 agent searches memory and finds a match from a prior incident
(IR-2024-117, written 4 months ago). This memory causes the analyst to
escalate rather than dismiss the alert.

**What the audience needs to see:** A search query radiating from the
Tier 1 agent toward the central MemoryHub node. A memory node lighting
up. The content flowing back. Then the escalation decision. The causal
chain is: *this memory caused this decision.*

### 2. Agent-operational self-learning

The Forensics agent reads a memory *it wrote itself* from a prior
investigation (the ai.exe false positive filter). No human wrote this.
The agent fleet learned from its own experience.

**What the audience needs to see:** The Forensics agent card showing a
self-referencing memory retrieval. A visual indicator that this memory
was authored by the same agent role, not by a human.

### 3. Attribution contradiction

The Threat Intel agent writes an attribution assessment. Later, network
analysis contradicts it. Both views are preserved; the IC reads both
and adjusts.

**What the audience needs to see:** Two memory nodes connected by a red
"contradicts" edge. Both visible simultaneously with their content. The
IC reading both and writing a synthesis that references the disagreement.

### 4. Operational lesson at the moment of decision

The IC is about to rotate the breakglass credential. An 8-month-old
memory surfaces: "last time we did this, it broke backup for 6 hours."
The IC coordinates with the backup admin first.

**What the audience needs to see:** The memory surfacing at the critical
moment, visually tied to the containment action it's preventing from
going wrong. A "lesson applied" indicator.

### 5. Shift change with audit trail

At 06:00, the night shift hands off to the day shift. The role (actor_id)
stays constant; the human behind it (driver_id) changes. The accumulated
investigation memory persists across the handoff.

**What the audience needs to see:** A smooth transition on the agent card
where the human identity changes but the agent identity and its memory
context remain stable.

## Layout concept

### Primary view: the constellation

Center of the screen: MemoryHub, represented as a central node or core.
Around it, the four agent cards arranged in a loose constellation:

```
                    [Tier 1 SOC Analyst]
                     Claude Code · cyan
                          |
                          |
    [Threat Intel]  ——  [MEMORYHUB]  ——  [Forensics]
     Hermes · yellow      |            FIPS-Agent · green
                          |
                          |
                   [Incident Commander]
                    OpenClaw · magenta
```

Each agent card shows:
- Role name and framework badge
- actor_id and driver_id (color-coded per the RSA script spec)
- Current status (idle / searching / writing / reading)
- A small activity log of recent actions

Lines between agents and MemoryHub pulse when memory operations happen.
The direction of flow is visible (read vs write).

### Secondary view: memory timeline

A horizontal timeline along the bottom showing memory nodes as they're
created. Each node is color-coded by the agent that wrote it. Hovering
shows content. Contradiction edges are visible as red connecting lines.
The timeline scrolls as the scenario progresses.

### Phase indicator

A progress bar or phase label at the top showing which of the 7 phases
the scenario is in, with timestamp and one-line description. This
orients the audience in the incident timeline.

### Detail panel

A side panel (collapsible) that shows the full content of the currently
selected memory, including metadata (who wrote it, when, weight,
framework), version history if updated, and any contradiction
relationships.

## Interaction model

The frontend is **presenter-driven**, not audience-interactive. The
presenter clicks through phases or lets the scenario auto-advance on a
timer. The audience watches.

Two modes:
- **Auto-play**: the harness runs and pushes events to the frontend via
  WebSocket. The visualization updates in real time. This is the
  recording mode.
- **Click-through**: the presenter advances one action at a time with
  spacebar or arrow keys. This is the live presentation mode.

## Color system

Each agent framework has a distinct color (from the terminal harness):
- Claude Code: cyan (#00BCD4)
- FIPS-Agent: green (#4CAF50)
- OpenClaw: magenta (#E040FB)
- Hermes: yellow (#FFC107)

MemoryHub central node: blue (#2196F3)

Contradiction: red (#F44336)
Quarantine: red background with white text
Shift change: yellow (#FFEB3B) transition

Background: dark (near-black, #1a1a2e or similar). This is terminal
territory -- security audiences expect dark mode.

## Technical architecture

The frontend is a static SPA (HTML/CSS/JS, no build step) served by a
Go or Python server. The harness pushes structured events via WebSocket:

```json
{
  "type": "memory_write",
  "phase": 3,
  "timestamp": "03:15",
  "agent": "forensics",
  "framework": "FIPS-Agent",
  "memory_id": "abc-123",
  "content": "IR-2024-184 forensic timeline...",
  "metadata": {"incident_id": "IR-2024-184"}
}
```

Event types:
- `phase_start` — new phase begins
- `agent_register` — agent joins the fleet
- `memory_search` — agent searches (query visible, results flowing back)
- `memory_write` — agent writes a memory (node appears)
- `memory_read` — agent reads a memory (line pulses from MemoryHub to agent)
- `contradiction` — contradiction reported (red edge appears)
- `quarantine` — sensitive data caught (red flash on the memory node)
- `shift_change` — driver_id changes on an agent card
- `audit_query` — audit table appears in the detail panel

The frontend is purely a renderer. All scenario logic stays in the
Python harness. This separation means the frontend can also be used
with the live agent sandbox pods (Phase 3 future work) -- the harness
just needs to emit the same event format.

## What this is NOT

- Not a SIEM dashboard. The audience has those. Don't mimic Splunk.
- Not a chat interface. The agents don't chat with the audience.
- Not an admin panel. No forms, no configuration, no settings.
- Not a graph database viewer. The memory graph is a supporting visual,
  not the primary interface.

It's an **operational awareness display** -- the kind of thing you'd
put on the SOC wall screen during an incident if you wanted to see how
your agent fleet was working the problem.

## Model configuration (for the design narrative)

The demo uses a mix of cloud and on-cluster models to reinforce the
framework-agnostic story:

| Agent | Framework | Model | Where it runs |
|-------|-----------|-------|--------------|
| Tier 1 | Claude Code | Claude (Anthropic API) | Cloud (api.anthropic.com) |
| Forensics | FIPS-Agent | Gemma 4 E4B | On-cluster (vLLM, gemma-model namespace) |
| IC | OpenClaw | Gemma 4 E4B | On-cluster (vLLM) |
| Threat Intel | Hermes | Gemma 4 E4B | On-cluster (vLLM) |

Three agents run an open model hosted on the same OpenShift cluster as
MemoryHub. One calls a commercial cloud API. The memory layer doesn't
care which model is behind which agent -- it stores and retrieves the
same way regardless of model or framework.

This is worth showing in the UI: a small badge on each agent card
showing "Gemma 4 (on-cluster)" vs "Claude (cloud)" to make the
model-agnostic story visible.

## Reference material

- Scenario doc: `demos/scenarios/cybersecurity/threat-hunting-incident-response.md`
- RSA demo script (shot lists): `demos/scenarios/cybersecurity/demo-script-rsa.md`
- Terminal harness (event source): `demos/soc-demo/harness.py`
- Agent fleet config: `demos/soc-demo/agents/`
- Public-safety-demo (sibling project with same architecture): `github.com/fips-agents/public-safety-demo`
