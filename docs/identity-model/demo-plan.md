# Healthcare Demo Plan

## What we're showing

A fleet of small, purpose-built agents (target: 50, minimum acceptable: ~20)
running on the cluster, coordinating around a clinical workflow, with
MemoryHub as the shared memory and governance layer between them. The demo's
load-bearing narratives are:

1. **Centralized identity** — every agent gets its identity from a central
   source (Kubernetes Secret + ConfigMap), authenticates to MemoryHub, and
   acts under that identity for the duration of its life.
2. **Hive-mind learning** — agents post discoveries to project-scope
   memory, where the rest of the fleet can search them, react to them,
   and refine future behavior. The fleet behaves coherently because of
   shared memory, not because of central coordination.
3. **Auditable attribution** — every memory operation is recorded with
   `actor_id` (which agent did it) and `driver_id` (on whose behalf), and
   the audit log is queryable. "Show me everything Agent #07 did during
   the discharge workflow" is a real query.
4. **Contradiction detection** — when one agent's findings contradict
   another's, MemoryHub surfaces the conflict, and the demo shows the
   resolution flow.
5. **Governance in action** — when an agent attempts to write a memory
   containing PHI, the curation pipeline catches it, quarantines it, and
   logs the attempt. The agent learns and the policy is enforced.

The fifth narrative is what makes this a *healthcare* demo and not just an
agent-fleet demo. It needs PHI/HIPAA detection that doesn't exist today.

## Scenario sketch (working draft)

The exact clinical workflow will be picked when we mock up the scenario,
but it should have these properties:

- **Multiple care team roles** — at minimum: ED triage nurse, ED
  attending physician, pharmacist, cardiology consult, discharge planner,
  scheduler, billing/coding clerk. Each role has multiple instances so
  the demo can show role-vs-instance attribution.
