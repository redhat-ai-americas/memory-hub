# Trust Bricks Alignment: PTC and GAL for Agent Memory

Status: Research / Standards Assessment
Date: 2026-08-11
Source: [Trust Bricks](https://wjatx.github.io/trust-bricks/) (safe-agents composition model, v0.2.1-draft)

## Context

Trust Bricks defines two proposed standards that address gaps in the
agent safety landscape:

- **PTC (Provenance & Trust Context)** -- signed envelope mechanism
  with append-only provenance chains and Biba lattice taint markers.
  Addresses "the trust seam": knowing where data came from and whether
  a receiver should trust it.
- **GAL (Grant & Autonomy Lifecycle)** -- authority as signed, stored
  state linked to principals and action classes. Promotions require
  maker/checker ceremonies; demotions are automatic and ceremony-free.
  Addresses "the authority seam."

Both standards are transport-orthogonal and designed to compose with
MCP (agent-to-tool) and A2A (agent-to-agent). The framework also
adopts DSSE, in-toto, SPIFFE/WIMSE, and a Biba integrity lattice.

This document assesses where MemoryHub's existing design aligns with
these standards, where compliance would provide genuine differentiation,
and what implementation would look like.

## The core insight for memory systems

Trust Bricks' central claim: "a capability's autonomy rung is capped by
what the mesh can currently prove about its inputs." PTC supplies the
proof; GAL manages the state transitions.

Applied to memory: no agent memory product today tells the consuming
agent how much to trust a recalled fact. Every memory is treated as
equally authoritative regardless of whether a human wrote it, an agent
inferred it from verified docs, or an agent guessed it from a forum
post. That's the gap.

## PTC alignment: provenance metadata on memories

### What PTC provides

PTC envelopes carry:
- Sender classification (owner, peer, tool, unknown)
- Append-only provenance chain (who produced this, from what sources)
- Biba lattice taint markers (tainted/untainted, with five-level vocabulary)
- Cryptographic binding via DSSE over in-toto statements

### How this maps to MemoryHub

**Existing infrastructure that aligns:**
- `source` column on memory_nodes (agent / dreaming / import) -- this
  is a primitive form of provenance, tracking the producer but not the
  upstream lineage.
- `report_contradiction` -- structural analog to GAL's demotion triggers.
- Memory versioning -- append-only version history exists.
- Scope hierarchy (user / project / org / enterprise) -- maps to
  integrity tiers.

**What's missing:**
- No taint propagation. A memory extracted from an unverified web page
  and a memory extracted from an internal design doc have identical
  trust signals today.
- No upstream lineage. We know *who* wrote the memory but not *what
  sources informed it*.
- No receiver-side taint re-derivation. When an agent retrieves a
  memory, it has no mechanism to evaluate the memory's trustworthiness
  under its own trust policy.

### Proposed: PTC-lite envelope on memory nodes

Add provenance metadata to memory entries without requiring full
cryptographic signing infrastructure (that can come later as a Tier 3
upgrade):

```
provenance:
  origin_class: agent | human | extraction | import
  source_taint: tainted | untainted
  taint_reason: "derived from external web content" | null
  lineage:
    - source: "conversation:sess_abc123"
      producer: "agent:claude-code"
      timestamp: "2026-08-11T14:30:00Z"
    - source: "document:planning/auth-design.md"
      producer: "pipeline:dreaming"
      timestamp: "2026-08-11T12:00:00Z"
  integrity_tier: 1 | 2 | 3
```

**Tier 1 (taint flags):** Memories carry a tainted/untainted flag and a
reason string. Agents can filter or rank by taint status. Low
implementation cost. This is the starting point.

**Tier 2 (full lineage):** Memories carry the provenance chain showing
upstream sources. Agents can trace why a memory is tainted and decide
whether to trust it anyway. Moderate implementation cost.

**Tier 3 (signed lineage):** Provenance chains are cryptographically
signed via DSSE. Required for acting-rung eligibility in a full GAL
deployment. Higher infrastructure cost (needs broker identity via
SPIFFE/WIMSE or DID).

### Taint propagation on recall

When a memory is recalled and used in an agent's reasoning, PTC says
the taint follows. MemoryHub could support this by:

1. Including taint metadata in search results (already have `source`;
   extend with `source_taint` and `integrity_tier`).
2. Providing a `taint_policy` parameter on search: `strict` (exclude
   tainted), `annotated` (include with markers), `permissive` (no
   filtering).
3. Documenting that consuming agents should propagate taint to any
   memories they write based on tainted inputs.

Step 3 is a convention, not enforcement. Full enforcement would require
the harness to track taint through the agent's reasoning, which is
outside MemoryHub's scope but within a Trust Bricks-compliant harness's
scope.

## GAL alignment: trust lifecycle for memories

### What GAL provides

GAL manages authority through:
- Rungs (levels of autonomy/trust)
- Promotion ceremonies (maker proposes, predicate checks, checker
  ratifies, ledger records)
- Automatic demotion on four triggers (stale_confidence,
  corroboration_failure, budget_breach, false_action)
- Append-only ledger of all transitions

### Memory trust rungs

Applying GAL's rung concept to memories rather than agents:

| Rung | Name | Meaning | Entry condition |
|------|------|---------|-----------------|
| 0 | Asserted | Agent wrote it, no corroboration | Default on write |
| 1 | Corroborated | Independent evidence supports it | Predicate: N independent sources, M recall cycles without contradiction |
| 2 | Verified | Human-confirmed or from authoritative source | Human ratification or signed-source provenance |
| 3 | Policy | Organizational policy, highest trust | Human ratification + enterprise scope |

### Promotion ceremonies for memories

**Rung 0 -> 1 (Asserted -> Corroborated):**
- Maker: Any agent that encounters corroborating evidence
- Evidence: `corroborate_memory(memory_id, evidence_type, evidence_ref)`
- Predicate: >= 2 independent corroborations, >= 3 recall cycles
  without contradiction, evidence fresher than 30 days
- Checker: Different agent session or different agent identity
  (no self-promotion)
- Movement: Automatic once predicate satisfied, no human needed

**Rung 1 -> 2 (Corroborated -> Verified):**
- Maker: Agent or human proposing verification
- Evidence: Human confirmation in conversation, or provenance chain
  showing derivation from a signed/authoritative source
- Predicate: Human-class PTC envelope on the confirmation, or Tier 2+
  provenance with untainted lineage
- Checker: Human (always, for this rung)
- Movement: After human ratification

**Rung 2 -> 3 (Verified -> Policy):**
- Maker: Human proposing policy status
- Evidence: Enterprise-scope designation, organizational approval
- Predicate: Enterprise scope, human ratification, Tier 2+ provenance
- Checker: Different human (maker != checker for policy)
- Movement: After second human ratification

### Demotion triggers for memories

Mapping GAL's four triggers to memory operations:

**stale_confidence:** Memory hasn't been accessed or corroborated in a
configurable window (e.g., 90 days). Trust weight decays; rung drops to
max(current - 1, 0). Recalled memories surface with a staleness marker.
MemoryHub could implement this as a background job or on-access check.

**corroboration_failure:** An agent calls `report_contradiction`. Today
this increments a counter. Under GAL, a single contradiction from a
verified source (Rung 2+) drops the memory one rung immediately. Multiple
contradictions from asserted sources accumulate toward a threshold.

**budget_breach:** A memory was written at a scope the writer wasn't
authorized for (e.g., agent wrote enterprise-scope without human
approval). Rung drops to 0. This requires scope-authority enforcement
that doesn't exist today but aligns with planned RBAC work.

**false_action:** A decision based on this memory led to a reported bad
outcome. An agent calls `report_false_action(memory_id, description)`.
Rung drops to 0; re-promotion requires fresh evidence and a dwell-time
delay. Hardest to detect automatically; depends on agents self-reporting.

### Re-promotion after demotion

GAL requires fresh evidence and dwell-time delays for re-promotion.
A contradicted memory can't be immediately re-confirmed; it must
accumulate new corroborating evidence after a cooling-off period. This
prevents "memory thrashing" where two agents repeatedly confirm and
contradict the same fact.

### Ledger

All rung transitions (up and down) are recorded in an append-only
ledger: who proposed, what evidence, what the predicate evaluated, who
ratified (if applicable), timestamp. This is the audit trail that
regulated environments need.

MemoryHub's existing version history is a partial implementation. The
gap is that version history tracks content changes, not trust-state
transitions. A separate `memory_trust_ledger` table (or extension of
the existing audit infrastructure) would close this gap.

## Implementation priority

### Phase 1: PTC Tier 1 (taint flags)

Low cost, high signal. Add `source_taint` and `taint_reason` to
memory_nodes. Expose in search results. Allow filtering by taint
status. This alone differentiates MemoryHub from every competitor.

### Phase 2: GAL demotion triggers

Formalize the existing contradiction system. Add staleness-based
decay. Define rung levels and implement automatic demotion. The
promotion side can wait; demotion is where the immediate safety
value lives.

### Phase 3: PTC Tier 2 (full lineage)

Add provenance chain metadata. Requires changes to the write path
(agents and the dreaming pipeline must record their sources) and the
read path (search results include lineage).

### Phase 4: GAL promotion ceremonies

Implement corroboration tracking, promotion predicates, and the
maker/checker separation. This is the most complex phase and depends
on Phases 1-3.

### Phase 5 (optional): PTC Tier 3 (signed lineage)

Cryptographic signing via DSSE. Requires broker identity infrastructure
(SPIFFE/WIMSE). Only needed for acting-rung eligibility in a full
Trust Bricks deployment or for regulated-environment audit requirements.

## Standards adopted by Trust Bricks (relevance to MemoryHub)

| Standard | Role in Trust Bricks | MemoryHub relevance |
|----------|---------------------|---------------------|
| MCP | Agent-to-tool connectivity | Already used (primary interface) |
| A2A | Agent-to-agent connectivity | Not directly relevant; MemoryHub is a service, not an agent |
| DSSE | Signature encoding | Phase 5 (signed provenance) |
| in-toto | Attestation format | Phase 5 (signed provenance) |
| SPIFFE/WIMSE | Workload identity | Phase 5 (broker signing keys) |
| DID | Fallback identity | Phase 5 alternative to SPIFFE |
| Biba lattice | Integrity model | Phase 1 (two-level taint projection) |
| Ed25519 | Signature algorithm | Phase 5 |

## Declined standards (Trust Bricks rationale, applicable here too)

- **Cedar:** Cannot express transform verbs or polarity seams. Not
  applicable to memory access control.
- **OPA/Rego:** Reproduces gate functionality without formal
  analyzability. MemoryHub's scope-based access control is simpler
  and sufficient.

## References

- [Trust Bricks](https://wjatx.github.io/trust-bricks/)
- [PTC & GAL Data Flow](https://wjatx.github.io/trust-bricks/data-flow.html)
- [Standards Landscape](https://wjatx.github.io/trust-bricks/standards.html)
- [Agent Memory Protocol RFC](../research/agent-memory-protocol-rfc.md)
- [Memory Source Tagging](../planning/memory-source-tagging.md)
