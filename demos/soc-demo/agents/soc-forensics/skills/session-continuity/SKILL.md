---
name: session-continuity
description: Resume and hand off work across agent sessions using the work-item pool
version: "1.0"
triggers:
  - resume work
  - hand off
  - pick up where I left off
  - check for work
  - session continuity
dependencies: []
parameters: {}
---

# Session Continuity

Manages seamless work transitions across agent sessions by following a
structured resume and handoff protocol with the work-item pool.

## When to activate

- At the start of a session when work items may be available.
- When the agent's budget or time is running low and it needs to hand
  off cleanly.
- When the agent encounters a blocker and needs to release its current
  work item.

## Resume steps

1. Call `check_available_work` to see pending items.
2. Review any handoff notes from previous attempts.
3. Verify the environment (services, data, outputs from prior work).
4. Call `checkout_work_item` to claim the most appropriate item.
5. Plan your approach based on the handoff note and current state.

## Handoff steps

1. Call `update_work_progress` with your current status.
2. Verify your work (run tests, check outputs).
3. If done: `complete_work_item` with results and accomplishments.
4. If blocked or out of budget: `release_work_item` with a structured
   handoff note.

## Domain-Specific AgentState Examples

Define a typed `AgentState` subclass to track session progress. The
framework checkpoints it automatically and replays from traces on
recovery.

### Document processing

```python
class DocProcessingState(AgentState):
    batch_id: str = ""
    total_documents: int = 0
    processed: list[str] = []
    failed: dict[str, str] = {}   # doc_id -> error
    current_document: str | None = None
```

### Research / investigation

```python
class ResearchState(AgentState):
    questions: list[dict] = []     # {id, text, status, answer}
    sources_reviewed: list[str] = []
    hypotheses: list[dict] = []    # {claim, confidence, evidence}
```

### Compliance monitoring

```python
class ComplianceState(AgentState):
    framework: str = ""            # SOC2, FedRAMP, etc.
    sections: dict[str, str] = {}  # section_id -> status
    findings: list[dict] = []
    last_reviewed: str | None = None
```

## Handoff Note Quality

A good handoff note answers five questions:

1. **What was accomplished?** Concrete, verifiable statements with
   artifact references.
2. **What was attempted but failed?** Including the failure reason —
   the next actor should not retry the same approach.
3. **What remains?** Scoped to the work item, not the entire project.
4. **What blocks progress?** Missing access, broken infra, ambiguity.
5. **Where are the artifacts?** File paths, URLs, trace IDs, commit
   SHAs.
