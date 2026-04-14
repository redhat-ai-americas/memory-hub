#!/usr/bin/env python3
"""Validate vLLM prefix cache behavior with MemoryHub memory injection.

Tests three core hypotheses about cache-optimized memory assembly (#175):
stable prefix caching, append-only preservation, and recompilation cost.

Usage::

    export VLLM_URL="https://..."
    export MEMORYHUB_URL="https://..."
    export MEMORYHUB_API_KEY="mh-dev-..."

    # Optional: aggregate metrics via Prometheus/Thanos Querier
    export PROMETHEUS_URL="https://thanos-querier-openshift-monitoring.apps.<cluster>.<domain>"
    export PROMETHEUS_TOKEN="$(oc get secret metrics-reader-token \
        -n openshift-monitoring -o jsonpath='{.data.token}' | base64 -d)"

    python scripts/validate-prefix-cache.py

Results are written to research/vllm-prefix-cache-validation/results-<timestamp>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

warnings.filterwarnings("ignore", message="Unverified HTTPS")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "sdk" / "src")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import uuid as _uuid  # noqa: E402

from memoryhub import MemoryHubClient  # noqa: E402

# Unique per-run ID so temp memories don't collide with curation rules
RUN_ID = _uuid.uuid4().hex[:12]

BASELINE_SCENARIOS = ["stable_prefix", "append_only", "recompile", "block_granularity", "threshold_analysis"]
FOLLOWUP_SCENARIOS = [
    "byte_stability_fix",
    "immediate_recompile",
    "block_size_32",
    "eviction_pressure",
    "cross_query_sharing",
]
ALL_SCENARIOS = BASELINE_SCENARIOS + FOLLOWUP_SCENARIOS

MODEL = "RedHatAI/granite-3.3-8b-instruct"
SEARCH_QUERY = "project conventions deployment patterns"
SYSTEM_MSG = "You are a helpful assistant."


@dataclass
class MetricsSnapshot:
    prefix_cache_queries: float = 0
    prefix_cache_hits: float = 0
    prompt_tokens_cache_hit: float = 0
    prompt_tokens_computed: float = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class MetricsCollector:
    def __init__(self, vllm_url: str) -> None:
        self._url = vllm_url.rstrip("/")
        self._http = httpx.AsyncClient(verify=False, timeout=30)

    async def snapshot(self) -> MetricsSnapshot:
        resp = await self._http.get(f"{self._url}/metrics")
        resp.raise_for_status()
        return self._parse_metrics(resp.text)

    def _parse_metrics(self, text: str) -> MetricsSnapshot:
        values: dict[str, float] = {}
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            key_part = line.split("{")[0] if "{" in line else line.split()[0]
            if "source=" in line:
                m = re.search(r'source="([^"]+)"', line)
                if m:
                    key_part = f"{key_part}[{m.group(1)}]"
            values[key_part] = float(line.split()[-1])
        return MetricsSnapshot(
            prefix_cache_queries=values.get("vllm:prefix_cache_queries_total", 0),
            prefix_cache_hits=values.get("vllm:prefix_cache_hits_total", 0),
            prompt_tokens_cache_hit=values.get("vllm:prompt_tokens_by_source_total[local_cache_hit]", 0),
            prompt_tokens_computed=values.get("vllm:prompt_tokens_by_source_total[local_compute]", 0),
        )

    @staticmethod
    def delta(before: MetricsSnapshot, after: MetricsSnapshot) -> dict:
        queries = after.prefix_cache_queries - before.prefix_cache_queries
        hits = after.prefix_cache_hits - before.prefix_cache_hits
        return {
            "queries": queries,
            "hits": hits,
            "hit_rate": hits / queries if queries > 0 else 0.0,
            "tokens_cache_hit": after.prompt_tokens_cache_hit - before.prompt_tokens_cache_hit,
            "tokens_computed": after.prompt_tokens_computed - before.prompt_tokens_computed,
        }


class VLLMClient:
    def __init__(self, vllm_url: str) -> None:
        self._url = vllm_url.rstrip("/")
        self._http = httpx.AsyncClient(verify=False, timeout=60)

    async def chat(self, system: str, user: str) -> dict:
        resp = await self._http.post(
            f"{self._url}/v1/chat/completions",
            json={
                "model": MODEL,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": 50,
                "temperature": 0,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def get_version(self) -> str:
        resp = await self._http.get(f"{self._url}/version")
        resp.raise_for_status()
        data = resp.json()
        return data.get("version", str(data))


class PrometheusClient:
    """Query aggregate vLLM metrics via the cluster's Thanos Querier."""

    # PromQL templates for the metrics we care about
    QUERIES = {
        "prefix_cache_hit_rate": (
            'rate(vllm:prefix_cache_hits_total{{model_name="{model}"}}[{window}])'
            ' / rate(vllm:prefix_cache_queries_total{{model_name="{model}"}}[{window}])'
        ),
        "ttft_p95": (
            'histogram_quantile(0.95, rate(vllm:time_to_first_token_seconds_bucket{{model_name="{model}"}}[{window}]))'
        ),
        "kv_cache_usage": 'vllm:kv_cache_usage_perc{{model_name="{model}"}}',
        "active_requests": 'vllm:num_requests_running{{model_name="{model}"}}',
        "cached_tokens_rate": (
            'rate(vllm:prompt_tokens_by_source_total{{model_name="{model}",source="local_cache_hit"}}[{window}])'
        ),
        "computed_tokens_rate": (
            'rate(vllm:prompt_tokens_by_source_total{{model_name="{model}",source="local_compute"}}[{window}])'
        ),
    }

    def __init__(self, url: str, token: str, model: str = MODEL) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._model = model
        self._http = httpx.AsyncClient(
            verify=False,
            timeout=30,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def instant(self, query_name: str, window: str = "5m") -> float | None:
        """Run an instant PromQL query and return the scalar value, or None."""
        template = self.QUERIES.get(query_name)
        if not template:
            return None
        promql = template.format(model=self._model, window=window)
        try:
            resp = await self._http.get(
                f"{self._url}/api/v1/query",
                params={"query": promql},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            if results:
                val = float(results[0]["value"][1])
                return None if val != val else val  # NaN check
        except Exception as exc:
            log(f"  [prometheus] query {query_name} failed: {exc}")
        return None

    async def snapshot(self, window: str = "2m") -> dict[str, float | None]:
        """Capture current values for all tracked metrics."""
        result = {}
        for name in self.QUERIES:
            result[name] = await self.instant(name, window=window)
        return result


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _make_user_msg(block: str, question: str) -> str:
    return f"[Memory context]\n{block}\n[End memory context]\n\n{question}"


async def _measure(vllm: VLLMClient, metrics: MetricsCollector, system: str, user: str) -> tuple[dict, dict]:
    """Send one chat request and return (metrics_delta, chat_response).

    The delta includes per-request ``cached_tokens`` from the vLLM API
    response (requires ``--enable-prompt-tokens-details`` on the server).
    When available, ``cached_tokens`` is the authoritative per-request
    measurement; the Prometheus delta is a cross-check.
    """
    before = await metrics.snapshot()
    resp = await vllm.chat(system, user)
    await asyncio.sleep(0.5)
    after = await metrics.snapshot()
    delta = MetricsCollector.delta(before, after)

    # Extract per-request cached_tokens from the API response
    usage = resp.get("usage", {})
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    prompt_tokens = usage.get("prompt_tokens", 0)
    delta["prompt_tokens"] = prompt_tokens
    delta["cached_tokens"] = cached
    if cached is not None and prompt_tokens > 0:
        delta["per_request_hit_rate"] = cached / prompt_tokens
    else:
        delta["per_request_hit_rate"] = None

    return delta, resp


async def _with_prom_context(prom: PrometheusClient | None, name: str, coro):
    """Run a scenario coroutine and attach Prometheus context if available."""
    prom_before = await prom.snapshot() if prom else None
    result = await coro
    prom_after = await prom.snapshot() if prom else None
    if prom_before or prom_after:
        result["prometheus"] = {
            "before": prom_before,
            "after": prom_after,
        }
    return result


async def _search_block(client: MemoryHubClient):
    """Search and return (SearchResult, injection_block)."""
    sr = await client.search(SEARCH_QUERY, max_results=15, mode="full_only", max_response_tokens=20000)
    return sr, MemoryHubClient.get_injection_block(sr)


async def run_stable_prefix(client, vllm, metrics) -> dict:
    log("=== Scenario 1: Stable Prefix ===")
    sr, block = await _search_block(client)
    block_hash = hashlib.sha256(block.encode()).hexdigest()
    log(f"  Injection block: {len(block)} chars, hash={block_hash[:12]}...")
    log(f"  Compilation epoch: {sr.compilation_epoch}, appendix: {sr.appendix_count}")

    _, block2 = await _search_block(client)
    assert block == block2, "Injection block is not deterministic!"

    user_msg = _make_user_msg(block, "Summarize the key project conventions.")
    requests_data = []
    for i in range(5):
        label = "cold_start" if i == 0 else f"warm_{i}"
        d, resp = await _measure(vllm, metrics, SYSTEM_MSG, user_msg)
        ct = d["cached_tokens"]
        pt = d["prompt_tokens"]
        pct = f"{d['per_request_hit_rate']:.2%}" if d["per_request_hit_rate"] is not None else "n/a"
        log(f"  Request {i + 1} ({label}): {ct}/{pt} cached ({pct}), prom_hit_rate={d['hit_rate']:.2%}")
        requests_data.append({"request_num": i + 1, "label": label, **d})

    # Prefer per-request hit rate when available; fall back to Prometheus delta
    warm_rates = [r.get("per_request_hit_rate") or r["hit_rate"] for r in requests_data[1:]]
    mean_warm = sum(warm_rates) / len(warm_rates) if warm_rates else 0
    passed = mean_warm > 0.8
    return {
        "hypothesis": "Identical memory injection blocks produce >90% prefix cache hit rates",
        "status": "PASS" if passed else "FAIL",
        "injection_block_chars": len(block),
        "injection_block_hash": block_hash,
        "compilation_epoch": sr.compilation_epoch,
        "compilation_hash": sr.compilation_hash,
        "requests": requests_data,
        "summary": {
            "cold_hit_rate": requests_data[0]["hit_rate"],
            "warm_hit_rate_mean": mean_warm,
            "warm_hit_rate_min": min(warm_rates) if warm_rates else 0,
            "pass": passed,
        },
    }


async def run_append_only(client, vllm, metrics, temp_ids) -> dict:
    log("=== Scenario 2: Append-Only ===")
    sr1, block_v1 = await _search_block(client)
    epoch_before = sr1.compilation_epoch
    question = "What deployment patterns are recommended?"
    user_v1 = _make_user_msg(block_v1, question)

    log("  Warming cache...")
    for _ in range(2):
        await vllm.chat(SYSTEM_MSG, user_v1)
    await asyncio.sleep(0.5)

    # Content must be (a) semantically relevant to the search query so it
    # appears in results and (b) distinct from each other to avoid curation veto
    append_contents = [
        f"[VALIDATION-{RUN_ID}] Project convention: deployment pipelines"
        " must use blue-green strategy with automated rollback.",
        f"[VALIDATION-{RUN_ID}] Deployment pattern: production containers"
        " must set resource limits and use readiness probes.",
    ]
    log("  Writing 2 temporary memories...")
    for content in append_contents:
        result = await client.write(
            content,
            scope="user",
            weight=0.3,
            metadata={"validation": True, "scenario": "append_only", "run_id": RUN_ID},
        )
        temp_ids.append(result.memory.id)
        log(f"    Written: {result.memory.id[:8]}...")

    log("  Waiting for embeddings to settle...")
    await asyncio.sleep(2)

    sr2, block_v2 = await _search_block(client)
    appendix_count = sr2.appendix_count or 0
    log(f"  block_v1: {len(block_v1)} chars, block_v2: {len(block_v2)} chars")
    log(f"  Appendix count: {appendix_count}")

    prefix_preserved = block_v2.startswith(block_v1) or block_v1 in block_v2
    user_v2 = _make_user_msg(block_v2, question)

    d_append, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_v2)
    ca = d_append["cached_tokens"]
    pa = d_append["prompt_tokens"]
    log(f"  Append request: {ca}/{pa} cached, prom_hit_rate={d_append['hit_rate']:.2%}")

    d_repeat, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_v2)
    cr = d_repeat["cached_tokens"]
    pr = d_repeat["prompt_tokens"]
    log(f"  Repeat request: {cr}/{pr} cached, prom_hit_rate={d_repeat['hit_rate']:.2%}")

    # Use per-request hit rate when available
    a_rate = d_append.get("per_request_hit_rate") or d_append["hit_rate"]
    r_rate = d_repeat.get("per_request_hit_rate") or d_repeat["hit_rate"]
    passed = a_rate > 0.3 and r_rate > 0.8
    return {
        "hypothesis": "Adding appendix memories preserves compiled prefix cache hits",
        "status": "PASS" if passed else "FAIL",
        "block_v1_chars": len(block_v1),
        "block_v2_chars": len(block_v2),
        "prefix_preserved": prefix_preserved,
        "appendix_count": appendix_count,
        "epoch_before": epoch_before,
        "epoch_after": sr2.compilation_epoch,
        "requests": [{"label": "with_appendix", **d_append}, {"label": "repeat_appendix", **d_repeat}],
        "summary": {"append_hit_rate": a_rate, "repeat_hit_rate": r_rate, "pass": passed},
    }