- **Cross-role information flow** — the workflow has natural points where
  one role discovers something the rest of the team needs to know
  (e.g., a triage nurse identifies a drug interaction that affects the
  attending's treatment plan).
- **Natural contradictions** — at least one point in the workflow where
  two agents reach different conclusions about the same patient, so
  contradiction detection has something to surface.
- **A PHI failure mode** — at least one agent attempts to write a
  memory containing synthesized PHI (MRN, full name + condition, etc.)
  and the curation pipeline blocks or quarantines it.
- **A driven-vs-autonomous mix** — some agents run autonomously
  (scheduled, no human in the loop, `driver_id == actor_id`); others are
  driven by the harness (`driver_id == claude-code-cli-run-N`). The demo
  shows queries that distinguish these modes.

A worked candidate scenario: **ED visit → discharge with new medication**.
A patient arrives at the ED with chest pain. Triage nurse documents intake.
Attending orders cardiac workup. Cardiology consult happens. Pharmacist
reviews home medications and the new prescription for interactions.
Discharge planner schedules follow-up. Billing/coding agent assigns codes.
At several points in this flow, agents post to project-scope memory; at
one point an agent attempts to log a full MRN and is blocked; at one point
the cardiology consult contradicts the initial triage assessment.

The exact scenario will be refined when we sit down with a real clinical
workflow reference.

## What needs to be built before the demo

The dependencies, in rough order of "things that block other things":

### 1. Identity model implementation

Tracked in [data-model.md](data-model.md) and the corresponding GitHub
issues. Schema migration, plumbing of `actor_id`/`driver_id` through tools,
`register_session` extension. This is the foundation the rest builds on.

### 2. Project membership enforcement

Tracked in [authorization.md](authorization.md). Without this, the
hive-mind narrative is a hand-wave — any agent could read or write any
project-scope memory. The whole "trustworthy shared memory" claim
collapses without enforced membership.

### 3. Audit log stub interface

Tracked in [authorization.md](authorization.md). A no-op
`audit.record_event` interface that every tool calls. Persistence is
post-demo work; for the demo, structured log lines are sufficient to
demonstrate the recording shape and prove call sites are wired correctly.

The demo can show audit by tailing the MCP server's logs and grepping for
audit events. Not glamorous but honest: "the events are captured, the
persistence layer is the next milestone."

### 4. PHI/HIPAA detection patterns in the curation pipeline

The current curation pipeline (`memory-hub-mcp/src/tools/write_memory.py`)
detects generic PII: email, phone, SSN, credit cards. It does not detect
HIPAA-specific identifiers. For the healthcare narrative, we need patterns
for at least:

- **MRN** (Medical Record Number) — varies by system, but a numeric or
  alphanumeric identifier in clinical context. Pattern is heuristic
  (preceded by "MRN:", "Medical Record:", etc.) plus a length check.
- **NPI** (National Provider Identifier) — exactly 10 digits, has a
  Luhn-style check digit. Strict format, easy to validate.
- **DEA Number** — 2 letters + 7 digits with a checksum. Strict format.
- **DOB in clinical context** — a date pattern (MM/DD/YYYY or
  YYYY-MM-DD) appearing near words like "born," "DOB," "age," or
  "birthday." Heuristic.
- **ICD-10 / CPT codes** — these are arguably *not* PHI on their own
  (they describe conditions, not patients), but in combination with
  other identifiers they become PHI. For the demo, we treat ICD/CPT as
  metadata that's fine to store, but the *combination* of an ICD code
  with a name or MRN raises the severity.
- **Full name + clinical context** — heuristic: a recognizable
  human-name pattern (FirstName LastName) appearing in the same memory
  as a clinical identifier or condition. Hardest to detect cleanly;
  acceptable to use a simple "two capitalized words near a clinical
  keyword" heuristic for the demo.

The detection patterns ship as a curation policy file (proposed:
`memory-hub-mcp/policies/healthcare.yaml`) loadable via the existing
`manage_curation(action="set_rule", ...)` tool action. Three actions configurable per pattern:
flag-and-alert, quarantine, block. The demo uses `quarantine` for most
patterns so the demo presenter can show the quarantined memory and explain
what happened.

This work depends on understanding the existing curation pipeline's
extension points; whoever picks this up should read
`memory-hub-mcp/src/tools/write_memory.py` and the curation rule modules
end-to-end before designing the patterns.

### 5. Contradiction detection demo flow validation

`manage_curation(action="report_contradiction", ...)` exists as a tool action. Before the demo, the full flow
needs to be exercised end-to-end:

- Agent A writes finding F1 to project scope.
- Agent B searches and finds F1.
- Agent B writes finding F2 that contradicts F1 (also to project scope).
- Some agent (B itself, or a curator agent) calls `manage_curation(action="report_contradiction", ...)`
  pointing at F1 with F2 as the contradicting evidence.
- A query surfaces the contradiction in some queryable form.
- The demo shows resolution: either F1 is marked obsolete, F2 is marked
  obsolete, or the contradiction is left open with a note explaining the
  ambiguity.

Each step needs to be verified to actually work. There may be gaps —
that's a discovery exercise, not a build exercise (yet).

### 6. Agent generation CLI

Tracked in [cli-requirements.md](cli-requirements.md). Wes is implementing.
This unblocks fleet provisioning for the demo.

### 7. The agents themselves

The 50-ish small agent loops, one per role/instance. These get built once
the scenario is picked and the contracts above are stable. Each agent is
small (a Python script + Containerfile), and most of them will be
templated from a common base.

## Demo run-of-show outline

This is a sketch of how the demo might flow once everything is built.
The actual run-of-show gets refined closer to the demo.

1. **Identity & provisioning** (~3 min)
   - Show the fleet manifest YAML.
   - Run the generation CLI; show the produced ConfigMap and Secrets.
   - Apply to the cluster.
   - Show all 50 agents starting up and registering with MemoryHub.

2. **Hive-mind learning** (~5 min)
   - Drive the workflow scenario through the harness.
   - Show triage nurse posting an observation to project scope.
   - Show attending physician searching project scope and finding it.
   - Show how the attending's behavior changes based on the memory.

3. **Audit & attribution** (~3 min)
   - Show the audit log (or grepped log lines) for the run so far.
   - Run the query "everything Agent #07 did" — show the result.
   - Run the query "everything done on behalf of `claude-code-cli-run-14`" —
     show the result.
   - Highlight the actor/driver distinction.

4. **Contradiction detection** (~3 min)
   - Drive the workflow to the point where two agents reach different
     conclusions.
   - Show the contradiction being reported.
   - Show the resolution flow.

5. **Governance: PHI quarantine** (~3 min)
   - Drive an agent to attempt to log a memory containing synthesized PHI.
   - Show the curation pipeline catching it.
   - Show the quarantined memory and the audit event.
   - Explain the policy that caught it.

6. **Q&A and roadmap** (~5 min)
   - Field questions.
   - Quickly cover what's not yet built (Phase 2 token exchange, full
     audit log persistence, intersection authorization) and the migration
     story.

Total: ~22 minutes, which is right for a focused technical demo.

## What we're explicitly not demoing

- Tenant isolation (out of scope)
- Phase 2 OAuth token exchange (future work)
- Intersection authorization enforcement (future work; data model
  supports it but the demo runs in audit-only mode)
- Full audit log persistence (stub interface only)
- `driver_id` redaction on read (future work)
- The Operator / dynamic CRD-driven provisioning (the agent generation CLI
  is the static-provisioning answer for the demo)

## Open questions

- *Which clinical workflow do we mock?* Needs to be picked. ED visit with
  new prescription is a candidate; happy to evaluate alternatives.
- *Where do we get a realistic-looking-but-synthesized clinical scenario?*
  Possible sources: published clinical pathway docs, MIMIC-IV dataset
  (synthesized case mixes), or hand-rolled. Hand-rolled is fine if the
  scenarios are vetted by someone with clinical domain knowledge.
- *Do we want a GUI for the demo presenter, or is a tmux session showing
  multiple panes (harness, agent logs, MemoryHub events) sufficient?*
  tmux is honest and demo-able. A GUI is nicer but separate work.
- *What's the demo's recording strategy?* If we want to ship a recorded
  version, that affects how much the harness needs to be polished.
