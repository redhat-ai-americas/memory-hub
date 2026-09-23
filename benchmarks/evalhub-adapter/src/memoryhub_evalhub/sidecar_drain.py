"""Retry result reporting and hold the adapter alive so the sidecar can flush.

EvalHub jobs run as adapter + sidecar. ``DefaultCallbacks.report_results()``
POSTs COMPLETED+metrics to the sidecar, which proxies to the EvalHub server.
The SDK swallows HTTP errors, so a failed POST looks like success and the
adapter exits. Kubernetes then SIGTERMs the sidecar, which can still be
forwarding -- completed jobs show score=N/A in the API (#426, related #364).

This module retries until the sidecar acknowledges the POST (2xx or 409),
then sleeps so an in-flight proxy call can finish before the process exits.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DRAIN_SECONDS = 30
DEFAULT_RETRIES = 5
DEFAULT_BACKOFF_SECONDS = 2.0

# 409: sidecar/server already has COMPLETED (a prior attempt landed).
_SUCCESS_STATUS_CODES = frozenset({200, 201, 202, 204, 409})

ENV_DRAIN_SECONDS = "EVALHUB_SIDECAR_DRAIN_SECONDS"
ENV_RETRIES = "EVALHUB_SIDECAR_REPORT_RETRIES"
ENV_BACKOFF_SECONDS = "EVALHUB_SIDECAR_RETRY_BACKOFF_SECONDS"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def sidecar_configured(callbacks: Any) -> bool:
    """True when callbacks can POST to a sidecar HTTP client."""
    return bool(
        getattr(callbacks, "sidecar_url", None)
        and getattr(callbacks, "_http_client", None)
        and getattr(callbacks, "_httpx_available", True)
    )


def k8s_sidecar_mode(callbacks: Any) -> bool:
    """True only for cluster jobs where pod exit would SIGTERM the sidecar.

    Local smoke runs often set ``callback_url`` (so an HTTP client exists) but
    there is no sidecar to drain. Honor ``EVALHUB_MODE=k8s`` as the gate.
    """
    mode = os.environ.get("EVALHUB_MODE", "local").strip().lower()
    return mode == "k8s" and sidecar_configured(callbacks)


class _PostObserver:
    """Wrap an HTTP client's ``post`` to record the last response status."""

    def __init__(self, client: Any) -> None:
        self.ok = False
        self.status_code: int | None = None
        self.error: BaseException | None = None
        self._client = client
        self._original_post = client.post
        client.post = self._tracked_post

    def restore(self) -> None:
        self._client.post = self._original_post

    def reset(self) -> None:
        self.ok = False
        self.status_code = None
        self.error = None

    def _tracked_post(self, *args: Any, **kwargs: Any) -> Any:
        self.reset()
        try:
            response = self._original_post(*args, **kwargs)
        except Exception as exc:
            self.error = exc
            raise
        self.status_code = getattr(response, "status_code", None)
        if self.status_code in _SUCCESS_STATUS_CODES:
            self.ok = True
        return response


def report_results_and_drain(
    callbacks: Any,
    results: Any,
    *,
    drain_seconds: int | None = None,
    retries: int | None = None,
    backoff_seconds: float | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """Report job results, retrying sidecar POSTs, then drain.

    Returns True if the sidecar acknowledged the results (HTTP 2xx or 409),
    or if there is no sidecar (local mode). Returns False if every attempt
    failed; still drains in that case in case the last POST is in flight.
    """
    if drain_seconds is None:
        drain_seconds = _env_int(ENV_DRAIN_SECONDS, DEFAULT_DRAIN_SECONDS)
    if retries is None:
        retries = _env_int(ENV_RETRIES, DEFAULT_RETRIES)
    if backoff_seconds is None:
        backoff_seconds = _env_float(ENV_BACKOFF_SECONDS, DEFAULT_BACKOFF_SECONDS)

    if not k8s_sidecar_mode(callbacks):
        callbacks.report_results(results)
        return True

    attempts = max(1, retries)
    observer = _PostObserver(callbacks._http_client)
    reported = False
    try:
        for attempt in range(1, attempts + 1):
            callbacks.report_results(results)
            if observer.ok:
                reported = True
                logger.info(
                    "Sidecar accepted results (HTTP %s) on attempt %d/%d",
                    observer.status_code,
                    attempt,
                    attempts,
                )
                break
            if attempt < attempts:
                wait = backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "Sidecar did not accept results on attempt %d/%d "
                    "(status=%s error=%s); retrying in %.1fs",
                    attempt,
                    attempts,
                    observer.status_code,
                    observer.error,
                    wait,
                )
                sleeper(wait)
    finally:
        observer.restore()

    if drain_seconds > 0:
        logger.info(
            "Draining sidecar for %ds so results can be forwarded before exit",
            drain_seconds,
        )
        sleeper(drain_seconds)

    if not reported:
        logger.error(
            "Sidecar never acknowledged results after %d attempt(s); "
            "EvalHub API may show score=N/A",
            attempts,
        )
    return reported
