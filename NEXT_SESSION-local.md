# Next Session -- Local

## Next: Onboarding + docs (Phase 5)

Final phase of the personal-edition epic. All code is shipped (Phases 1-4,
41 tests green). This session is pure documentation and verification.

1. **#460 -- README quickstart with two-command install path**
   Rewrite the 5-line stub README with a full quickstart covering install,
   Claude Code integration, tool surface, and CLI commands (doctor, dream, mcp).

2. **#461 -- Parity matrix (personal vs cluster features)**
   Feature comparison table: storage, embeddings, extraction, auth, multi-tenancy,
   curation, governance.

3. **#462 -- Clean-venv quickstart verification** (depends on #460)
   Test the quickstart on a fresh venv + fresh user directory. This IS the
   exit predicate: "an outsider follows the README and has working memory
   in 10 minutes."

**Sequencing.** #460 first (write the docs), #461 in parallel or after,
#462 last (verify #460 works end-to-end).

**Session start protocol:**
- Premise checks: `git log --oneline feat/personal-edition` shows 33+
  commits; Phase 4 complete (extraction pipeline, 41 tests); working tree clean
- Rules with history: all pushes through PRs; stop-and-ask before modifying
  existing published packages (sdk/, memoryhub-cli/)
- Close ritual: session summary + NEXT_SESSION update

**Exit predicate:**
- README quickstart covers install, setup, and tool surface
- Parity matrix published
- Quickstart tested on clean venv -- an outsider can follow it in 10 minutes

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

### Phase 5: Onboarding + docs (1 session) -- NEXT

See "Next" section above. Issues: #460, #461, #462.

---

## What landed last session (2026-07-28, P4S1)

Phase 4 complete. 6 commits shipped the extraction pipeline.

**Session summary:** `session-summaries/2026-07-28-personal-edition-p4s1.md`

## Watch out for

- **MCP sampling verification:** the sampling round-trip (Claude Code writes
  a thread, extraction runs, facts appear) needs manual testing with a live
  agent session. Can't be automated without Claude Code running.
- **Ollama verification:** `memoryhub dream --model llama3.2` needs a running
  Ollama instance. Not all models support `response_format: {"type": "json_object"}`.
- **httpx dependency:** `memoryhub dream` requires httpx which is an optional
  `[dream]` extra, not in the core deps. The quickstart should mention this.
- **transformers dependency size:** ~200MB+. Quickstart should set expectations
  about first-run download time.

## If blocked

- If quickstart verification hits a bug in the local server, fix the bug
  first (that's a higher-priority finding than finishing the docs).
- If ONNX model download is unreliable, document the fallback
  (`memoryhub doctor` shows mock-embedding status).
