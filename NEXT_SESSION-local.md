# Next Session -- Local

## Epic complete

All 5 phases shipped. 37 commits on `feat/personal-edition`. 41 tests green.

Next step: PR `feat/personal-edition` into `main`.

## Remaining epic phases

A developer runs `pip install "memoryhub[local]"` +
`claude mcp add memoryhub -- memoryhub mcp` and has working, versioned,
searchable memory on their laptop with the same tool surface as the
cluster edition. No database server, no API keys, no background services.

Architecture doc: `planning/personal-edition.md` (grounded 2026-07-27).
Branch: `feat/personal-edition`.

### Phase 1: RecallBackend protocol + SQLiteBackend (2 sessions) -- DONE

**Commits:** `907602f`..`d88a86a` (14 commits on feat/personal-edition)

### Phase 2: Local MCP server + `memoryhub mcp` CLI (2 sessions) -- DONE

**Commits:** `4006fc1`..`1149890` (9 commits on feat/personal-edition)

### Phase 3: Local ONNX embeddings (1 session) -- DONE

**Commits:** `2b8f5fc`..`450064b` (4 commits on feat/personal-edition)

### Phase 4: Extraction + maintenance (1 session) -- DONE

**Commits:** `fc485a6`..`dd72a17` (6 commits on feat/personal-edition)

Extraction service with LLM-agnostic pipeline, thread extract action via
MCP sampling, on-connect dreaming in register_session, shared startup
helper, `memoryhub dream` CLI with Ollama support. 11 extraction tests.

### Phase 5: Onboarding + docs (1 session) -- DONE

**Commits:** `260c6ec`..`dc40694` (feat/personal-edition)

README quickstart with two-command install + from-source path, edition
parity matrix (PARITY.md), clean-venv verification of full round-trip.
Closed #460, #461, #462.

---

## What landed last session (2026-07-28, P5S1)

Phase 5 complete. README quickstart, parity matrix, clean-venv verification.

**Session summary:** `session-summaries/2026-07-28-personal-edition-p5s1.md`

## Open watch-fors (carry to PR review)

- **MCP sampling verification:** the sampling round-trip (agent writes thread,
  extraction runs, facts appear) needs manual testing with a live agent session.
- **Ollama verification:** `memoryhub dream --model llama3.2` needs a running
  Ollama instance.
- **PyPI publishing:** two-command install path requires publishing memoryhub,
  memoryhub-cli, and memoryhub-local to PyPI. From-source path documented as interim.
