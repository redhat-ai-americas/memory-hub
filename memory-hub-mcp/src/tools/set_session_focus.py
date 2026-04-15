"""Declare the current session's focus topic for #61 history and #62 broadcast filter.

Writes two records to Valkey atomically:

1. ``memoryhub:sessions:<session_id>`` — an active-session hash carrying the
   focus string and its 384-dim embedded vector, with a TTL matching the JWT
   lifetime. Consumed by the (future) #62 Pattern E broadcast filter to
   pre-filter push notifications by per-session cosine distance.
2. ``memoryhub:session_focus_history:<project>:<yyyy-mm-dd>`` — an append-only
   JSON entry in the per-project per-day history list. Consumed by
   ``get_focus_history`` to build the #61 usage-signal histogram.

**Session ID model (interim).** The current session_id is the authenticated
``sub`` claim — i.e. the user_id. That means a user has a single active
"session" at a time and a second ``set_session_focus`` call overwrites the
active-session hash while appending a new history entry. When we need
multi-concurrent-sessions-per-user (for example, an agent swarm where one
user runs several conversations in parallel), this becomes the JWT ``jti`` or
a server-minted session cookie. The ValkeyClient schema already accepts an
opaque session_id so the switch is local to this tool.
"""

from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.exceptions import (
    EmbeddingContentTooLargeError,
    EmbeddingServiceError,
    EmbeddingServiceUnavailableError,
)
from memoryhub_core.services.valkey_client import (
    ValkeyUnavailableError,
    get_valkey_client,
)
from src.core.app import mcp
from src.core.authz import AuthenticationError, get_claims_from_context
from src.tools._deps import get_embedding_service


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def set_session_focus(
    focus: Annotated[
        str,
        Field(
            description=(
                "A short natural-language topic describing this session's current "
                "focus. 5-10 words work best. Examples: 'deployment', "
                "'MCP tool design for session focus', 'UI panel for curation rules'. "
                "The SDK normally infers this from working directory or first user "
                "turn, but agents can declare explicitly or update mid-session "
                "when the conversation pivots."
            ),
        ),
    ],
    project: Annotated[
        str,
        Field(
            description=(
                "The project identifier this session belongs to. Typically matches "
                "the `project` field of project-scope memories and the `project` "
                "value in `.memoryhub.yaml`. Required so the history aggregation "
                "can scope per-project."
            ),
        ),
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    """Declare the session's focus topic; stored in Valkey for history and broadcast filtering.

    Writes to two Valkey keys in a single pipeline:

    - An active-session hash (``memoryhub:sessions:<session_id>``) with TTL
      matching the JWT lifetime, containing the focus string and a base64-
      encoded 384-dim embedding vector. Reused by the #62 Pattern E push-side
      broadcast filter to cosine-rank notifications per active session.
    - A per-project per-day history list
      (``memoryhub:session_focus_history:<project>:<yyyy-mm-dd>``) with a
      30-day retention TTL. Consumed by ``get_focus_history`` for the #61
      usage-signal histogram.

    Args:
        focus: 5-10 word natural-language topic describing the session.
        project: Project identifier for history scoping.
        ctx: FastMCP context for logging.

    Returns:
        A dict with ``session_id``, ``user_id``, ``project``, ``focus``,
        ``expires_at`` (ISO datetime), and a human-readable ``message``.

    Raises:
        ToolError: If focus is empty, no authenticated session exists, or the
            Valkey backend is unreachable. Errors carry actionable messages
            that describe how to recover.
    """
    if not focus or not focus.strip():
        raise ToolError(
            "focus must not be empty. Provide a 5-10 word topic describing the "
            "session's current focus."
        )

    if not project or not project.strip():
        raise ToolError(
            "project must not be empty. Provide the project identifier this "
            "session belongs to (typically from .memoryhub.yaml)."
        )

    focus = focus.strip()
    project = project.strip()

    try:
        claims = get_claims_from_context()
    except AuthenticationError:
        raise ToolError(
            "No authenticated session found. Call register_session first, or "
            "provide a JWT in the Authorization header."
        ) from None

    user_id = claims["sub"]
    session_id = user_id  # interim: see module docstring

    embedding_service = get_embedding_service()
    try:
        focus_vector = await embedding_service.embed(focus)
    except EmbeddingContentTooLargeError as exc:
        raise ToolError(
            f"Invalid focus text: {exc.content_length} characters exceeds the "
            "embedding model's input limit. Use a shorter focus description "
            "(5-10 words recommended)."
        ) from exc
    except EmbeddingServiceUnavailableError as exc:
        raise ToolError(
            f"Embedding service is unavailable: {exc.reason}. Session focus was "
            "not set. Retry after the embedding service recovers."
        ) from exc
    except EmbeddingServiceError as exc:
        raise ToolError(
            f"Failed to embed focus text: {exc}. Session focus was not set."
        ) from exc

    valkey = get_valkey_client()
    try:
        result = await valkey.write_session_focus(
            session_id=session_id,
            focus=focus,
            focus_vector=focus_vector,
            user_id=user_id,
            project=project,
        )
    except ValkeyUnavailableError as exc:
        raise ToolError(
            f"Session focus store is unavailable: {exc}. Focus was not recorded; "
            "retry after the backend recovers."
        ) from exc

    if ctx is not None:
        await ctx.info(
            f"Session focus recorded for {user_id} in project {project}: {focus!r}"
        )

    return {
        "session_id": session_id,
        "user_id": user_id,
        "project": project,
        "focus": focus,
        "expires_at": result["expires_at"],
        "message": (
            f"Session focus recorded for {user_id} in project {project}. "
            f"Active-session record expires at {result['expires_at']}."
        ),
    }