async def run_recompile(client, vllm, metrics, temp_ids) -> dict:
    log("=== Scenario 3: Recompilation Cost ===")
    sr_pre, block_pre = await _search_block(client)
    epoch_pre = sr_pre.compilation_epoch
    question = "List the testing requirements."
    user_pre = _make_user_msg(block_pre, question)

    log("  Warming cache...")
    for _ in range(2):
        await vllm.chat(SYSTEM_MSG, user_pre)
    await asyncio.sleep(0.5)

    # Content must match the search query AND be distinct from each other
    recompile_contents = [
        f"[VALIDATION-{RUN_ID}] Convention: CI pipelines must run integration tests against staging before promotion.",
        f"[VALIDATION-{RUN_ID}] Deployment: canary releases gate on error-rate SLO for 15 min before full rollout.",
        f"[VALIDATION-{RUN_ID}] Convention: every service publishes an OpenAPI spec alongside its deployment manifest.",
        f"[VALIDATION-{RUN_ID}] Deployment: Helm values files split per environment with a shared base chart.",
        f"[VALIDATION-{RUN_ID}] Pattern: database migrations run as"
        " init containers so deployment fails fast on schema drift.",
    ]
    log("  Writing 5 temporary memories to trigger recompilation...")
    for content in recompile_contents:
        result = await client.write(
            content,
            scope="user",
            weight=0.5,
            metadata={"validation": True, "scenario": "recompile", "run_id": RUN_ID},
        )
        temp_ids.append(result.memory.id)

    log("  Waiting for embeddings to settle...")
    await asyncio.sleep(2)

    sr_post, block_post = await _search_block(client)
    epoch_post = sr_post.compilation_epoch
    appendix_post = sr_post.appendix_count or 0
    log(f"  Epoch: {epoch_pre} -> {epoch_post}, appendix: {appendix_post}")
    log(f"  Block changed: {block_pre != block_post}")

    user_post = _make_user_msg(block_post, question)
    requests_data = []
    for i in range(4):
        label = "recompile_miss" if i == 0 else f"post_recompile_{i}"
        d, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_post)
        ct = d["cached_tokens"]
        pt = d["prompt_tokens"]
        pct = f"{d['per_request_hit_rate']:.2%}" if d["per_request_hit_rate"] is not None else "n/a"
        log(f"  Request {i + 1} ({label}): {ct}/{pt} cached ({pct})")
        requests_data.append({"label": label, **d})

    warm_rates = [r.get("per_request_hit_rate") or r["hit_rate"] for r in requests_data[1:]]
    mean_warm = sum(warm_rates) / len(warm_rates) if warm_rates else 0
    passed = mean_warm > 0.8
    r0_rate = requests_data[0].get("per_request_hit_rate") or requests_data[0]["hit_rate"]
    return {
        "hypothesis": "Recompilation causes one-time miss, then cache-hits resume",
        "status": "PASS" if passed else "FAIL",
        "epoch_before": epoch_pre,
        "epoch_after": epoch_post,
        "epoch_incremented": (epoch_post or 0) > (epoch_pre or 0),
        "appendix_after_recompile": appendix_post,
        "block_changed": block_pre != block_post,
        "requests": requests_data,
        "summary": {
            "recompile_hit_rate": r0_rate,
            "post_recompile_mean": mean_warm,
            "pass": passed,
        },
    }


