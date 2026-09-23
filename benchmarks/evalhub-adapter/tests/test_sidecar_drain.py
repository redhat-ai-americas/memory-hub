"""Tests for sidecar result-drain retry (issue #426).

Imports bypass the package __init__.py to avoid pulling in the EvalHub SDK.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_src = Path(__file__).resolve().parent.parent / "src"
_spec = importlib.util.spec_from_file_location(
    "memoryhub_evalhub.sidecar_drain",
    _src / "memoryhub_evalhub" / "sidecar_drain.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_mod.__name__] = _mod
_spec.loader.exec_module(_mod)

report_results_and_drain = _mod.report_results_and_drain
sidecar_configured = _mod.sidecar_configured
k8s_sidecar_mode = _mod.k8s_sidecar_mode
ENV_DRAIN_SECONDS = _mod.ENV_DRAIN_SECONDS
ENV_RETRIES = _mod.ENV_RETRIES
ENV_BACKOFF_SECONDS = _mod.ENV_BACKOFF_SECONDS


class FakeHTTPError(Exception):
    def __init__(self, response: FakeResponse) -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.response = response


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise FakeHTTPError(self)


class FakeClient:
    """httpx-like client whose ``post`` can be scripted per call."""

    def __init__(self, outcomes: list[int | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        if not self.outcomes:
            raise AssertionError("unexpected extra POST")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


class FakeCallbacks:
    """Mimics DefaultCallbacks.report_results(): POST then swallow errors."""

    def __init__(
        self,
        *,
        sidecar_url: str | None = "http://localhost:8080",
        outcomes: list[int | Exception] | None = None,
        http_client: FakeClient | None = None,
        httpx_available: bool = True,
    ) -> None:
        self.sidecar_url = sidecar_url
        self._httpx_available = httpx_available
        self._http_client = http_client or (
            FakeClient(outcomes or [204]) if sidecar_url else None
        )
        self.report_calls = 0

    def report_results(self, results) -> None:
        self.report_calls += 1
        client = getattr(self, "_http_client", None)
        if not (self.sidecar_url and client and self._httpx_available):
            return
        try:
            response = client.post("http://sidecar/events", json={"results": results})
            response.raise_for_status()
        except Exception:
            pass


class Recorder:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)


@pytest.fixture(autouse=True)
def _k8s_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVALHUB_MODE", "k8s")


def test_local_mode_reports_once_without_drain():
    callbacks = FakeCallbacks(sidecar_url=None)
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks, {"score": 0.5}, drain_seconds=30, sleeper=sleeper
    )

    assert ok is True
    assert callbacks.report_calls == 1
    assert sleeper.sleeps == []


def test_local_mode_skips_drain_even_with_callback_url(monkeypatch: pytest.MonkeyPatch):
    """Smoke jobs set callback_url but EVALHUB_MODE defaults to local."""
    monkeypatch.delenv("EVALHUB_MODE", raising=False)
    callbacks = FakeCallbacks(outcomes=[204])
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks, {"score": 0.5}, drain_seconds=30, retries=3, sleeper=sleeper
    )

    assert ok is True
    assert callbacks.report_calls == 1
    assert sleeper.sleeps == []
    assert callbacks._http_client.calls == 1


def test_success_on_first_attempt_drains():
    callbacks = FakeCallbacks(outcomes=[204])
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks,
        {"score": 0.6},
        drain_seconds=15,
        retries=3,
        sleeper=sleeper,
    )

    assert ok is True
    assert callbacks.report_calls == 1
    assert sleeper.sleeps == [15]
    assert callbacks._http_client.calls == 1


def test_retries_after_failure_then_succeeds():
    callbacks = FakeCallbacks(outcomes=[500, 204])
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks,
        {"score": 0.7},
        drain_seconds=10,
        retries=5,
        backoff_seconds=2.0,
        sleeper=sleeper,
    )

    assert ok is True
    assert callbacks.report_calls == 2
    assert sleeper.sleeps == [2.0, 10]


def test_timeout_then_success():
    callbacks = FakeCallbacks(outcomes=[TimeoutError("timed out"), 204])
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks,
        {"score": 0.8},
        drain_seconds=5,
        retries=3,
        backoff_seconds=1.0,
        sleeper=sleeper,
    )

    assert ok is True
    assert callbacks.report_calls == 2
    assert sleeper.sleeps == [1.0, 5]


def test_conflict_409_counts_as_success():
    callbacks = FakeCallbacks(outcomes=[409])
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks, {"score": 0.9}, drain_seconds=8, retries=3, sleeper=sleeper
    )

    assert ok is True
    assert callbacks.report_calls == 1
    assert sleeper.sleeps == [8]


def test_all_attempts_fail_still_drains():
    callbacks = FakeCallbacks(outcomes=[500, 503, 500])
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks,
        {"score": 0.1},
        drain_seconds=12,
        retries=3,
        backoff_seconds=1.5,
        sleeper=sleeper,
    )

    assert ok is False
    assert callbacks.report_calls == 3
    # backoff for attempts 1 and 2, then drain
    assert sleeper.sleeps == [1.5, 3.0, 12]


def test_exponential_backoff():
    callbacks = FakeCallbacks(outcomes=[500, 500, 204])
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks,
        {"score": 0.2},
        drain_seconds=0,
        retries=3,
        backoff_seconds=2.0,
        sleeper=sleeper,
    )

    assert ok is True
    assert sleeper.sleeps == [2.0, 4.0]


def test_zero_drain_skips_sleep_after_success():
    callbacks = FakeCallbacks(outcomes=[200])
    sleeper = Recorder()

    ok = report_results_and_drain(
        callbacks, {"score": 1.0}, drain_seconds=0, retries=1, sleeper=sleeper
    )

    assert ok is True
    assert sleeper.sleeps == []


def test_sidecar_configured_requires_client_and_url():
    assert sidecar_configured(FakeCallbacks()) is True
    assert sidecar_configured(FakeCallbacks(sidecar_url=None)) is False
    bare = FakeCallbacks()
    bare._http_client = None
    assert sidecar_configured(bare) is False
    no_httpx = FakeCallbacks()
    no_httpx._httpx_available = False
    assert sidecar_configured(no_httpx) is False


def test_k8s_sidecar_mode_requires_k8s_env(monkeypatch: pytest.MonkeyPatch):
    callbacks = FakeCallbacks()
    monkeypatch.setenv("EVALHUB_MODE", "k8s")
    assert k8s_sidecar_mode(callbacks) is True
    monkeypatch.setenv("EVALHUB_MODE", "local")
    assert k8s_sidecar_mode(callbacks) is False
    monkeypatch.delenv("EVALHUB_MODE", raising=False)
    assert k8s_sidecar_mode(callbacks) is False


def test_env_overrides(monkeypatch: pytest.MonkeyPatch):
    callbacks = FakeCallbacks(outcomes=[204])
    sleeper = Recorder()
    monkeypatch.setenv(ENV_DRAIN_SECONDS, "7")
    monkeypatch.setenv(ENV_RETRIES, "2")
    monkeypatch.setenv(ENV_BACKOFF_SECONDS, "0.5")

    ok = report_results_and_drain(callbacks, {"score": 0.3}, sleeper=sleeper)

    assert ok is True
    assert sleeper.sleeps == [7]


def test_invalid_env_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch):
    callbacks = FakeCallbacks(outcomes=[204])
    sleeper = Recorder()
    monkeypatch.setenv(ENV_DRAIN_SECONDS, "nope")

    ok = report_results_and_drain(callbacks, {"score": 0.3}, sleeper=sleeper)

    assert ok is True
    assert sleeper.sleeps == [_mod.DEFAULT_DRAIN_SECONDS]


def test_restores_post_after_exception():
    client = FakeClient(outcomes=[204])
    callbacks = FakeCallbacks(http_client=client)
    original = client.post

    def boom(_seconds: float) -> None:
        raise RuntimeError("drain failed")

    with pytest.raises(RuntimeError, match="drain failed"):
        report_results_and_drain(
            callbacks, {"score": 0.4}, drain_seconds=1, retries=1, sleeper=boom
        )

    assert client.post == original
