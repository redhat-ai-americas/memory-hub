# Session Summaries

Developer work-session handoff notes. Each file records what a Claude Code
coding session planned, committed, deployed, and left for the next session.

These are **not** MemoryHub runtime sessions (`register_session(...)`, the
authenticated agent memory sessions documented in
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)). The naming collision is
unfortunate but entrenched.

## Naming convention

`YYYY-MM-DD-<epic>-<slug>.md`

## Typical header fields

- **Plan** -- which `NEXT_SESSION-*.md` file and issue drove the session
- **Commits** -- range or squash-merge SHA
- **Deployed** -- what was deployed (or "none")
- **Model** -- which Claude model was used