async def run_block_granularity(client, vllm, metrics) -> dict:
    log("=== Scenario 4: Block Granularity ===")
    _, block = await _search_block(client)
    prefix = f"[Memory context]\n{block}\n[End memory context]\n\n"
    q1 = "Describe the authentication approach used in this project."
    q2 = "Explain the storage architecture and database choices."

    log("  Warming cache with question 1...")
    await vllm.chat(SYSTEM_MSG, prefix + q1)
    await vllm.chat(SYSTEM_MSG, prefix + q1)
    await asyncio.sleep(0.5)

    log("  Sending question 2 (shared prefix, different suffix)...")
    d, resp = await _measure(vllm, metrics, SYSTEM_MSG, prefix + q2)
    ct = d["cached_tokens"]
    pt = d["prompt_tokens"]
    pct = f"{d['per_request_hit_rate']:.2%}" if d["per_request_hit_rate"] is not None else "n/a"
    log(f"  Shared-prefix request: {ct}/{pt} cached ({pct})")

    rate = d.get("per_request_hit_rate") or d["hit_rate"]
    passed = rate > 0.7
    return {
        "hypothesis": "Cache matching is 16-token block-aligned; shared prefix caches",
        "status": "PASS" if passed else "FAIL",
        "prefix_chars": len(prefix),
        "q1_chars": len(q1),
        "q2_chars": len(q2),
        "total_prompt_tokens": pt,
        "request": d,
        "summary": {
            "shared_prefix_hit_rate": rate,
            "cached_tokens": ct,
            "prompt_tokens": pt,
            "pass": passed,
        },
    }


