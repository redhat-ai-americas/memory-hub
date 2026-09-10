# Session Summary — 2026-09-09 · OMP · Prior art survey, standards sketch, and epic planning

**Plan:** Ad-hoc (Wes joining the Open Memory Protocol project)
**Commits:** 07d9b83, 50f1eca (OMP repo); a3ceca4..bb65886 (memory-hub)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: explore the OMP project, discuss protocol design, contribute
prior art research and standards proposals. Shipped: full prior art
survey, standards sketch, PTC/RI-informed security analysis, MemoryHub
improvements design doc, 9 issues, and an epic plan with next-session
slice. Scope expanded well beyond the initial exploration into a
complete contribution and backlog for an omp-interop epic.

## Shipped
- OMP PR #3: `prior-art/` directory (7 docs, ~90KB) -- 16 harnesses,
  10 enterprise services, 12 standards, protocol landscape, academic
  foundations, convergence analysis (07d9b83)
- OMP PR #4: `standards-proposals/` directory (5 docs, ~25KB) -- MOF,
  MAP, Memory Rights Standard, Memory Security Considerations (50f1eca)
- IlanStrauss tagged for review on both PRs
- Security considerations updated with PTC RI patterns: indirect
  channel injection threat, provenance survival through extraction,
  9-step context assembly pipeline, memory source admission (50f1eca)
- `planning/omp-informed-improvements.md` design doc (9ecdb63)
- 9 issues filed: #559-567, covering trust provenance, MOF export,
  context assembly pipeline, dreaming gates, PTC taint hook, consent
  signals, contradiction alignment, generating_model, source admission
- #516 closed as superseded by #559 + #563
- `NEXT_SESSION-omp-interop.md` epic plan with 4 phases (24dfbcf)
- Next session planned: Phase 1 (#559 + #562) (bb65886)

## Verification & confidence
- Prior art: research agents read source code of OpenClaw, Hermes, Pi,
  PAM, Letta trajectory, OMP spec PDFs, PTC spec, and PTC/GAL RI at
  the code level. Enterprise/cloud vendor coverage from public docs.
- Standards sketches: iterative discussion with Wes; MOF field list
  cross-checked against MemoryHub's 28 DB columns.
- Security document: informed by direct reading of PTC RI source code
  (taint propagation, airlock pipeline, tool admission, endorsement).
- MemoryHub improvements: each recommendation traced to a specific
  ecosystem finding or RI pattern.
- Confidence: medium-high. Survey covers major systems; may miss niche
  projects. Enterprise services researched from docs, not source.

## Judgment calls & deviations
- "Standards Sketch" not "Standards Proposals" -- signal early-stage
  intent, per Wes's direction
- PTC referenced for provenance/trust rather than reinventing
- Platform concerns (multi-tenancy, RBAC, extended scopes) folded into
  MOF/MAP rather than a separate platform spec
- Security document kept as discussion framing, not formal sketch
- Epic sequenced for pivot safety: internal hardening first (Phases
  1-2), OMP-dependent work after feedback (Phases 3-4)
- Renamed coding-agent-memory-systems.md to agent-harness-memory-
  systems.md after adding OpenClaw, Hermes, Pi

## Backlog delta
Filed: #559, #560, #561, #562, #563, #564, #565, #566, #567
Closed: #516 (superseded by #559 + #563)

## Drift & forward-collisions
- Backward: #516 closed as superseded by the new issues
- Forward: the design doc and issues lay groundwork for OMP conformance.
  If OMP converges on MOF, MemoryHub's Phase 3 (#560) implements the
  export format. No forward-collision comments needed yet (all issues
  are in the same epic).

## For the reviewer
- Sanity-check: the 9-step context assembly pipeline (security doc
  principle 5) is the most prescriptive element. Worth checking whether
  the ordering is defensible at this stage.
- Sanity-check: sequencing Phases 1-2 as "OMP-independent" assumes the
  upstream_trust_level field and dreaming gates are valuable regardless
  of standard direction. This seems safe but worth confirming.
- Thin verification: enterprise memory services (AWS AgentCore, Google
  Vertex, Microsoft Foundry) researched from public docs, not source.
- Wants guidance: none. Waiting for OMP working group feedback on PRs.

## Risks / watch-fors
- OMP working group may diverge from our sketches. Phases 1-2 are
  insulated; Phases 3-4 may need revision.
- PTC is referenced as the trust layer throughout. If OMP prefers a
  different approach, the security document needs revision.
- The indirect channel injection threat (Slack/Gmail to memory pipeline)
  is real but MemoryHub doesn't currently ingest from external channels.
  Becomes urgent if channel connectors are added.
