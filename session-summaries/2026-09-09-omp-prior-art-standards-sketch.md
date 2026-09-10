# Session Summary — 2026-09-09 · OMP · Prior art survey and standards sketch

**Plan:** Ad-hoc (Wes joining the Open Memory Protocol project)
**Commits:** 07d9b83, 50f1eca (Open-Memory-Protocol repo, fork rdwj/)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: explore the OMP project, discuss protocol design, contribute
prior art research and standards proposals. Shipped: full prior art
survey (7 documents) and standards sketch (5 documents), two PRs
submitted. No slippage; scope expanded organically from discussion
through research into deliverables.

## Shipped
- PR #3: `prior-art/` directory with survey of 16 agent harnesses, 10
  enterprise memory services, 12 emerging standards, interoperability
  protocol landscape, academic foundations, and convergence analysis
  (07d9b83)
- PR #4: `standards-proposals/` directory with Memory Object Format
  (MOF), Memory Access Protocol (MAP), Memory Rights Standard, and
  Memory Security Considerations (50f1eca)
- Both PRs to The-AI-Disclosures-Project/Open-Memory-Protocol from
  fork rdwj/Open-Memory-Protocol, IlanStrauss tagged for review

## Verification & confidence
- Factual accuracy of prior art: research agents read source code of
  OpenClaw, Hermes, Pi, PAM, Letta trajectory, and the OMP spec PDFs
  at the code level. Enterprise and cloud vendor coverage drawn from
  broader landscape research.
- Standards sketches: reviewed through iterative discussion with Wes;
  MOF field list cross-checked against MemoryHub's actual data model
  (28 DB columns audited).
- Security considerations informed by direct reading of PTC spec and
  PTC/GAL reference implementation source code.
- Confidence: medium-high. The prior art survey covers the major
  systems but may miss niche projects. The standards sketches are
  intentionally high-level; correctness at this altitude is about
  framing, not specification detail.

## Judgment calls & deviations
- Renamed "Standards Proposals" to "Standards Sketch" at Wes's
  direction to signal early-stage intent
- Referenced PTC for provenance/trust rather than sketching a separate
  provenance standard, based on Wes's identification that PTC already
  covers this
- Kept the security considerations as a discussion document rather
  than a formal sketch, per Wes's guidance
- Renamed coding-agent-memory-systems.md to agent-harness-memory-
  systems.md after adding OpenClaw, Hermes, and Pi (general-purpose
  agents, not just coding tools)
- Did not create a separate platform-level spec; folded platform
  concerns (multi-tenancy, extended scopes, RBAC) into MOF and MAP
  per discussion

## Backlog delta
Filed: none. Closed: none. No issues created this session.
Memory: none written (research session in external repo).

## Drift & forward-collisions
- Backward: none. This session worked in a separate repo (OMP), not
  in the memory-hub codebase.
- Forward: the MOF field list was cross-checked against MemoryHub's
  data model. If OMP converges on a standard memory object format,
  MemoryHub will need a conformance mapping. Not actionable yet.

## For the reviewer
- Sanity-check: the security considerations document's 9-step context
  assembly pipeline (principle 5) is the most prescriptive part of
  the sketches. Worth checking whether the ordering is defensible or
  over-specified for this stage.
- Thin verification: enterprise memory services (AWS AgentCore, Google
  Vertex, Microsoft Foundry) were researched from documentation and
  blog posts, not source code (proprietary). Claims about their
  architectures are based on public documentation.
- Wants guidance: none at this stage; waiting for OMP working group
  feedback on PRs #3 and #4.

## Risks / watch-fors
- The OMP project's first convening was today (2026-09-09). The
  working group may take the protocol in a different direction than
  what we sketched. The sketches are deliberately lightweight to
  accommodate this.
- PTC is referenced throughout as the trust layer. If the OMP working
  group prefers a different trust/provenance approach, the security
  considerations document would need significant revision.