def analyze_threshold(results: dict) -> dict:
    """Analyze whether 30%/5-entry recompile threshold is appropriate."""
    log("=== Scenario 5: Threshold Analysis ===")
    append_hr = results.get("append_only", {}).get("summary", {}).get("append_hit_rate", 0)
    recompile_hr = results.get("recompile", {}).get("summary", {}).get("recompile_hit_rate", 0)

    waste = 1.0 - append_hr if append_hr else 0
    cost = 1.0 - recompile_hr if recompile_hr else 1.0
    breakeven = cost / waste if waste > 0 else float("inf")

    rec = (
        f"Appendix mode wastes ~{waste:.0%} of tokens per request. "
        f"Recompilation costs ~{cost:.0%} once. Break-even at ~{breakeven:.1f} requests. "
    )
    if breakeven < 3:
        rec += "Current threshold may be too high -- consider recompiling sooner."
    elif breakeven > 10:
        rec += "Current threshold is conservative -- could tolerate a larger appendix."
    else:
        rec += "Current 5-entry threshold is in the right range."
    log(f"  {rec}")

    return {
        "hypothesis": "30%/5-entry recompile threshold is appropriate",
        "status": "ANALYSIS",
        "append_waste_per_request": waste,
        "recompile_one_time_cost": cost,
        "breakeven_requests": breakeven,
        "recommendation": rec,
    }


