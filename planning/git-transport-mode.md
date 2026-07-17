# Git and File Storage: Viability Analysis and Design Position

**Status:** Position + design sketch
**Date:** 2026-07-16
**Author:** @rdwj (designed with Claude in Cowork)
**Builds on:** `planning/personal-edition.md` (SQLite canonical store,
membership ladder, scope homing), #347 (reconciliation — reused here as
the merge engine)
**Prompted by:** recurring external interest in "memories as files in
git"

## Position (one paragraph)

"Git storage mode" bundles two proposals with opposite verdicts.
**Files-as-canonical-store (git as the database): no** — the analysis
below gives the specific failure modes and the boundary past which it
recreates a bad database. **Git-as-transport between canonical local
stores: yes** — it is the natural middle rung of the membership ladder
(personal -> git-team -> cluster), it reuses reconciliation as its merge
engine, and it converts market interest in file-based memory into a
funnel toward the governed architecture instead of a fork away from it.
A documented serialization format ships regardless, as the
export/portability/backup story.

## Part 1: Why files-as-canonical fails (the engineering "no")

1. **Merge semantics.** Git merges lines; memory requires semantic
   reconciliation. Concurrent updates to one memory on two clones
   produce either a manual textual conflict or silent divergence. The
   only real fix is a custom git merge driver that embeds the
   reconciliation engine and runs on every clone at pull time —
   reimplementing #347 inside git's merge machinery, per-user,
   per-clone.
2. **Double bookkeeping.** MemoryHub version chains and git commit
   history both claim to be the history. Serialize chains into files ->
   file explosion and repo bloat; keep chains local-only -> the core
   governance value (versioning, is_current, provenance) silently fails
   to transport. There is no clean resolution; every design falls into
   one of these two holes.
3. **Divergent curation.** Curation/reconciliation gates run per-clone
   with nondeterministic LLM tiebreakers -> different clones reach
   different verdicts about the same candidate -> stores diverge, then
   conflict at sync.
4. **Secrets and privacy.** Memories land in effectively-immutable repo
   history. This project has already run one credential-scrub incident;
   a memory store IN git multiplies that surface. The cluster has
   delete + audit; git has BFG and regret.
5. **Scale mechanics.** Tens of thousands of small files degrade clone
   and status times; reconciliation churn becomes commit noise;
   embeddings/indexes are derived state that must NOT be committed, so
   every clone rebuilds them anyway (which quietly concedes that the
   files are not the whole store).

**Viability boundary, stated fairly:** files-as-canonical works to
roughly 10 users / low-thousands of memories / PR-mediated writes /
project scope only / low churn. Inside that box it is a workable
artisanal system. The box's edges are exactly where MemoryHub's actual
customers live outside of.

## Part 2: Git as transport (the engineering "yes")

Each participant runs the personal edition — **SQLite remains canonical
on every machine**; indexes and embeddings stay local and derived. Git
carries a serialized projection of *shared-scope* memories:

```
memoryhub sync git [--remote origin]
  export: project-scope memories -> .memoryhub/memories/*.md
          (stable per-memory serialization; see Part 3)
  commit/push: normal git, normal review culture if the team wants PRs
  import (on pull): reconciliation-as-merge INSIDE MemoryHub --
          incoming candidates run the #347 pipeline against the local
          store: exact-dup skip, update-with-version, create, or
          flag -- with the decision log as the merge record
```

What each party contributes:

- **Git does what git is good at:** transport, offline/async sync,
  backup, repo-permission access control, and a human review surface
  (memory changes as PRs — the exact workflow this project already uses
  for CLAUDE.md, proven where humans should review).
- **MemoryHub does what git cannot:** semantic merge, per-fact
  versioning, retrieval, extraction, honesty flags. Conflicts surface
  as reconciliation decisions, never as `<<<<<<<` markers.
- **Scope homing does the privacy work:** user-scope memories NEVER
  serialize into a shared repo. Project scope only, by construction.
  (Same rule as the membership design in personal-edition.md 6b.)

Known limits, stated in docs from day one: sync-time consistency (not
live push updates — that is the cluster's job); repo-granular access
control (not per-scope RBAC); history in two places (git history is the
transport log; MemoryHub chains are the memory history — the
serialization carries chain summaries so provenance survives transport).

## Part 3: The serialization format (ships regardless)

One file per memory, markdown with YAML frontmatter (id, scope, owner,
weight, domains, branch_type, version, extraction run id, provenance
refs, embedder id) + content body. Deterministic filenames (id-based),
stable field ordering (clean diffs). `memoryhub export` / `import`
against any directory — the data-portability, backup, and
"never locked in" answer, valuable for trust independent of git-sync.
Format versioned; documented in docs/ once implemented.

## Part 4: The 3-person team, answered concretely

Shared CLAUDE.md wins while team memory is *constitutional*: dozens of
stable conventions, loaded whole, changed rarely, reviewed always. It
loses on three axes as volume/churn grow: (1) load-everything — no
retrieval, context cost grows with every fact; (2) versions the file,
not the facts — no per-memory history, no is_current, no cheese test;
(3) one hot file — merge conflicts, and agents writing operational
memories into the constitution degrades the constitution.

Rule of thumb for docs: **under ~50 stable facts, use CLAUDE.md; above
that, or with churn, or when agents write memories mid-session, use
git-transport mode.** They compose: constitution in CLAUDE.md,
operational memory in `.memoryhub/` — which is how this project itself
operates today (CLAUDE.md + MemoryHub), just with git in place of the
cluster.

## Onboarding and the sqlite-copy question (2026-07-16)

New-teammate onboarding is not a feature — it is a consequence of
transport: `git clone` + `memoryhub sync git` hydrates the team's
project memory locally (embeddings rebuilt on import; provenance
summaries carried by the serialization). No separate mechanism.

Copying the SQLite file itself is the wrong tool for sharing (binary
blob: no diffs, no review, whole-file conflicts, carries user-scope
private data, couples schema/embedder versions) and the right tool for
personal backup and device migration (copy file, restore file — free).
Doctrine: **the SQLite file is your memory moving between your
machines; serialized files in git are the team's memory moving between
people.**

## Ladder placement and sequencing

personal (n=1, SQLite) -> **git-team (n≈2-10, SQLite + git transport)**
-> cluster (org, governed multi-tenant). `memoryhub join` upgrades a
git-team member to a cluster the same way it upgrades a solo user —
curated promotion, provenance preserved.

Sequencing: strictly after personal-edition P1-P4 (needs the SQLite
backend and the serialization format) and materially better after #347
(reconciliation is the merge engine — before it lands, import can only
do exact-dup skip + create + flag, no semantic update). Candidate P7 of
the personal-edition epic. The export/import format (Part 3) can land
earlier, with P5.

## Open questions

1. Import trust: a teammate's repo push injects memories into my store
   at sync — curation gates apply, but the poisoning threat model
   (#334) gains a "malicious teammate commit" case (mitigated by PR
   review where teams use it).
2. Deletion semantics across clones (tombstone files? retention of
   soft-deletes in the serialization?).
3. Whether `sync git` runs reconciliation tiebreakers via sampling
   (connected-session import) or defers ambiguous merges to a review
   queue — leaning: defer, keep import deterministic.
