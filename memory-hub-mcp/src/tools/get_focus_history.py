"""Retrieve aggregated per-project histogram of session focus declarations (#61).

Reads the append-only history log written by ``set_session_focus`` across a
date range, counts focus-string occurrences, and returns a sorted histogram.
This is an advisory-only usage signal — it does NOT auto-tune memory weights
or feed into retrieval ranking. Humans and agents consume it informationally,
for example to decide which focus topics are most active on a project or to
spot coverage gaps in recent sessions.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.valkey_client import (
    ValkeyUnavailableError,
    get_valkey_client,
)
from src.core.app import mcp
from src.core.authz import AuthenticationError, get_claims_from_context

_DEFAULT_WINDOW_DAYS = 30


def _parse_iso_date(label: str, value: str | None) -> date | None:
    """Parse an optional YYYY-MM-DD string into a ``date``.

    ``label`` is the parameter name for error messages ("start_date" or
    "end_date"). Returns None if the input is None or empty.
    """
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ToolError(
            f"Invalid {label} format: {value!r}. Expected ISO format YYYY-MM-DD."
        ) from exc


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_focus_history(
    project: Annotated[
        str,
        Field(
            description=(
                "The project identifier to query. Typically matches the `project` "
                "field of project-scope memories and the `project` value in "
                "`.memoryhub.yaml`."
            ),
        ),
    ],
    start_date: Annotated[
        str | None,
        Field(
            description=(
                "Start of the date range, inclusive, in ISO format YYYY-MM-DD. "
                "Defaults to 30 days before `end_date`."
            ),
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(
            description=(
                "End of the date range, inclusive, in ISO format YYYY-MM-DD. "
                "Defaults to today (UTC)."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Aggregate per-project session focus declarations into a sorted histogram.

    Reads from ``memoryhub:session_focus_history:<project>:<yyyy-mm-dd>`` for
    every day in the range, counts focus-string occurrences, and returns the
    histogram sorted by count descending (ties broken alphabetically). This
    is advisory-only: the histogram answers "what has this project been
    working on recently?" but does not auto-tune anything.

    Args:
        project: Project identifier to query.
        start_date: Start of the window, inclusive (YYYY-MM-DD). Default: 30
            days before end_date.
        end_date: End of the window, inclusive (YYYY-MM-DD). Default: today
            (UTC).
        ctx: FastMCP context for logging.

    Returns:
        A dict with:
        - ``project`` (str): Echo of the input.
        - ``start_date`` / ``end_date`` (str): The window actually queried.
        - ``total_sessions`` (int): Count of focus declarations in the window.
        - ``histogram`` (list[dict]): Sorted entries ``{focus, count}``.

    Raises:
        ToolError: On inverted date range, malformed date string, no
            authentication, or Valkey unavailability.
    """
    if not project or not project.strip():
        raise ToolError(
            "project must not be empty. Provide the project identifier to query "
            "(typically from .memoryhub.yaml)."
        )
    project = project.strip()

    try:
        get_claims_from_context()
    except AuthenticationError:
        raise ToolError(
            "No authenticated session found. Call register_session first, or "
            "provide a JWT in the Authorization header."
        ) from None

    parsed_end = _parse_iso_date("end_date", end_date)
    parsed_start = _parse_iso_date("start_date", start_date)

    if parsed_end is None:
        parsed_end = datetime.now(timezone.utc).date()
    if parsed_start is None:
        parsed_start = parsed_end - timedelta(days=_DEFAULT_WINDOW_DAYS)

    if parsed_start > parsed_end:
        raise ToolError(
            f"start_date ({parsed_start.isoformat()}) is after end_date "
            f"({parsed_end.isoformat()}). Provide dates as YYYY-MM-DD where "
            "start_date <= end_date."
        )

    valkey = get_valkey_client()
    try:
        entries = await valkey.read_focus_history(
            project=project,
            start_date=parsed_start,
            end_date=parsed_end,
        )
    except ValkeyUnavailableError as exc:
        raise ToolError(
            f"Session focus store is unavailable: {exc}. Histogram data cannot "
            "be retrieved until the backend recovers."
        ) from exc

    counts: dict[str, int] = {}
    for entry in entries:
        focus = entry.get("focus")
        if not isinstance(focus, str) or not focus:
            continue
        counts[focus] = counts.get(focus, 0) + 1

    # Sort by count descending, then alphabetically by focus for stable ordering.
    histogram = [
        {"focus": f, "count": c}
        for f, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    if ctx is not None:
        await ctx.info(
            f"Focus history query for {project}: {len(entries)} declarations, "
            f"{len(histogram)} distinct topics over "
            f"{parsed_start.isoformat()}..{parsed_end.isoformat()}"
        )

    return {
        "project": project,
        "start_date": parsed_start.isoformat(),
        "end_date": parsed_end.isoformat(),
        "total_sessions": len(entries),
        "histogram": histogram,
    }
