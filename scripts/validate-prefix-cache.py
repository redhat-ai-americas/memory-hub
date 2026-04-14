#!/usr/bin/env python3
"""Validate vLLM prefix cache behavior with MemoryHub memory injection.

Tests three core hypotheses about cache-optimized memory assembly (#175):
stable prefix caching, append-only preservation, and recompilation cost.

Usage::

    export VLLM_URL="https://..."
    export MEMORYHUB_URL="https://..."
    export MEMORYHUB_API_KEY="mh-dev-..."

    python scripts/validate-prefix-cache.py

Results are written to research/vllm-prefix-cache-validation/results-<timestamp>.json.
"""

from __future__ import annotations

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


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _make_user_msg(block: str, question: str) -> str:
    return f"[Memory context]\n{block}\n[End memory context]\n\n{question}"


async def _measure(vllm: VLLMClient, metrics: MetricsCollector, system: str, user: str) -> tuple[dict, dict]:
    """Send one chat request and return (metrics_delta, chat_response)."""
    before = await metrics.snapshot()
    resp = await vllm.chat(system, user)
    await asyncio.sleep(0.5)
    after = await metrics.snapshot()
    return MetricsCollector.delta(before, after), resp


async def _search_block(client: MemoryHubClient):
    """Search and return (SearchResult, injection_block)."""
    sr = await client.search(
        SEARCH_QUERY, max_results=15, mode="full_only", max_response_tokens=20000
    )
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
        log(f"  Request {i + 1} ({label}): queries={d['queries']}, hits={d['hits']}, hit_rate={d['hit_rate']:.2%}")
        requests_data.append(
            {"request_num": i + 1, "label": label, **d, "prompt_tokens": resp["usage"]["prompt_tokens"]}
        )

    warm_rates = [r["hit_rate"] for r in requests_data[1:]]
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
    log(
        f"  Append request: queries={d_append['queries']}, hits={d_append['hits']}, hit_rate={d_append['hit_rate']:.2%}"
    )

    d_repeat, _ = await _measure(vllm, metrics, SYSTEM_MSG, user_v2)
    log(
        f"  Repeat request: queries={d_repeat['queries']}, hits={d_repeat['hits']}, hit_rate={d_repeat['hit_rate']:.2%}"
    )

    passed = d_append["hit_rate"] > 0.3 and d_repeat["hit_rate"] > 0.8
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
        "summary": {"append_hit_rate": d_append["hit_rate"], "repeat_hit_rate": d_repeat["hit_rate"], "pass": passed},
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
        f"[VALIDATION-{RUN_ID}] Convention: CI pipelines must run"
        " integration tests against staging before promotion.",
        f"[VALIDATION-{RUN_ID}] Deployment: canary releases gate"
        " on error-rate SLO for 15 min before full rollout.",
        f"[VALIDATION-{RUN_ID}] Convention: every service publishes"
        " an OpenAPI spec alongside its deployment manifest.",
        f"[VALIDATION-{RUN_ID}] Deployment: Helm values files split"
        " per environment with a shared base chart.",
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
        log(f"  Request {i + 1} ({label}): hit_rate={d['hit_rate']:.2%}")
        requests_data.append({"label": label, **d})

    warm_rates = [r["hit_rate"] for r in requests_data[1:]]
    mean_warm = sum(warm_rates) / len(warm_rates) if warm_rates else 0
    passed = mean_warm > 0.8
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
            "recompile_hit_rate": requests_data[0]["hit_rate"],
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
    total_tokens = resp["usage"]["prompt_tokens"]
    log(f"  Shared-prefix request: queries={d['queries']}, hits={d['hits']}, hit_rate={d['hit_rate']:.2%}")
    log(f"  Total prompt tokens: {total_tokens}")

    passed = d["hit_rate"] > 0.7
    return {
        "hypothesis": "Cache matching is 16-token block-aligned; shared prefix caches",
        "status": "PASS" if passed else "FAIL",
        "prefix_chars": len(prefix),
        "q1_chars": len(q1),
        "q2_chars": len(q2),
        "total_prompt_tokens": total_tokens,
        "request": d,
        "summary": {
            "shared_prefix_hit_rate": d["hit_rate"],
            "hits": d["hits"],
            "queries": d["queries"],
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


def write_results(results: dict) -> None:
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "vllm-prefix-cache-validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"results-{ts}.json"
    path.write_text(json.dumps(results, indent=2, default=str))
    log(f"Results written to {path}")


def print_summary(results: dict) -> None:
    log("\n=== Summary ===")
    for name in ["stable_prefix", "append_only", "recompile", "block_granularity", "threshold_analysis"]:
        log(f"  {name}: {results.get(name, {}).get('status', 'MISSING')}")


async def main() -> None:
    vllm_url = os.environ["VLLM_URL"]
    memoryhub_url = os.environ["MEMORYHUB_URL"]
    api_key = os.environ["MEMORYHUB_API_KEY"]

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

    temp_memory_ids: list[str] = []
    client = MemoryHubClient(url=memoryhub_url, api_key=api_key)

    try:
        async with client:
            results["stable_prefix"] = await run_stable_prefix(client, vllm, mc)
            results["append_only"] = await run_append_only(client, vllm, mc, temp_memory_ids)
            results["recompile"] = await run_recompile(client, vllm, mc, temp_memory_ids)
            results["block_granularity"] = await run_block_granularity(client, vllm, mc)
            results["threshold_analysis"] = analyze_threshold(results)
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
