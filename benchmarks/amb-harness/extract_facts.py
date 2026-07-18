#!/usr/bin/env python3
"""Extract discrete facts from PersonaMem documents and ingest into MemoryHub.

Supports Gemini (default) and Ollama backends. Set EXTRACTION_BACKEND=ollama
and OLLAMA_MODEL to use a local model.

Usage:
    source ~/.secrets
    MEMORYHUB_API_KEY=$(cat ~/.config/memoryhub/api-key) \
    MEMORYHUB_DB_PASS=$(oc get secret memoryhub-pg-credentials \
        --context mcp-rhoai -n memoryhub-db -o jsonpath='{.data.password}' | base64 -d) \
    uv run python extract_facts.py [--doc-limit N] [--dry-run]

    # Ollama example:
    EXTRACTION_BACKEND=ollama OLLAMA_MODEL=deepseek-r1:32b-qwen-distill-q4_K_M \
    uv run python extract_facts.py --sample 2
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)

from memoryhub import MemoryHubClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).parent / "src"))
from memory_bench.dataset import get_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("MEMORYHUB_FACTS_PROJECT", "amb-facts-lite")
TENANT_ID = os.environ.get("MEMORYHUB_TENANT_ID", "amb-benchmark")
BACKEND = os.environ.get("EXTRACTION_BACKEND", "gemini")
GEMINI_MODEL = os.environ.get("EXTRACTION_MODEL", "gemini-3.1-flash-lite")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "deepseek-r1:32b-qwen-distill-q4_K_M")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

EXTRACTION_PROMPT = """\
You are a memory extraction agent. Given a document recording conversations \
with a person, extract every discrete fact as a separate statement. Each fact \
should be a single, self-contained sentence that could be understood without \
the rest of the document.

Include: preferences, opinions, experiences, biographical details, \
relationships, habits, goals, likes/dislikes, stated intentions, and \
changes in preference over time.

Do NOT include: inferences not explicitly stated, generalizations, \
or meta-commentary about the conversation format.

Return ONLY a JSON array of strings, one fact per entry. No explanation, \
no markdown, no commentary -- just the JSON array. Be thorough -- \
capture every fact, even minor ones.

