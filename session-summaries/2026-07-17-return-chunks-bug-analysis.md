# Bug Analysis: return_chunks causes 0% dreaming benchmark accuracy

**Date:** 2026-07-17
**Affected:** All dreaming-mode EvalHub eval configs, any harness run using `return_chunks=true`
**Fixed in:** PR #433

## Symptom

Every dreaming-mode EvalHub benchmark scored exactly 0%. The MCP server
logs showed search requests being processed and returning data, but the
harness reported `context len: 0 chars` and `judge_reason: empty context
— no memories retrieved` for every query.

## Root cause

The eval configs included `return_chunks: "true"` as a benchmark
parameter. The adapter mapped this to `MEMORYHUB_RETURN_CHUNKS=true`,
which caused the harness's MemoryHub provider (`memoryhub.py:353-355`)
to add two flags to the SDK search call:

```python
if self._return_chunks:
    search_kwargs["return_chunks"] = True
    search_kwargs["raw_results"] = True
```

When `return_chunks=True` and `raw_results=True` are passed to
`client.search()`, the MCP server returns results in a chunked response
format. The SDK's `SearchResult.model_validate(data)` parsed this
response but the `results.results` list ended up empty -- the chunked
response structure doesn't map to the `results` field that the harness
iterates over.

The harness then built an empty document list, produced a 0-char context
string, and the runner's empty-context guard (`runner.py:197-198`)
short-circuited to `correct=False` without ever calling the answer LLM.

## Why the model appeared to be called

The runner logs showed `gemini-3.1-pro-preview:generateContent` HTTP
requests even for 0-context queries. This is because the runner's
empty-context check happens AFTER `mode.async_answer()` returns -- the
RAG mode calls the LLM regardless of context content, and the runner
only checks the context afterward. So the model was called with an empty
`## Memory` list, answered based on the question alone (usually wrong),
and then the runner discarded the answer because context was empty.

## Secondary issue: stale env vars

The adapter's `run_benchmark_job()` starts with `load_dotenv(override=True)`
and then sets env vars from the job parameters:

```python
for param_key, env_key in param_to_env.items():
    val = params.get(param_key)
    if val is not None:
        os.environ[env_key] = str(val)
    elif env_key in os.environ and param_key == "disabled_signals":
        del os.environ[env_key]
```

The `elif` branch only cleared `disabled_signals`. If
`MEMORYHUB_TENANT_ID` was set by a prior `.env` load (e.g., `amb-benchmark`
from the harness's `.env` file), it persisted into the search call.
Memories in `amb-dreaming-tiny` have `tenant_id=default`, so filtering
by `amb-benchmark` returned zero results.

This was the cause of the 0% in the local adapter simulation (which
loaded the `.env` file) but NOT on the cluster (where no `.env` exists).
On the cluster, only the `return_chunks` bug applied.

## Diagnosis path

1. **Initial hypothesis (wrong):** Flash Lite answerer too weak for MCQ.
   Disproved when switching to Pro still scored 0% on EvalHub.

2. **Local test (misleading):** Running `uv run omb run` with
   `MEMORYHUB_PROJECT_ID=amb-dreaming-tiny` scored 90%. But the `.env`
   file has `override=True` and sets `MEMORYHUB_PROJECT_ID=amb-granite-pro`,
   so the local test was actually querying the library-mode project with
   full session transcripts, not the dreaming project with extracted facts.

3. **Honest local test:** Setting env vars in Python AFTER import (bypassing
   dotenv) against the actual `amb-dreaming-tiny` project scored 66.7%
   (2/3) -- confirming dreaming extraction works.

4. **Adapter simulation:** Simulating the adapter's env-var setup locally
   reproduced the 0% with `context len: 0 chars`.

5. **Isolation:** Running with and without `MEMORYHUB_RETURN_CHUNKS=true`
   while keeping everything else identical confirmed `return_chunks` as
   the cause: without it, 100% (2/2) with 1505-char context; with it,
   0% (0/3) with 0-char context.

## Fix

1. Removed `return_chunks: "true"` from all dreaming eval configs.
   This parameter is a diagnostic tool for inspecting chunk-level retrieval,
   not needed for benchmark scoring.

2. Changed the adapter's env-var clearing to remove ALL stale env vars
   when a config param is absent, not just `disabled_signals`.

3. Switched dreaming-smoke and dreaming-tiny answerer from Flash Lite
   to Pro (Flash Lite is appropriate for extraction but not for MCQ
   answering).

## Validation

- Local: 100% (2/2) with return_chunks removed
- EvalHub: 70% (7/10) with Pro answerer, job a995d14b

## Deeper issue (not yet fixed)

The SDK's `SearchResult.model_validate()` silently produces an empty
results list when the server returns chunked responses. This should
either be fixed in the SDK (parse chunked responses correctly) or the
search tool should reject `return_chunks` with `raw_results` as an
invalid combination. Filed as a watch-for; no issue yet since it doesn't
block benchmarks.
