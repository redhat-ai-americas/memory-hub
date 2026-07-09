"""GitHub webhook receiver for triage automation."""

import hashlib
import hmac
import logging
import subprocess
import time
from collections import deque
from typing import Any

from config import CLAUDE_TIMEOUT, RATE_LIMIT_MAX, SKIP_AUTHORS, get_webhook_secret
from fastapi import BackgroundTasks, FastAPI, Request, Response

from prompts import build_issue_prompt, build_pr_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("triage")

app = FastAPI(title="MemoryHub Triage Bot")

rate_limit_queue: deque = deque()


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("Invalid signature format: %s", signature_header)
        return False

    signature = signature_header.replace("sha256=", "")
    secret = get_webhook_secret()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected):
        logger.warning("Signature mismatch")
        return False

    return True


def check_rate_limit() -> bool:
    now = time.time()
    cutoff = now - 60.0

    # Prune old entries
    while rate_limit_queue and rate_limit_queue[0] < cutoff:
        rate_limit_queue.popleft()

    # Check limit
    if len(rate_limit_queue) >= RATE_LIMIT_MAX:
        logger.warning("Rate limit exceeded: %d requests in last 60s", len(rate_limit_queue))
        return False

    # Record this request
    rate_limit_queue.append(now)
    return True


def run_triage(event_type: str, prompt: str, number: int) -> None:
    logger.info("Starting triage for %s #%d", event_type, number)

    try:
        result = subprocess.run(
            ["claude", "-p", "--verbose", prompt],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )

        if result.returncode == 0:
            logger.info("Triage completed for %s #%d", event_type, number)
            if result.stdout:
                logger.debug("Claude stdout:\n%s", result.stdout)
        else:
            logger.error(
                "Triage failed for %s #%d (exit %d)",
                event_type,
                number,
                result.returncode,
            )
            if result.stderr:
                logger.error("Claude stderr:\n%s", result.stderr)

    except subprocess.TimeoutExpired:
        logger.error(
            "Triage timed out for %s #%d after %ds",
            event_type,
            number,
            CLAUDE_TIMEOUT,
        )
    except FileNotFoundError:
        logger.error("Claude Code CLI not found in PATH")
    except Exception as e:
        logger.error("Unexpected error triaging %s #%d: %s", event_type, number, e, exc_info=True)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    response: Response,
) -> dict[str, Any]:
    # Read raw body for signature verification
    body = await request.body()

    # Verify webhook signature
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(body, signature):
        response.status_code = 401
        return {"error": "Invalid signature"}

    # Check rate limit
    if not check_rate_limit():
        response.status_code = 429
        return {"error": "Rate limit exceeded"}

    # Parse JSON payload
    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event")

    logger.info("Received %s event: action=%s", event_type, payload.get("action"))

    # Route by event type and action
    if event_type == "issues" and payload.get("action") == "opened":
        issue = payload["issue"]
        author = issue["user"]["login"]
        number = issue["number"]

        # Filter internal authors
        if author in SKIP_AUTHORS:
            logger.info("Skipping issue #%d from internal author %s", number, author)
            return {"status": "skipped", "reason": "internal author"}

        prompt = build_issue_prompt(payload)
        background_tasks.add_task(run_triage, "issue", prompt, number)

        response.status_code = 202
        return {"status": "accepted", "event": "issue", "number": number}

    elif event_type == "pull_request" and payload.get("action") == "opened":
        pr = payload["pull_request"]
        author = pr["user"]["login"]
        number = pr["number"]

        # Filter internal authors
        if author in SKIP_AUTHORS:
            logger.info("Skipping PR #%d from internal author %s", number, author)
            return {"status": "skipped", "reason": "internal author"}

        prompt = build_pr_prompt(payload)
        background_tasks.add_task(run_triage, "pr", prompt, number)

        response.status_code = 202
        return {"status": "accepted", "event": "pr", "number": number}

    else:
        # Ignore other events
        return {"status": "ignored"}
