"""Assertion dataclasses and evaluation logic for eval cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Assertion:
    """A single check to run against agent output."""

    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssertionResult:
    """Outcome of checking a single assertion."""

    assertion: Assertion
    passed: bool
    detail: str = ""


def check_assertion(
    assertion: Assertion,
    result: Any,
    tool_calls_log: list[str],
) -> AssertionResult:
    """Evaluate one assertion against the agent's output.

    *result* is expected to be a Pydantic model or ``None`` if the agent
    failed.
    """
    atype = assertion.type
    params = assertion.params

    if result is None:
        return AssertionResult(
            assertion=assertion,
            passed=False,
            detail="Agent returned no result",
        )

    if atype == "field_exists":
        fld = params["field"]
        exists = hasattr(result, fld) and getattr(result, fld) is not None
        return AssertionResult(
            assertion=assertion,
            passed=exists,
            detail=f"field '{fld}' {'exists' if exists else 'missing'}",
        )

    if atype == "contains":
        fld = params["field"]
        expected = params["value"]
        actual = str(getattr(result, fld, ""))
        found = expected.lower() in actual.lower()
        return AssertionResult(
            assertion=assertion,
            passed=found,
            detail=(
                f"'{expected}' {'found' if found else 'not found'} "
                f"in {fld} (length {len(actual)})"
            ),
        )

    if atype == "not_contains":
        fld = params["field"]
        unexpected = params["value"]
        actual = str(getattr(result, fld, ""))
        absent = unexpected.lower() not in actual.lower()
        return AssertionResult(
            assertion=assertion,
            passed=absent,
            detail=(
                f"'{unexpected}' {'absent' if absent else 'present'} "
                f"in {fld}"
            ),
        )

    if atype == "field_gte":
        fld = params["field"]
        threshold = float(params["value"])
        actual = float(getattr(result, fld, 0))
        ok = actual >= threshold
        return AssertionResult(
            assertion=assertion,
            passed=ok,
            detail=f"{fld}={actual} {'>=':} {threshold}",
        )

    if atype == "field_lte":
        fld = params["field"]
        threshold = float(params["value"])
        actual = float(getattr(result, fld, 0))
        ok = actual <= threshold
        return AssertionResult(
            assertion=assertion,
            passed=ok,
            detail=f"{fld}={actual} {'<=':} {threshold}",
        )

    if atype == "tool_called":
        tool_name = params["tool"]
        min_calls = int(params.get("min_calls", 1))
        count = tool_calls_log.count(tool_name)
        ok = count >= min_calls
        return AssertionResult(
            assertion=assertion,
            passed=ok,
            detail=(
                f"tool '{tool_name}' called {count} time(s), "
                f"expected >= {min_calls}"
            ),
        )

    if atype == "custom":
        return AssertionResult(
            assertion=assertion,
            passed=False,
            detail=(
                "Custom assertions must be registered via an external "
                "eval harness.  Skipping in the built-in runner."
            ),
        )

    return AssertionResult(
        assertion=assertion,
        passed=False,
        detail=f"Unknown assertion type: {atype}",
    )
