"""Utility functions for memory models."""

STUB_CONTENT_LIMIT = 200


def generate_stub(
    content: str,
    scope: str,
    weight: float,
    branch_count: int,
    has_rationale: bool,
) -> str:
    """Generate a lightweight stub string for a memory node.

    The stub is the first 200 characters of content plus metadata summary.
    Used for lightweight injection into agent context windows.

    Args:
        content: The full memory content text.
        scope: The memory scope (user, project, role, organizational, enterprise).
        weight: The injection weight (0.0-1.0).
        branch_count: Number of child branches.
        has_rationale: Whether the node has a rationale branch.

    Returns:
        A stub string suitable for compact context injection.
    """
    truncated = content[:STUB_CONTENT_LIMIT]
    rationale_str = "yes" if has_rationale else "no"
    return f"{truncated} [scope={scope}, weight={weight}, branches={branch_count}, rationale={rationale_str}]"