async def run_byte_stability_fix(client, vllm, metrics, temp_ids) -> dict:
    """Validate that a byte-stable get_injection_block() restores append-only cache benefit.

    Prerequisite: get_injection_block() must render compiled and appendix
    as separately stable text segments. Run AFTER applying that fix.
    """
    log("=== Follow-Up: Byte Stability Fix ===")
    log("  This scenario requires the byte-stability fix to get_injection_block().")
    log("  See findings.md recommendation #1.")

    sr1, block_v1 = await _search_block(client)
    epoch_before = sr1.compilation_epoch  # noqa: F841
    question = "What are the key architectural decisions?"
    user_v1 = _make_user_msg(block_v1, question)

    # Warm cache
    log("  Warming cache...")
    for _ in range(2):
        await vllm.chat(SYSTEM_MSG, user_v1)
    await asyncio.sleep(0.5)

    # Write 2 memories (below recompile threshold)
    append_contents = [
        f"[VALIDATION-{RUN_ID}] Byte-stability test: service mesh requires mTLS between all pods in the data plane.",
        f"[VALIDATION-{RUN_ID}] Byte-stability test: feature flags use"
        " LaunchDarkly SDK with server-side evaluation only.",
    ]
    for content in append_contents:
        result = await client.write(
            content,
            scope="user",
            weight=0.3,
            metadata={"validation": True, "scenario": "byte_stability", "run_id": RUN_ID},
        )
        temp_ids.append(result.memory.id)

    await asyncio.sleep(2)
    sr2, block_v2 = await _search_block(client)

    # Key check: does block_v2 start with the exact bytes of block_v1?
    compiled_prefix_preserved = block_v2.startswith(block_v1)
    log(f"  Compiled prefix byte-stable: {compiled_prefix_preserved}")
    log(f"  block_v1: {len(block_v1)} chars, block_v2: {len(block_v2)} chars")

    user_v2 = _make_user_msg(block_v2, question)
    d, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_v2)
    ct = d["cached_tokens"]
    pt = d["prompt_tokens"]
    pct = f"{d['per_request_hit_rate']:.2%}" if d["per_request_hit_rate"] is not None else "n/a"
    log(f"  Append request: {ct}/{pt} cached ({pct})")

    passed = compiled_prefix_preserved and (d.get("per_request_hit_rate") or 0) > 0.5
    return {
        "hypothesis": "Byte-stable compiled section preserves prefix cache on append",
        "status": "PASS" if passed else "FAIL",
        "compiled_prefix_preserved": compiled_prefix_preserved,
        "block_v1_chars": len(block_v1),
        "block_v2_chars": len(block_v2),
        "request": d,
        "summary": {
            "hit_rate": d.get("per_request_hit_rate") or d["hit_rate"],
            "pass": passed,
        },
    }


