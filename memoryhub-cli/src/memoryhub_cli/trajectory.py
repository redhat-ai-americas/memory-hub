"""Record Claude Code session trajectories into MemoryHub threads (#554).

Claude Code hooks (UserPromptSubmit, PostToolUse, PostToolUseFailure, Stop)
pipe a JSON payload to ``memoryhub thread record``. This module turns each
payload into thread messages (``user``, ``tool_call`` + ``tool_result``,
``assistant``) so the dreaming pipeline can learn procedures from real
tool-call trajectories. Recording is opt-in (``memoryhub config init
--record-trajectories``) and never blocks or fails the host.

Payload fields follow the Claude Code hook inputs: ``session_id``,
``hook_event_name``, ``prompt`` (UserPromptSubmit), ``tool_name`` /
``tool_input`` / ``tool_response`` / ``tool_use_id`` (PostToolUse),
``error`` (PostToolUseFailure) and ``last_assistant_message`` (Stop).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # POSIX; on Windows concurrent hooks of one session are not serialized
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

DEFAULT_MAX_CHARS = 16000

#: MemoryHub's own tools are not part of the user's procedure.
_SKIPPED_TOOL_PREFIXES = ("mcp__memoryhub", "mcp__memory-hub", "mcp__plugin_memoryhub")

#: Best-effort client-side redaction before anything leaves the machine. The
#: server's curation pipeline still scans everything derived from threads.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[REDACTED]"),
    (re.compile(r"mh-dev-[0-9a-fA-F]{8,}"), "[REDACTED]"),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED]",
    ),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)((?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)[\"']?[^\s\"']{6,}"
        ),
        r"\1[REDACTED]",
    ),
]

_OUTCOMES = ("success", "failure", "partial")


def redact_secrets(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.75)
    tail = max_chars - head
    return f"{text[:head]}\n[... {len(text) - max_chars} chars omitted ...]\n{text[-tail:]}"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


@dataclass
class TrajectoryMessage:
    role: str
    content: str
    tool_call_id: str | None = None
    metadata: dict[str, Any] | None = None


def messages_from_hook_payload(
    payload: dict[str, Any], *, max_chars: int = DEFAULT_MAX_CHARS
) -> list[TrajectoryMessage]:
    """Map one Claude Code hook payload to thread messages (possibly none)."""
    event = payload.get("hook_event_name")

    def text(value: Any) -> str:
        return clip(redact_secrets(_as_text(value)), max_chars)

    if event == "UserPromptSubmit":
        prompt = _as_text(payload.get("prompt")).strip()
        return [TrajectoryMessage("user", text(prompt))] if prompt else []

    if event in ("PostToolUse", "PostToolUseFailure"):
        tool = str(payload.get("tool_name") or "")
        if not tool or tool.startswith(_SKIPPED_TOOL_PREFIXES):
            return []
        call_id = str(payload.get("tool_use_id") or "") or None
        call = text({"tool": tool, "input": payload.get("tool_input") or {}})
        if event == "PostToolUse":
            result = text(payload.get("tool_response")) or "(no output)"
            meta = None
        else:
            result = text(f"ERROR: {_as_text(payload.get('error'))}")
            meta = {"is_error": True}
        return [
            TrajectoryMessage("tool_call", call, call_id),
            TrajectoryMessage("tool_result", result, call_id, meta),
        ]

    if event == "Stop":
        message = _as_text(payload.get("last_assistant_message")).strip()
        return [TrajectoryMessage("assistant", text(message))] if message else []

    return []


def outcome_message(result: str, note: str | None = None) -> TrajectoryMessage:
    """The explicit outcome marker the procedural pass reads (D-Outcome)."""
    if result not in _OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(_OUTCOMES)}")
    content = f"Session outcome: {result}" + (f". {redact_secrets(note)}" if note else "")
    return TrajectoryMessage("system", content, None, {"outcome": result})


# ---------------------------------------------------------------------------
# session -> thread state
# ---------------------------------------------------------------------------


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "memoryhub" / "trajectories"


@dataclass
class SessionState:
    session_id: str
    thread_id: str | None = None
    project_dir: str | None = None
    updated_at: float = field(default_factory=time.time)


def _safe_name(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:128] or "unknown"


@contextlib.contextmanager
def locked_state(session_id: str) -> Iterator[SessionState]:
    """Load and lock one session's state; saved on exit.

    The lock serializes concurrent hooks of the same session (Claude Code
    can run PostToolUse hooks for parallel tool calls at once), so only one
    of them creates the thread.
    """
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_safe_name(session_id)}.json"
    with open(directory / f"{_safe_name(session_id)}.lock", "a+") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError):
            data = {}
        state = SessionState(
            session_id=session_id,
            thread_id=data.get("thread_id"),
            project_dir=data.get("project_dir"),
            updated_at=float(data.get("updated_at", time.time())),
        )
        yield state
        state.updated_at = time.time()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "session_id": state.session_id,
                    "thread_id": state.thread_id,
                    "project_dir": state.project_dir,
                    "updated_at": state.updated_at,
                }
            )
        )
        os.replace(tmp, path)


def latest_thread_for(project_dir: str | None) -> str | None:
    """Most recently recorded thread, optionally restricted to a project directory."""
    directory = state_dir()
    if not directory.exists():
        return None
    best: tuple[float, str] | None = None
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not data.get("thread_id"):
            continue
        if project_dir and data.get("project_dir") not in (None, project_dir):
            continue
        stamp = float(data.get("updated_at", 0))
        if best is None or stamp > best[0]:
            best = (stamp, data["thread_id"])
    return best[1] if best else None
