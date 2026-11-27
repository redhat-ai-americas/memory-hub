"""Local activity summaries for Claude Code and Codex lifecycle hooks.

The hook recorder stores only operation names, counts, and timestamps. It
never persists prompts, memory content, tool arguments, or tool responses.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = (
    Path.home() / ".config" / "memoryhub" / "activity" / "activity.sqlite3"
)
_EVENT_ALIASES = {
    "session-start": "session_start",
    "session_start": "session_start",
    "user-prompt-submit": "user_prompt_submit",
    "userpromptsubmit": "user_prompt_submit",
    "post-tool-use": "post_tool_use",
    "posttooluse": "post_tool_use",
    "cli-search": "cli_search",
    "cli-write": "cli_write",
    "session-end": "session_end",
    "sessionend": "session_end",
}
_MUTATING_ACTIONS = {"write", "update"}
_FAILURE_STATUSES = {"error", "failed", "failure", "rejected", "denied"}
_GATED_STATUSES = {"duplicate", "gated", "skipped"}


@dataclass(frozen=True)
class ActivitySnapshot:
    writes: int
    updates: int
    searches: int
    turns_since_write: int
    last_write_ns: int | None


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    connection = sqlite3.connect(path, timeout=2.0)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            project_key TEXT NOT NULL,
            session_key TEXT NOT NULL,
            started_ns INTEGER NOT NULL,
            PRIMARY KEY (project_key, session_key)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_key TEXT NOT NULL,
            session_key TEXT NOT NULL,
            event_type TEXT NOT NULL,
            operation TEXT,
            occurred_ns INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS activity_events_session_idx
            ON events(project_key, session_key, event_type, operation);
        CREATE INDEX IF NOT EXISTS activity_events_project_write_idx
            ON events(project_key, operation, occurred_ns);
        CREATE TABLE IF NOT EXISTS session_summaries (
            project_key TEXT NOT NULL,
            session_key TEXT NOT NULL,
            writes INTEGER NOT NULL,
            updates INTEGER NOT NULL,
            searches INTEGER NOT NULL,
            last_write_ns INTEGER,
            ended_ns INTEGER NOT NULL,
            PRIMARY KEY (project_key, session_key)
        );
        """
    )
    return connection


def _ensure_session(
    connection: sqlite3.Connection,
    project_key: str,
    session_key: str,
    now_ns: int,
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO sessions(project_key, session_key, started_ns) "
        "VALUES (?, ?, ?)",
        (project_key, session_key, now_ns),
    )


def _tool_operation(payload: dict[str, Any]) -> str | None:
    """Return the MemoryHub operation represented by a host tool event."""
    name = str(payload.get("tool_name") or payload.get("toolName") or "")
    leaf = name.rsplit("__", 1)[-1].lower().replace("-", "_")
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    if leaf == "memory":
        action = str(tool_input.get("action") or "").lower()
    else:
        action = ""
        for suffix, operation in (
            ("search_memory", "search"),
            ("memoryhub_search", "search"),
            ("write_memory", "write"),
            ("memoryhub_write", "write"),
            ("update_memory", "update"),
            ("memoryhub_update", "update"),
        ):
            if leaf == suffix:
                action = operation
                break

    if action in _MUTATING_ACTIONS | {"search"}:
        return action
    return None