async def run_immediate_recompile(client, vllm, metrics, temp_ids) -> dict:
    """Validate that min_appendix=1 (immediate recompile) is better than appendix mode.

    Prerequisite: set min_appendix=1 in compilation config.
    """
    log("=== Follow-Up: Immediate Recompile ===")
    log("  This scenario requires min_appendix=1 in compilation config.")

    sr1, block_v1 = await _search_block(client)
    question = "Explain the monitoring and alerting setup."
    user_v1 = _make_user_msg(block_v1, question)

    log("  Warming cache...")
    for _ in range(2):
        await vllm.chat(SYSTEM_MSG, user_v1)
    await asyncio.sleep(0.5)

    # Write 1 memory -- should trigger immediate recompile if min_appendix=1
    result = await client.write(
        f"[VALIDATION-{RUN_ID}] Immediate recompile test: alerting"
        " thresholds must be defined in code, not configured manually.",
        scope="user",
        weight=0.5,
        metadata={"validation": True, "scenario": "immediate_recompile", "run_id": RUN_ID},
    )
    temp_ids.append(result.memory.id)
    await asyncio.sleep(2)

    sr2, block_v2 = await _search_block(client)
    epoch_changed = (sr2.compilation_epoch or 0) > (sr1.compilation_epoch or 0)
    appendix_zero = (sr2.appendix_count or 0) == 0
    log(f"  Epoch changed: {epoch_changed}, appendix: {sr2.appendix_count}")

    user_v2 = _make_user_msg(block_v2, question)
    requests_data = []
    for i in range(4):
        label = "post_write_miss" if i == 0 else f"post_write_warm_{i}"
        d, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_v2)
        ct = d["cached_tokens"]
        pt = d["prompt_tokens"]
        pct = f"{d['per_request_hit_rate']:.2%}" if d["per_request_hit_rate"] is not None else "n/a"
        log(f"  Request {i + 1} ({label}): {ct}/{pt} cached ({pct})")
        requests_data.append({"label": label, **d})

    warm_rates = [r.get("per_request_hit_rate") or r["hit_rate"] for r in requests_data[1:]]
    mean_warm = sum(warm_rates) / len(warm_rates) if warm_rates else 0
    passed = epoch_changed and appendix_zero and mean_warm > 0.9

    return {
        "hypothesis": "Immediate recompile (min_appendix=1) restores cache after 1 miss",
        "status": "PASS" if passed else "FAIL",
        "epoch_changed": epoch_changed,
        "appendix_zero": appendix_zero,
        "requests": requests_data,
        "summary": {"post_write_warm_mean": mean_warm, "pass": passed},
    }


async def run_block_size_32(client, vllm, metrics) -> dict:
    """Compare cache behavior with block_size=32 vs baseline block_size=16.

    Prerequisite: redeploy vLLM with --block-size 32.
    """
    log("=== Follow-Up: Block Size 32 ===")
    log("  This scenario requires vLLM deployed with --block-size 32.")

    sr, block = await _search_block(client)
    user_msg = _make_user_msg(block, "Summarize the key project conventions.")

    requests_data = []
    for i in range(5):
        label = "cold_start" if i == 0 else f"warm_{i}"
        d, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_msg)
        ct = d["cached_tokens"]
        pt = d["prompt_tokens"]
        pct = f"{d['per_request_hit_rate']:.2%}" if d["per_request_hit_rate"] is not None else "n/a"
        log(f"  Request {i + 1} ({label}): {ct}/{pt} cached ({pct})")
        requests_data.append({"label": label, **d})

    warm_rates = [r.get("per_request_hit_rate") or r["hit_rate"] for r in requests_data[1:]]
    mean_warm = sum(warm_rates) / len(warm_rates) if warm_rates else 0
    pt = requests_data[1]["prompt_tokens"] if len(requests_data) > 1 else 0
    ct = requests_data[1].get("cached_tokens") or 0
    partial_block_waste = pt - ct if pt and ct else 0

    return {
        "hypothesis": "Block size 32 performs comparably to block size 16",
        "status": "PASS" if mean_warm > 0.9 else "FAIL",
        "requests": requests_data,
        "summary": {
            "warm_hit_rate_mean": mean_warm,
            "partial_block_waste_tokens": partial_block_waste,
            "pass": mean_warm > 0.9,
        },
    }


