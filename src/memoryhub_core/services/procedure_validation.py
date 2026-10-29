"""Optional validation gate for structural procedural edits (#554).

In ``apply`` mode the deterministic gates (supporting sessions, attributable
failures, graph invariants) decide whether ``add_step`` / ``add_edge`` /
``deprecate_step`` / ``deprecate_edge`` land. Operators who want an extra,
evaluation-based check before the graph changes configure
``MEMORYHUB_PROCEDURAL_VALIDATION_URL``: an HTTP service (for example one
backed by an EvalHub replay benchmark) that scores the planned edits and
answers ``accept`` or ``reject`` per edit.

Off by default. When on, it fails closed: a structural edit lands only if
the validator accepted exactly that edit in phase A. Anything else (the
validator rejected it, was unreachable, or never saw it because a concurrent
run changed the plan) stays in ``pending_edits`` with a reason and is asked
about again on the next supporting session. Non-structural edits (attribute
merges, weights) are not gated.

The call happens in phase A, with no transaction open, like the model call.

Request (``POST {url}``)::

    {"schema_version": 1, "procedure_id": "...", "goal": "...",
     "description": "...", "run_id": "...", "edits": [
        {"key": "<edit key>", "edit": "add_step", "target": "...",
         "payload": {...}, "support": ["<thread id>", ...]}]}

Response::

    {"verdicts": {"<edit key>": "accept" | "reject"}, "detail": "optional"}

The request carries no transcript text and no credentials: edit payloads are
the observed attributes that would be written to the graph anyway.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

ACCEPT = "accept"
REJECTED = "validation_rejected"
UNAVAILABLE = "validation_unavailable"
UNSEEN = "validation_unseen"

#: Rejection reasons this gate adds to the decision log.
VALIDATION_REASONS = frozenset({REJECTED, UNAVAILABLE, UNSEEN})


class ProcedureValidationError(RuntimeError):
    """The validator could not be reached or answered with something unusable."""


class ProcedureEditValidator(Protocol):
    async def validate(self, request: dict[str, Any]) -> dict[str, str]:
        """Return ``{edit key: "accept" | "reject"}``; raise on failure."""
        ...

    async def aclose(self) -> None: ...


class HttpProcedureValidator:
    """POSTs the planned structural edits to an external validation service."""

    def __init__(
        self,
        *,
        url: str,
        api_key: str = "",
        timeout: float = 120,
        ca_bundle: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # TLS verification stays on (#604); a private CA is a bundle path.
        verify: Any = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True
        self._client = client or httpx.AsyncClient(timeout=timeout, headers=headers, verify=verify)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def validate(self, request: dict[str, Any]) -> dict[str, str]:
        try:
            response = await self._client.post(self.url, json=request)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProcedureValidationError(
                f"validator returned {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProcedureValidationError(f"validator unreachable: {type(exc).__name__}") from exc
        verdicts = body.get("verdicts") if isinstance(body, dict) else None
        if not isinstance(verdicts, dict):
            raise ProcedureValidationError("validator response has no 'verdicts' object")
        return {str(k): str(v) for k, v in verdicts.items()}


def build_validator(settings: Any) -> ProcedureEditValidator | None:
    url = (getattr(settings, "procedural_validation_url", "") or "").strip()
    if not url:
        return None
    return HttpProcedureValidator(
        url=url,
        api_key=getattr(settings, "procedural_validation_api_key", "") or "",
        timeout=float(getattr(settings, "procedural_validation_timeout", 120)),
        ca_bundle=getattr(settings, "procedural_validation_ca_bundle", "") or None,
    )


def build_validation_request(
    *, procedure_id: str, goal: str, description: str, run_id: str, edits: list[Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "procedure_id": procedure_id,
        "goal": goal,
        "description": description,
        "run_id": run_id,
        "edits": [
            {"key": e.key(), "edit": e.kind, "target": e.target, "payload": e.payload,
             "support": e.support}
            for e in edits
        ],
    }


async def validate_structural_edits(
    validator: ProcedureEditValidator, *, edits: list[Any], **request: Any,
) -> dict[str, str]:
    """Phase-A verdicts for the planned structural edits, keyed by ``Edit.key()``.

    Never raises: an unusable validator turns every planned edit into
    ``validation_unavailable``. Only an explicit ``accept`` lets an edit land.
    """
    structural = [e for e in edits if e.structural]
    if not structural:
        return {}
    try:
        answers = await validator.validate(build_validation_request(edits=structural, **request))
    except Exception as exc:  # fail closed
        logger.warning("Procedure validation unavailable: %s", exc)
        return {e.key(): UNAVAILABLE for e in structural}
    return {
        e.key(): ACCEPT if answers.get(e.key()) == ACCEPT else REJECTED for e in structural
    }


def gate_reason(verdicts: dict[str, str] | None, edit: Any) -> str | None:
    """None when the edit may land; otherwise the pending/rejection reason."""
    if verdicts is None or not edit.structural:
        return None
    verdict = verdicts.get(edit.key(), UNSEEN)
    return None if verdict == ACCEPT else verdict