def _response_values(value: Any):
    """Yield nested response values, decoding JSON text blocks when possible."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _response_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _response_values(child)
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith(("{", "[")):
            try:
                decoded = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return
            yield from _response_values(decoded)


def _tool_succeeded(payload: dict[str, Any]) -> bool:
    response = payload.get("tool_response", payload.get("toolResponse"))
    if isinstance(response, str) and re.match(
        r"^\s*(error|failed|failure)\b", response, flags=re.IGNORECASE,
    ):
        return False
    for value in _response_values(response):
        if not isinstance(value, dict):
            continue
        if value.get("isError") is True or value.get("is_error") is True:
            return False
        if value.get("success") is False or value.get("ok") is False:
            return False
        status = str(value.get("status", "")).lower()
        if status in _FAILURE_STATUSES | _GATED_STATUSES:
            return False
        curation = value.get("curation")
        if (
            isinstance(curation, dict)
            and curation.get("gated") is True
            and value.get("memory") is None
        ):
            return False
    # PostToolUse only runs after the host reports a tool call as completed.
    # Explicit error and curation-gate envelopes are excluded above.
    return True


def _snapshot(
    connection: sqlite3.Connection,
    project_key: str,
    session_key: str,
    now_ns: int,
) -> ActivitySnapshot:
    rows = connection.execute(
        "SELECT operation, COUNT(*) FROM events "
        "WHERE project_key = ? AND session_key = ? AND event_type = 'tool' "
        "GROUP BY operation",
        (project_key, session_key),
    ).fetchall()
    counts = {str(operation): int(count) for operation, count in rows}
    session = connection.execute(
        "SELECT started_ns FROM sessions WHERE project_key = ? AND session_key = ?",
        (project_key, session_key),
    ).fetchone()
    started_ns = int(session[0]) if session else now_ns
    last_session_write = connection.execute(
        "SELECT MAX(occurred_ns) FROM events WHERE project_key = ? "
        "AND session_key = ? AND event_type = 'tool' AND operation IN ('write', 'update')",
        (project_key, session_key),
    ).fetchone()[0]
    baseline_ns = int(last_session_write) if last_session_write else started_ns
    turns_since_write = int(connection.execute(
        "SELECT COUNT(*) FROM events WHERE project_key = ? AND session_key = ? "
        "AND event_type = 'user_prompt_submit' AND occurred_ns > ?",
        (project_key, session_key, baseline_ns),
    ).fetchone()[0])
    last_project_write = connection.execute(
        "SELECT MAX(occurred_ns) FROM events WHERE project_key = ? "
        "AND event_type = 'tool' AND operation IN ('write', 'update')",
        (project_key,),
    ).fetchone()[0]
    return ActivitySnapshot(
        writes=counts.get("write", 0),
        updates=counts.get("update", 0),
        searches=counts.get("search", 0),
        turns_since_write=turns_since_write,
        last_write_ns=int(last_project_write) if last_project_write else None,
    )


def _format_timestamp(timestamp_ns: int | None) -> str:
    if timestamp_ns is None:
        return "none observed on this machine for this project"
    timestamp = datetime.fromtimestamp(
        timestamp_ns / 1_000_000_000,
        timezone.utc,
    ).astimezone()
    return timestamp.strftime("%Y-%m-%d %H:%M %Z")


def _summary_text(snapshot: ActivitySnapshot) -> str:
    return (
        "MemoryHub activity so far this session: "
        f"{snapshot.writes} successful new saves, "
        f"{snapshot.updates} successful updates, and "
        f"{snapshot.searches} successful searches. "
        "Most recent successful save or update observed on this machine for "
        f"this project: {_format_timestamp(snapshot.last_write_ns)}."
    )


def process_activity_hook(
    event: str,
    payload: dict[str, Any],
    *,
    database_path: Path | None = None,
    now_ns: int | None = None,
) -> str | None:
    """Record one host hook event and return context to inject, when useful."""
    normalized_event = _EVENT_ALIASES.get(event.lower().replace("_", "-"))
    if normalized_event is None:
        normalized_event = _EVENT_ALIASES.get(event.lower())
    if normalized_event is None:
        return None

    session_id = payload.get("session_id") or payload.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        return None
    project_dir = str(payload.get("cwd") or os.getcwd())
    project_key = _stable_key(os.path.realpath(project_dir))
    session_key = _stable_key(f"{project_key}:{session_id}")
    now = now_ns if now_ns is not None else time.time_ns()

    connection = _connection(database_path or _DEFAULT_DB_PATH)
    try:
        _ensure_session(connection, project_key, session_key, now)

        if normalized_event == "session_start":
            connection.execute(
                "INSERT INTO events(project_key, session_key, event_type, occurred_ns) "
                "VALUES (?, ?, 'session_start', ?)",
                (project_key, session_key, now),
            )
            connection.commit()
            if payload.get("source") not in (None, "startup"):
                return None
            previous = connection.execute(
                "SELECT writes, updates, searches, last_write_ns FROM session_summaries "
                "WHERE project_key = ? AND session_key != ? ORDER BY ended_ns DESC LIMIT 1",
                (project_key, session_key),
            ).fetchone()
            if previous is None:
                return None
            writes, updates, searches, last_write_ns = previous
            return (
                "Previous MemoryHub session: "
                f"{int(writes)} successful new saves, {int(updates)} successful updates, "
                f"and {int(searches)} successful searches. Most recent successful save "
                "or update observed on this machine for this project: "
                f"{_format_timestamp(int(last_write_ns) if last_write_ns else None)}."
            )

        if normalized_event == "cli_search":
            connection.execute(
                "INSERT INTO events(project_key, session_key, event_type, operation, occurred_ns) "
                "VALUES (?, ?, 'tool', 'search', ?)",
                (project_key, session_key, now),
            )
            connection.commit()
            return None

        if normalized_event == "cli_write":
            count = payload.get("count", 0)
            try:
                writes = max(0, min(int(count), 200))
            except (TypeError, ValueError):
                writes = 0
            connection.executemany(
                "INSERT INTO events(project_key, session_key, event_type, operation, occurred_ns) "
                "VALUES (?, ?, 'tool', 'write', ?)",
                [
                    (project_key, session_key, now + index)
                    for index in range(writes)
                ],
            )
            connection.commit()
            return None

        if normalized_event == "post_tool_use":
            operation = _tool_operation(payload)
            if operation is None or not _tool_succeeded(payload):
                return None
            connection.execute(
                "INSERT INTO events(project_key, session_key, event_type, operation, occurred_ns) "
                "VALUES (?, ?, 'tool', ?, ?)",
                (project_key, session_key, operation, now),
            )
            connection.commit()
            return _summary_text(_snapshot(connection, project_key, session_key, now))

        if normalized_event == "user_prompt_submit":
            connection.execute(
                "INSERT INTO events(project_key, session_key, event_type, occurred_ns) "
                "VALUES (?, ?, 'user_prompt_submit', ?)",
                (project_key, session_key, now),
            )
            connection.commit()
            snapshot = _snapshot(connection, project_key, session_key, now)
            summary = _summary_text(snapshot)
            if (
                snapshot.turns_since_write >= 10
                and snapshot.turns_since_write % 10 == 0
            ):
                summary += (
                    f" No successful memory write has occurred in "
                    f"{snapshot.turns_since_write} user turns. If the current "
                    "work contains durable information, consider saving it; "
                    "do not create low-value memories just to satisfy this reminder."
                )
            return summary

        # SessionEnd cannot feed the completed session's model response. Save a
        # durable snapshot locally so the session's activity remains recorded.
        snapshot = _snapshot(connection, project_key, session_key, now)
        connection.execute(
            "INSERT INTO session_summaries(project_key, session_key, writes, updates, "
            "searches, last_write_ns, ended_ns) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(project_key, session_key) DO UPDATE SET "
            "writes=excluded.writes, updates=excluded.updates, searches=excluded.searches, "
            "last_write_ns=excluded.last_write_ns, ended_ns=excluded.ended_ns",
            (
                project_key,
                session_key,
                snapshot.writes,
                snapshot.updates,
                snapshot.searches,
                snapshot.last_write_ns,
                now,
            ),
        )
        connection.commit()
        return None
    finally:
        connection.close()


def format_hook_output(event_name: str, context: str) -> str:
    """Return the shared JSON envelope accepted by Claude Code and Codex."""
    safe_event = re.sub(r"[^A-Za-z]", "", event_name)
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": safe_event,
            "additionalContext": context,
        }
    })


__all__ = ["format_hook_output", "process_activity_hook"]
