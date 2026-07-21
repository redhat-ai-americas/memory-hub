#!/usr/bin/env python3
"""Seed MemoryHub with sample data so the admin UI has content to display.

Usage:
    # Uses MCP_URL env var or prompts; reads API key from ~/.config/memoryhub/api-key
    python scripts/seed-sample-data.py

    # Explicit URL and key
    python scripts/seed-sample-data.py --url https://memory-hub-mcp-....apps.example.com/mcp/ --api-key mh-dev-abc123

    # Skip if data already exists
    python scripts/seed-sample-data.py --skip-if-exists

Requires: pip install memoryhub
"""
import argparse
import asyncio
import sys
from pathlib import Path

try:
    from memoryhub import MemoryHubClient
except ImportError:
    print("Error: memoryhub SDK not installed. Run: pip install memoryhub")
    sys.exit(1)


PROJECT_ID = "sample-project"
MEMORIES = [
    # (content, scope, weight, content_type, project_id)
    (
        "Use FastAPI over Flask for all new Python web services. FastAPI provides "
        "built-in async support, automatic OpenAPI documentation, and Pydantic "
        "validation that eliminates an entire class of bugs.",
        "user", 0.9, "knowledge", None,
    ),
    (
        "PostgreSQL with pgvector handles relational, vector, and lightweight "
        "graph queries in a single database. This avoids the operational overhead "
        "of running separate vector and graph databases for most workloads.",
        "user", 0.85, "knowledge", None,
    ),
    (
        "When building containers for OpenShift on a Mac, always specify "
        "--platform linux/amd64 to avoid architecture mismatches. The cluster "
        "runs x86_64; ARM images will crash with exec format errors.",
        "user", 0.95, "knowledge", None,
    ),
    (
        "Red Hat UBI base images are required for all container builds in "
        "regulated environments. They include FIPS-validated crypto modules "
        "and receive CVE patches on Red Hat's security SLA.",
        "project", 0.9, "knowledge", PROJECT_ID,
    ),
    (
        "The embedding model (all-MiniLM-L6-v2) runs on CPU and returns "
        "384-dimensional vectors. It handles up to 256 tokens per input. "
        "For longer documents, chunk at paragraph boundaries.",
        "project", 0.8, "knowledge", PROJECT_ID,
    ),
    (
        "Agent memory retrieval uses two-vector RRF: the query vector finds "
        "semantically relevant memories, and the session focus vector biases "
        "results toward the current work context. Cross-encoder reranking "
        "runs as a second pass for precision.",
        "project", 0.85, "knowledge", PROJECT_ID,
    ),
    (
        "Deploy database schema changes through Alembic migrations, never "
        "through create_all(). Alembic handles column additions and type "
        "changes on existing tables; create_all() silently skips them.",
        "project", 0.9, "knowledge", PROJECT_ID,
    ),
    (
        "The MCP server exposes three tool profiles: compact (4 action-dispatch "
        "tools, default), full (13 individual tools), and minimal (5 tools). "
        "Most agents should use compact -- it reduces tool-selection overhead "
        "while keeping the full API surface available through action parameters.",
        "project", 0.8, "knowledge", PROJECT_ID,
    ),
    (
        "OAuth 2.1 client_credentials flow is the production auth path. API "
        "keys (mh-dev-<hex>) are the developer convenience path. Both issue "
        "JWTs validated against the auth server's JWKS endpoint. Start with "
        "API keys; move to OAuth when you need automatic token refresh.",
        "user", 0.75, "experiential", None,
    ),
    (
        "MinIO provides S3-compatible object storage for large memory content. "
        "Memories under 4KB are stored inline in PostgreSQL; larger content "
        "is stored in MinIO with a reference pointer in the database row.",
        "project", 0.7, "knowledge", PROJECT_ID,
    ),
]


async def main():
    parser = argparse.ArgumentParser(description="Seed MemoryHub with sample data")
    parser.add_argument("--url", help="MCP server URL (or set MCP_URL env var)")
    parser.add_argument("--api-key", help="API key (or store at ~/.config/memoryhub/api-key)")
    parser.add_argument("--skip-if-exists", action="store_true",
                        help="Skip seeding if memories already exist")
    args = parser.parse_args()

    url = args.url
    if not url:
        import os
        url = os.environ.get("MCP_URL")
    if not url:
        print("Error: provide --url or set MCP_URL environment variable")
        sys.exit(1)

    api_key = args.api_key
    if not api_key:
        key_path = Path.home() / ".config/memoryhub/api-key"
        if key_path.exists():
            api_key = key_path.read_text().strip()
        else:
            print(f"Error: provide --api-key or store key at {key_path}")
            sys.exit(1)

    client = MemoryHubClient(url=url, api_key=api_key)

    async with client:
        session = await client.get_session()
        print(f"Authenticated as {session.get('user_id', 'unknown')}")

        if args.skip_if_exists:
            existing = await client.search("sample seed data check", max_results=1)
            if existing.results:
                print("Memories already exist -- skipping (use without --skip-if-exists to add more)")
                return

        # Create the sample project
        try:
            await client._call_action("create_project", project_id=PROJECT_ID)
            print(f"Created project: {PROJECT_ID}")
        except Exception:
            print(f"Project '{PROJECT_ID}' already exists -- continuing")

        # Write memories
        memory_ids = []
        for i, (content, scope, weight, content_type, project_id) in enumerate(MEMORIES, 1):
            try:
                result = await client.write(
                    content=content,
                    scope=scope,
                    weight=weight,
                    content_type=content_type,
                    project_id=project_id,
                )
                if result.memory:
                    memory_ids.append(result.memory.id)
                    print(f"  [{i}/{len(MEMORIES)}] Written: {content[:60]}...")
                else:
                    print(f"  [{i}/{len(MEMORIES)}] Blocked by curation: {content[:40]}...")
            except Exception as e:
                print(f"  [{i}/{len(MEMORIES)}] Error: {e}")

        # Create a relationship between two project memories
        if len(memory_ids) >= 6:
            try:
                await client._call_action(
                    "relate",
                    options={
                        "source_id": memory_ids[4],
                        "target_id": memory_ids[5],
                        "relationship_type": "related_to",
                    },
                )
                print("  Created relationship: embedding model -> two-vector retrieval")
            except Exception as e:
                print(f"  Relationship error: {e}")

        if len(memory_ids) >= 8:
            try:
                await client._call_action(
                    "relate",
                    options={
                        "source_id": memory_ids[6],
                        "target_id": memory_ids[7],
                        "relationship_type": "related_to",
                    },
                )
                print("  Created relationship: alembic migrations -> MCP server profiles")
            except Exception as e:
                print(f"  Relationship error: {e}")

        print(f"\nSeeded {len(memory_ids)} memories across user and project scopes.")
        print("Open the MemoryHub dashboard to see them in the Memory Graph panel.")


if __name__ == "__main__":
    asyncio.run(main())
