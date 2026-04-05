#!/usr/bin/env python3
"""Seed initial OAuth clients from the existing users ConfigMap data.

Run after migration 006 has been applied:
    python scripts/seed-oauth-clients.py

Requires:
  - MEMORYHUB_DB_* env vars or defaults to localhost
  - SEED_CLIENTS_JSON env var OR a clients.json file path as first arg

Example clients.json:
  [
    {
      "client_id": "wjackson",
      "client_secret": "your-secret-here",
      "client_name": "William Jackson",
      "identity_type": "user",
      "tenant_id": "default",
      "default_scopes": ["memory:read", "memory:write:user"]
    }
  ]

Idempotent — skips clients that already exist.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import bcrypt

# Add repo root to path so we can import memoryhub
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memoryhub.config import DatabaseSettings  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _load_clients() -> list[dict]:
    """Load client definitions from env var, file arg, or default file."""
    # Priority 1: JSON from env var
    raw = os.getenv("SEED_CLIENTS_JSON")
    if raw:
        return json.loads(raw)

    # Priority 2: file path as CLI arg
    if len(sys.argv) > 1:
        return json.loads(Path(sys.argv[1]).read_text())

    # Priority 3: default file next to this script
    default = Path(__file__).parent / "seed-clients.json"
    if default.exists():
        return json.loads(default.read_text())

    print("ERROR: No client data found.")
    print("  Set SEED_CLIENTS_JSON env var, pass a JSON file path, or create scripts/seed-clients.json")
    sys.exit(1)


async def seed_clients():
    clients = _load_clients()
    db = DatabaseSettings()
    engine = create_async_engine(db.async_url, echo=False)

    async with engine.begin() as conn:
        for client in clients:
            # Check if client already exists
            result = await conn.execute(
                text("SELECT client_id FROM oauth_clients WHERE client_id = :cid"),
                {"cid": client["client_id"]},
            )
            if result.fetchone():
                print(f"  skip: {client['client_id']} (already exists)")
                continue

            secret_hash = bcrypt.hashpw(
                client["client_secret"].encode(), bcrypt.gensalt()
            ).decode()

            # Use CAST function instead of :: operator for jsonb conversion
            scopes_json = json.dumps(client["default_scopes"])
            await conn.execute(
                text("""
                    INSERT INTO oauth_clients
                        (id, client_id, client_secret_hash, client_name,
                         identity_type, tenant_id, default_scopes, active)
                    VALUES
                        (uuid_generate_v4(), :client_id, :secret_hash, :client_name,
                         :identity_type, :tenant_id, CAST(:scopes AS jsonb), true)
                """),
                {
                    "client_id": client["client_id"],
                    "secret_hash": secret_hash,
                    "client_name": client["client_name"],
                    "identity_type": client["identity_type"],
                    "tenant_id": client["tenant_id"],
                    "scopes": scopes_json,
                },
            )
            print(f"  created: {client['client_id']} ({client['identity_type']})")

    await engine.dispose()
    print("\nDone.")


if __name__ == "__main__":
    print("Seeding OAuth clients...")
    asyncio.run(seed_clients())
