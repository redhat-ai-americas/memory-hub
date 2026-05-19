"""Obsidian-compatible memory export."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from memoryhub.client import MemoryHubClient

logger = logging.getLogger(__name__)


def _memory_to_markdown(memory: dict, relationships: list[dict] | None = None) -> str:
    """Convert a memory dict to Obsidian-compatible markdown with YAML frontmatter.

    Args:
        memory: Memory dict from client.list() or client.read()
        relationships: Optional list of relationship dicts from get_relationships()

    Returns:
        Markdown string with YAML frontmatter
    """
    # Extract fields
    memory_id = memory.get("id", "unknown")
    scope = memory.get("scope", "user")
    weight = memory.get("weight", 0.7)
    owner_id = memory.get("owner_id", "")
    version = memory.get("version", 1)
    content_type = memory.get("content_type")
    created = memory.get("created_at")
    updated = memory.get("updated_at")
    domains = memory.get("domains") or []
    branch_type = memory.get("branch_type")
    content = memory.get("content", "")

    # Format timestamps
    created_str = created if isinstance(created, str) else (
        created.isoformat() if isinstance(created, datetime) else ""
    )
    updated_str = updated if isinstance(updated, str) else (
        updated.isoformat() if isinstance(updated, datetime) else ""
    )

    # Build tags: scope tag + domain tags + entity tags if applicable
    tags = [f"scope/{scope}"]
    tags.extend(domains)

    # Add entity-specific tags if this is an entity node
    if branch_type and branch_type.startswith("entity:"):
        entity_type = branch_type.removeprefix("entity:")
        tags.append("entity")
        tags.append(f"entity/{entity_type}")

    # Build frontmatter
    frontmatter_lines = [
        "---",
        f"id: {memory_id}",
        f"scope: {scope}",
        f"weight: {weight}",
        f"owner: {owner_id}",
        f"version: {version}",
    ]

    if content_type:
        frontmatter_lines.append(f"content_type: {content_type}")

    if created_str:
        frontmatter_lines.append(f"created: {created_str}")

    if updated_str:
        frontmatter_lines.append(f"updated: {updated_str}")

    # Add domains as YAML list
    if domains:
        frontmatter_lines.append("domains:")
        for domain in domains:
            frontmatter_lines.append(f"  - {domain}")

    # Add tags as YAML list
    frontmatter_lines.append("tags:")
    for tag in tags:
        frontmatter_lines.append(f"  - {tag}")

    frontmatter_lines.append("---")

    # Build the body
    body = content

    # Add relationships section if provided
    if relationships:
        rel_lines = ["\n## Relationships"]
        for rel in relationships:
            source_id = rel.get("source_id", "")
            target_id = rel.get("target_id", "")
            rel_type = rel.get("relationship_type", "related")

            # Create wikilink to the related memory
            # For outgoing edges, link to target; for incoming, link to source
            if str(source_id) == memory_id:
                # Outgoing relationship
                rel_lines.append(f"- [[{target_id}]] ({rel_type})")
            else:
                # Incoming relationship
                rel_lines.append(f"- [[{source_id}]] ({rel_type})")

        body += "\n".join(rel_lines)

    return "\n".join(frontmatter_lines) + "\n\n" + body


def _generate_obsidian_config(output_dir: Path, scopes: set[str]) -> None:
    """Generate .obsidian/graph.json with color groups for different scopes.

    Args:
        output_dir: Root directory of the Obsidian vault
        scopes: Set of scope strings found in exported memories
    """
    obsidian_dir = output_dir / ".obsidian"
    obsidian_dir.mkdir(parents=True, exist_ok=True)

    # Color palette for scope tags
    scope_colors = {
        "user": "#4A90E2",       # Blue
        "project": "#50C878",    # Green
        "organizational": "#F5A623",  # Orange
        "enterprise": "#D0021B",  # Red
        "role": "#9013FE",       # Purple
        "campaign": "#BD10E0",   # Magenta
    }

    # Build color groups for the graph view
    color_groups = []
    for scope in sorted(scopes):
        color = scope_colors.get(scope, "#8B572A")  # Default to brown
        color_groups.append({
            "query": f"tag:#scope/{scope}",
            "color": {"a": 1, "rgb": int(color.lstrip("#"), 16)}
        })

    graph_config = {
        "collapse-filter": True,
        "search": "",
        "localGraph": {
            "collapse-filter": True,
            "search": "",
            "localJumps": 1,
            "localBacklinks": True,
            "localForelinks": True,
            "localInterlinks": False,
            "showTags": True,
            "showAttachments": False,
            "hideUnresolved": False,
            "collapse-color-groups": False,
            "colorGroups": color_groups,
            "collapse-display": True,
            "showArrow": True,
            "textFadeMultiplier": 0,
            "nodeSizeMultiplier": 1,
            "lineSizeMultiplier": 1,
            "collapse-forces": True,
            "centerStrength": 0.518713248970312,
            "repelStrength": 10,
            "linkStrength": 1,
            "linkDistance": 250,
            "scale": 1,
            "close": False
        },
        "collapse-color-groups": False,
        "colorGroups": color_groups,
        "collapse-display": True,
        "showArrow": True,
        "textFadeMultiplier": 0,
        "nodeSizeMultiplier": 1,
        "lineSizeMultiplier": 1,
        "collapse-forces": True,
        "centerStrength": 0.518713248970312,
        "repelStrength": 10,
        "linkStrength": 1,
        "linkDistance": 250,
        "scale": 1
    }

    graph_path = obsidian_dir / "graph.json"
    with graph_path.open("w") as f:
        json.dump(graph_config, f, indent=2)

    logger.info("Generated Obsidian graph config at %s", graph_path)


async def export_obsidian(
    client: MemoryHubClient,
    output_dir: str | Path,
    *,
    scope: str | None = None,
    project_id: str | None = None,
    include_branches: bool = False,
    weight_threshold: float = 0.0,
) -> dict[str, Any]:
    """Export memories to Obsidian-compatible markdown files.

    Creates a directory structure with markdown files for each memory,
    complete with YAML frontmatter, wikilinks for relationships, and
    Obsidian graph configuration.

    Args:
        client: Connected MemoryHubClient instance
        output_dir: Path to output directory (created if needed)
        scope: Filter by scope (user, project, etc.)
        project_id: Project identifier for project-scoped memories
        include_branches: If True, include branch memories
        weight_threshold: Minimum weight to export (default 0.0)

    Returns:
        Summary dict with files_written, output_dir, scopes, errors
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Paginate through all memories
    cursor = None
    all_memories = []
    scopes_seen: set[str] = set()
    errors: list[dict[str, str]] = []

    logger.info("Fetching memories from MemoryHub...")

    while True:
        try:
            result = await client.list(
                scope=scope,
                project_id=project_id,
                include_branches=include_branches,
                cursor=cursor,
                max_results=100,
            )
        except Exception as exc:
            error_msg = f"Failed to list memories: {exc}"
            logger.error(error_msg)
            errors.append({"type": "list_error", "message": str(exc)})
            break

        memories = result.get("results", [])
        all_memories.extend(memories)

        if not result.get("has_more"):
            break

        cursor = result.get("next_cursor")
        if not cursor:
            break

    logger.info("Fetched %d memories", len(all_memories))

    # Filter by weight threshold
    if weight_threshold > 0.0:
        filtered = [m for m in all_memories if m.get("weight", 0.0) >= weight_threshold]
        logger.info(
            "Filtered %d/%d memories with weight >= %.2f",
            len(filtered),
            len(all_memories),
            weight_threshold,
        )
        all_memories = filtered

    # Export each memory
    files_written = 0

    for memory in all_memories:
        memory_id = memory.get("id")
        memory_scope = memory.get("scope", "user")
        scopes_seen.add(memory_scope)

        if not memory_id:
            errors.append({"type": "missing_id", "message": "Memory missing ID field"})
            continue

        # Try to fetch relationships for this memory
        relationships = None
        try:
            rel_result = await client.get_relationships(
                memory_id,
                project_id=project_id,
            )
            relationships = rel_result.relationships if hasattr(rel_result, "relationships") else []
        except Exception as exc:
            # Not all memories have relationships, that's okay
            logger.debug("Could not fetch relationships for %s: %s", memory_id, exc)

        # Convert to markdown
        try:
            markdown = _memory_to_markdown(memory, relationships)
        except Exception as exc:
            errors.append({
                "type": "markdown_conversion",
                "memory_id": memory_id,
                "message": str(exc),
            })
            continue

        # Write to scope-organized directory
        scope_dir = output_path / memory_scope
        scope_dir.mkdir(parents=True, exist_ok=True)

        file_path = scope_dir / f"{memory_id}.md"
        try:
            file_path.write_text(markdown, encoding="utf-8")
            files_written += 1
        except Exception as exc:
            errors.append({
                "type": "file_write",
                "memory_id": memory_id,
                "path": str(file_path),
                "message": str(exc),
            })

    # Generate Obsidian config
    try:
        _generate_obsidian_config(output_path, scopes_seen)
    except Exception as exc:
        errors.append({
            "type": "obsidian_config",
            "message": str(exc),
        })

    logger.info("Export complete: %d files written to %s", files_written, output_path)

    return {
        "files_written": files_written,
        "output_dir": str(output_path),
        "scopes": sorted(scopes_seen),
        "errors": errors,
    }
