# Configuration for GitHub webhook triage bot

import os

REPO = "redhat-ai-americas/memory-hub"

SKIP_AUTHORS = set(
    os.environ.get("TRIAGE_SKIP_AUTHORS", "rdwj,dependabot[bot],github-actions[bot]").split(",")
)

RATE_LIMIT_MAX = int(os.environ.get("TRIAGE_RATE_LIMIT", "10"))

CLAUDE_TIMEOUT = int(os.environ.get("TRIAGE_CLAUDE_TIMEOUT", "120"))

TYPE_LABELS = [
    "type:bug",
    "type:feature",
    "type:design",
    "type:infra",
]

SUBSYSTEM_LABELS = [
    "subsystem:memory-tree",
    "subsystem:storage",
    "subsystem:curator",
    "subsystem:governance",
    "subsystem:mcp-server",
    "subsystem:operator",
    "subsystem:observability",
    "subsystem:org-ingestion",
    "subsystem:auth",
    "subsystem:ui",
    "subsystem:llamastack",
    "subsystem:kagenti",
    "subsystem:client",
]

SPECIAL_LABELS = [
    "needs-design",
    "good first issue",
    "help wanted",
    "priority:future",
    "kagenti-candidate",
]


def get_webhook_secret() -> str:
    secret = os.environ.get("TRIAGE_WEBHOOK_SECRET")
    if not secret:
        raise ValueError("TRIAGE_WEBHOOK_SECRET environment variable is required")
    return secret