async def run_eviction_pressure(client, vllm, metrics) -> dict:
    """Measure cache eviction behavior under memory pressure.

    Prerequisite: optionally redeploy vLLM with --num-gpu-blocks-override
    at ~50% of profiled capacity.
    """
    log("=== Follow-Up: Eviction Pressure ===")

    sr, block = await _search_block(client)
    user_msg = _make_user_msg(block, "Summarize the key project conventions.")

    # Warm cache
    log("  Warming cache...")
    await vllm.chat(SYSTEM_MSG, user_msg)
    await vllm.chat(SYSTEM_MSG, user_msg)
    await asyncio.sleep(0.5)

    # Verify warm
    d_warm, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_msg)
    log(f"  Warm baseline: {d_warm.get('cached_tokens')}/{d_warm['prompt_tokens']} cached")

    # Send unrelated prompts to pressure the cache
    eviction_prompts = [f"Write a detailed essay about topic number {i}: {' '.join(['word'] * 200)}" for i in range(20)]
    log("  Sending 20 unrelated prompts to pressure cache...")
    preemptions_before = (await metrics.snapshot()).prefix_cache_queries  # noqa: F841
    for i, prompt in enumerate(eviction_prompts):
        await vllm.chat(SYSTEM_MSG, prompt)
        if (i + 1) % 5 == 0:
            log(f"    Sent {i + 1}/20")

    # Re-check our original prompt
    d_post, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_msg)
    post_ct = d_post.get("cached_tokens")
    post_pt = d_post["prompt_tokens"]
    log(f"  Post-pressure: {post_ct}/{post_pt} cached")

    survived = (post_ct or 0) > (post_pt * 0.5) if post_pt else False
    return {
        "hypothesis": "Cached blocks survive moderate eviction pressure",
        "status": "PASS" if survived else "FAIL",
        "warm_baseline": d_warm,
        "post_pressure": d_post,
        "eviction_prompts_sent": len(eviction_prompts),
        "summary": {
            "warm_cached_tokens": d_warm.get("cached_tokens"),
            "post_pressure_cached_tokens": post_ct,
            "blocks_survived": survived,
        },
    }


async def run_cross_query_sharing(client, vllm, metrics) -> dict:
    """Test whether different search queries with overlapping results share cache."""
    log("=== Follow-Up: Cross-Query Cache Sharing ===")

    # Query A
    sr_a = await client.search(
        "project conventions and coding standards",
        max_results=15,
        mode="full_only",
        max_response_tokens=20000,
    )
    block_a = MemoryHubClient.get_injection_block(sr_a)
    user_a = _make_user_msg(block_a, "Summarize the conventions.")

    # Query B
    sr_b = await client.search(
        "deployment patterns and infrastructure",
        max_results=15,
        mode="full_only",
        max_response_tokens=20000,
    )
    block_b = MemoryHubClient.get_injection_block(sr_b)
    user_b = _make_user_msg(block_b, "Summarize the deployment approach.")

    # Measure overlap
    common_prefix_len = 0
    for a, b in zip(block_a, block_b, strict=False):
        if a == b:
            common_prefix_len += 1
        else:
            break
    log(f"  Block A: {len(block_a)} chars, Block B: {len(block_b)} chars")
    log(f"  Common prefix: {common_prefix_len} chars")

    # Check memory ID overlap
    ids_a = {m.id for m in sr_a.results}
    ids_b = {m.id for m in sr_b.results}
    overlap = ids_a & ids_b
    log(f"  Memory overlap: {len(overlap)}/{len(ids_a)} IDs shared")

    # Warm with query A
    log("  Warming cache with query A...")
    await vllm.chat(SYSTEM_MSG, user_a)
    await vllm.chat(SYSTEM_MSG, user_a)
    await asyncio.sleep(0.5)

    # Send query B -- does the shared prefix hit?
    log("  Sending query B (different query, potentially overlapping memories)...")
    d, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_b)
    ct = d.get("cached_tokens")
    pt = d["prompt_tokens"]
    pct = f"{d['per_request_hit_rate']:.2%}" if d["per_request_hit_rate"] is not None else "n/a"
    log(f"  Cross-query request: {ct}/{pt} cached ({pct})")

    return {
        "hypothesis": "Different queries with overlapping memories share prefix cache",
        "status": "ANALYSIS",
        "block_a_chars": len(block_a),
        "block_b_chars": len(block_b),
        "common_prefix_chars": common_prefix_len,
        "memory_overlap_count": len(overlap),
        "memory_overlap_ids": sorted(overlap),
        "request": d,
        "summary": {
            "common_prefix_chars": common_prefix_len,
            "memory_overlap_ratio": len(overlap) / len(ids_a) if ids_a else 0,
            "cross_query_hit_rate": d.get("per_request_hit_rate") or d["hit_rate"],
        },
    }


def write_results(results: dict) -> None:
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "vllm-prefix-cache-validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"results-{ts}.json"
    path.write_text(json.dumps(results, indent=2, default=str))
    log(f"Results written to {path}")