Document:
{content}"""

_MAX_RETRIES = 4
_RETRY_BASE = 5
_JSON_INSIST_MAX = 3

JSON_INSIST_MESSAGE = (
    "That response was not valid JSON. I need ONLY a JSON array of strings, "
    "nothing else. No markdown fences, no explanation, no thinking tags. "
    "Just: [\"fact one\", \"fact two\", ...]"
)


def _try_parse_json_array(text: str) -> list[str] | None:
    """Try to extract a JSON array from text that might have extra content."""
    text = text.strip()

    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    # Strip deepseek-r1 <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [f.strip() for f in result if isinstance(f, str) and f.strip()]
    except json.JSONDecodeError:
        pass

    # Try to find a JSON array in the text
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [f.strip() for f in result if isinstance(f, str) and f.strip()]
        except json.JSONDecodeError:
            pass

    return None


def _extract_gemini(content: str) -> list[str]:
    from google import genai
    from google.genai import types

    client = genai.Client()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.0,
    )
    prompt = EXTRACTION_PROMPT.format(content=content)
    delay = _RETRY_BASE
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=config,
            )
            facts = _try_parse_json_array(response.text)
            if facts is not None:
                return facts
            logger.warning("Gemini returned unparseable response (attempt %d)", attempt + 1)
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) and attempt < _MAX_RETRIES - 1:
                logger.warning("Rate limited, retrying in %ds...", delay)
                time.sleep(delay)
                delay *= 2
                continue
            logger.error("Gemini extraction failed: %s", e)
            return []
    return []


def _extract_ollama(content: str) -> list[str]:
    import httpx

    prompt = EXTRACTION_PROMPT.format(content=content)
    messages = [{"role": "user", "content": prompt}]
    # Scale timeout with content length: ~60s per 1K tokens, minimum 120s
    timeout_s = max(120.0, len(content) / 4 * 0.06)

    for attempt in range(_JSON_INSIST_MAX):
        try:
            resp = httpx.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
                timeout=timeout_s,
            )
            resp.raise_for_status()
            raw = resp.json()["message"]["content"]

            facts = _try_parse_json_array(raw)
            if facts is not None:
                if attempt > 0:
                    logger.info("JSON insistor succeeded on attempt %d", attempt + 1)
                return facts

            # Insist on valid JSON
            logger.warning(
                "Ollama returned non-JSON (attempt %d/%d, %d chars), insisting...",
                attempt + 1, _JSON_INSIST_MAX, len(raw),
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": JSON_INSIST_MESSAGE})

        except Exception as e:
            logger.error("Ollama extraction failed: %s", e)
            return []

    logger.error("JSON insistor exhausted after %d attempts", _JSON_INSIST_MAX)
    return []


def extract_facts(content: str) -> list[str]:
    if BACKEND == "ollama":
        return _extract_ollama(content)
    return _extract_gemini(content)


async def reset_project(project_id: str) -> None:
    db_host = os.environ.get("MEMORYHUB_DB_HOST", "localhost")
    db_port = os.environ.get("MEMORYHUB_DB_PORT", "25432")
    db_user = os.environ.get("MEMORYHUB_DB_USER", "memoryhub")
    db_pass = os.environ.get("MEMORYHUB_DB_PASS", "")
    db_name = os.environ.get("MEMORYHUB_DB_NAME", "memoryhub")
    url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    engine = create_async_engine(url, pool_size=2)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(
                text("DELETE FROM memory_nodes WHERE owner_id LIKE 'amb-%' AND scope_id = :pid"),
                {"pid": project_id},
            )
            await session.commit()
            logger.info("Deleted %d memories for project %s", result.rowcount, project_id)
    finally:
        await engine.dispose()


async def ingest_facts(
    facts_by_doc: list[tuple[str, str, list[str]]],
    dry_run: bool = False,
) -> dict:
    if dry_run:
        total = sum(len(facts) for _, _, facts in facts_by_doc)
        logger.info("DRY RUN: would write %d facts from %d docs", total, len(facts_by_doc))
        return {"docs": len(facts_by_doc), "facts": total, "written": 0}

    url = os.environ["MEMORYHUB_URL"]
    api_key = os.environ["MEMORYHUB_API_KEY"]
    model_name = OLLAMA_MODEL if BACKEND == "ollama" else GEMINI_MODEL

    await reset_project(PROJECT_ID)

    written = 0
    async with MemoryHubClient(url=url, api_key=api_key) as client:
        try:
            await client.create_project(PROJECT_ID, description="Fact extraction benchmark")
            logger.info("Created project %s", PROJECT_ID)
        except Exception:
            logger.debug("Project %s already exists", PROJECT_ID)

        for doc_id, user_id, facts in facts_by_doc:
            owner = f"amb-{user_id}" if user_id else "amb-default"
            for i, fact in enumerate(facts):
                try:
                    result = await client.write(
                        content=fact,
                        scope="project",
                        project_id=PROJECT_ID,
                        owner_id=owner,
                        content_type="experiential",
                        force=True,
                        tenant_id=TENANT_ID,
                        metadata={
                            "source_doc_id": doc_id,
                            "fact_index": i,
                            "extraction_model": model_name,
                        },
                    )
                    if result.memory:
                        written += 1
                    else:
                        logger.warning("Fact gated for doc %s fact %d", doc_id, i)
                except Exception as e:
                    logger.error("Write failed for doc %s fact %d: %s", doc_id, i, e)

            if (written % 100) == 0 and written > 0:
                logger.info("Written %d facts so far...", written)

    total = sum(len(facts) for _, _, facts in facts_by_doc)
    logger.info("Ingestion complete: %d/%d facts written from %d docs", written, total, len(facts_by_doc))
    return {"docs": len(facts_by_doc), "facts": total, "written": written}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract facts from PersonaMem docs")
    parser.add_argument("--doc-limit", type=int, default=None, help="Max docs to process")
    parser.add_argument("--dry-run", action="store_true", help="Extract but don't write to MemoryHub")
    parser.add_argument("--sample", type=int, default=None, help="Print extracted facts for N docs and exit")
    args = parser.parse_args()

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        os.environ["GOOGLE_API_KEY"] = key

    model_name = OLLAMA_MODEL if BACKEND == "ollama" else GEMINI_MODEL
    logger.info("Backend: %s, Model: %s", BACKEND, model_name)

    ds = get_dataset("personamem")
    documents = ds.load_documents("32k")
    if args.doc_limit:
        documents = documents[:args.doc_limit]
    logger.info("Loaded %d PersonaMem documents", len(documents))

    facts_by_doc: list[tuple[str, str, list[str]]] = []
    total_facts = 0
    json_retries = 0

    for i, doc in enumerate(documents):
        facts = extract_facts(doc.content)
        facts_by_doc.append((doc.id, doc.user_id, facts))
        total_facts += len(facts)

        if args.sample and i < args.sample:
            print(f"\n=== Doc {doc.id} ({len(facts)} facts) ===")
            for j, f in enumerate(facts):
                print(f"  {j+1}. {f}")

        if (i + 1) % 20 == 0:
            logger.info("Extracted from %d/%d docs (%d facts so far)", i + 1, len(documents), total_facts)

    logger.info("Extraction complete: %d facts from %d docs (avg %.1f facts/doc)",
                total_facts, len(documents), total_facts / max(len(documents), 1))

    if args.sample:
        return

    result = asyncio.run(ingest_facts(facts_by_doc, dry_run=args.dry_run))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
