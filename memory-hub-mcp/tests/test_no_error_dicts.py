"""Regression test: no tool may return an error dict (#97, sub-issue 10).

Every MCP tool must raise fastmcp.exceptions.ToolError for failures.
Returning {"error": True, "message": "..."} as a successful MCP response
bypasses the SDK's error handling — the SDK only checks result.is_error,
which dict returns don't set.

This test walks every .py file in src/tools/ and fails if any contains
the literal pattern ``"error": True`` outside of a comment. If this test
fails, the offending tool is returning an error dict instead of raising
ToolError.
"""

import re
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "src" / "tools"

# Match "error": True (with flexible whitespace) that isn't in a comment
ERROR_DICT_PATTERN = re.compile(r'^[^#]*"error"\s*:\s*True', re.MULTILINE)


def test_no_error_dicts_in_tools():
    """No tool file may contain ``"error": True`` as a return value."""
    violations = []
    for py_file in sorted(TOOLS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        text = py_file.read_text()
        matches = ERROR_DICT_PATTERN.findall(text)
        if matches:
            violations.append(
                f"{py_file.name}: {len(matches)} occurrence(s) of '\"error\": True'"
            )

    assert not violations, (
        "Tool files must raise ToolError, not return error dicts. "
        "Violations:\n  " + "\n  ".join(violations)
    )