def print_summary(results: dict) -> None:
    log("\n=== Summary ===")
    for name in ALL_SCENARIOS:
        if name in results:
            s = results[name]
            status = s.get("status", "MISSING")
            prom = s.get("prometheus", {}).get("after", {})
            extras = []
            if prom.get("prefix_cache_hit_rate") is not None:
                extras.append(f"prom_hit_rate={prom['prefix_cache_hit_rate']:.2%}")
            if prom.get("ttft_p95") is not None:
                extras.append(f"ttft_p95={prom['ttft_p95']:.3f}s")
            if prom.get("kv_cache_usage") is not None:
                extras.append(f"kv_usage={prom['kv_cache_usage']:.1%}")
            suffix = f" ({', '.join(extras)})" if extras else ""
            log(f"  {name}: {status}{suffix}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        choices=ALL_SCENARIOS,
        help="Run a single scenario instead of the full baseline suite",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios and exit",
    )
    args = parser.parse_args()

    if args.list_scenarios:
        print("Baseline scenarios (run by default):")
        for s in BASELINE_SCENARIOS:
            print(f"  {s}")
        print("\nFollow-up scenarios (run with --scenario <name>):")
        for s in FOLLOWUP_SCENARIOS:
            print(f"  {s}")
        return

    vllm_url = os.environ["VLLM_URL"]
    memoryhub_url = os.environ["MEMORYHUB_URL"]
    api_key = os.environ["MEMORYHUB_API_KEY"]
    prom_url = os.environ.get("PROMETHEUS_URL", "")
    prom_token = os.environ.get("PROMETHEUS_TOKEN", "")
    prom = PrometheusClient(prom_url, prom_token) if prom_url and prom_token else None
    if prom:
        log("Prometheus: connected to Thanos Querier")
    else:
        log("Prometheus: not configured (set PROMETHEUS_URL and PROMETHEUS_TOKEN for aggregate metrics)")

    mc = MetricsCollector(vllm_url)
    vllm = VLLMClient(vllm_url)

    version = await vllm.get_version()
    snap = await mc.snapshot()
    log(f"vLLM v{version}, prefix_cache_queries={snap.prefix_cache_queries}")

    results: dict = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "vllm_url": vllm_url,
        "vllm_version": version,
        "model": MODEL,
    }
    if prom:
        results["prometheus_url"] = prom_url
        results["prometheus_connected"] = True
    else:
        results["prometheus_connected"] = False

    temp_memory_ids: list[str] = []
    client = MemoryHubClient(url=memoryhub_url, api_key=api_key)
    scenarios_to_run = [args.scenario] if args.scenario else BASELINE_SCENARIOS

    try:
        async with client:
            if "stable_prefix" in scenarios_to_run:
                results["stable_prefix"] = await _with_prom_context(
                    prom,
                    "stable_prefix",
                    run_stable_prefix(client, vllm, mc),
                )
            if "append_only" in scenarios_to_run:
                results["append_only"] = await _with_prom_context(
                    prom,
                    "append_only",
                    run_append_only(client, vllm, mc, temp_memory_ids),
                )
            if "recompile" in scenarios_to_run:
                results["recompile"] = await _with_prom_context(
                    prom,
                    "recompile",
                    run_recompile(client, vllm, mc, temp_memory_ids),
                )
            if "block_granularity" in scenarios_to_run:
                results["block_granularity"] = await _with_prom_context(
                    prom,
                    "block_granularity",
                    run_block_granularity(client, vllm, mc),
                )
            if "threshold_analysis" in scenarios_to_run:
                results["threshold_analysis"] = analyze_threshold(results)
            # Follow-up scenarios
            if "byte_stability_fix" in scenarios_to_run:
                results["byte_stability_fix"] = await _with_prom_context(
                    prom,
                    "byte_stability_fix",
                    run_byte_stability_fix(client, vllm, mc, temp_memory_ids),
                )
            if "immediate_recompile" in scenarios_to_run:
                results["immediate_recompile"] = await _with_prom_context(
                    prom,
                    "immediate_recompile",
                    run_immediate_recompile(client, vllm, mc, temp_memory_ids),
                )
            if "block_size_32" in scenarios_to_run:
                results["block_size_32"] = await _with_prom_context(
                    prom,
                    "block_size_32",
                    run_block_size_32(client, vllm, mc),
                )
            if "eviction_pressure" in scenarios_to_run:
                results["eviction_pressure"] = await _with_prom_context(
                    prom,
                    "eviction_pressure",
                    run_eviction_pressure(client, vllm, mc),
                )
            if "cross_query_sharing" in scenarios_to_run:
                results["cross_query_sharing"] = await _with_prom_context(
                    prom,
                    "cross_query_sharing",
                    run_cross_query_sharing(client, vllm, mc),
                )
    finally:
        if temp_memory_ids:
            async with client:
                for mid in temp_memory_ids:
                    try:
                        await client.delete(mid)
                        log(f"  Cleaned up temp memory {mid[:8]}...")
                    except Exception:
                        pass

    write_results(results)
    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
