#!/usr/bin/env python3
"""Manage project memberships and role assignments.

Run with port-forwarding to the cluster DB (same as run-migrations.sh):

    MEMORYHUB_DB_PASSWORD=... python scripts/manage-memberships.py <command> [args]

Commands:
    list-projects                    List all project memberships
    add-project  <project> <user>    Add user to project (--role admin|member)
    remove-project <project> <user>  Remove user from project

    list-roles                       List all role assignments
    add-role  <role> <user>          Assign role to user (--tenant default)
    remove-role <role> <user>        Remove role from user (--tenant default)

Idempotent — add operations skip if the row already exists.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memoryhub_core.config import DatabaseSettings  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy import text  # noqa: E402


async def list_projects(engine):
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT project_id, user_id, role, joined_at, joined_by FROM project_memberships ORDER BY project_id, user_id")
        )
        rows = result.fetchall()
        if not rows:
            print("  (no project memberships)")
            return
        print(f"  {'PROJECT':<25} {'USER':<20} {'ROLE':<10} {'JOINED':<22} {'BY'}")
        print(f"  {'-'*25} {'-'*20} {'-'*10} {'-'*22} {'-'*15}")
        for r in rows:
            joined = r[3].strftime("%Y-%m-%d %H:%M") if r[3] else ""
            print(f"  {r[0]:<25} {r[1]:<20} {r[2]:<10} {joined:<22} {r[4]}")


async def add_project(engine, project_id: str, user_id: str, role: str, actor: str):
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT id FROM project_memberships WHERE project_id = :pid AND user_id = :uid"),
            {"pid": project_id, "uid": user_id},
        )
        if result.fetchone():
            print(f"  skip: {user_id} already a member of {project_id}")
            return
        await conn.execute(
            text("""
                INSERT INTO project_memberships (id, project_id, user_id, role, joined_by)
                VALUES (uuid_generate_v4(), :pid, :uid, :role, :actor)
            """),
            {"pid": project_id, "uid": user_id, "role": role, "actor": actor},
        )
        print(f"  added: {user_id} -> {project_id} (role={role})")


async def remove_project(engine, project_id: str, user_id: str):
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM project_memberships WHERE project_id = :pid AND user_id = :uid"),
            {"pid": project_id, "uid": user_id},
        )
        if result.rowcount == 0:
            print(f"  skip: {user_id} is not a member of {project_id}")
        else:
            print(f"  removed: {user_id} from {project_id}")


async def list_roles(engine):
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT role_name, user_id, tenant_id, assigned_at, assigned_by FROM role_assignments ORDER BY role_name, user_id")
        )
        rows = result.fetchall()
        if not rows:
            print("  (no role assignments)")
            return
        print(f"  {'ROLE':<25} {'USER':<20} {'TENANT':<15} {'ASSIGNED':<22} {'BY'}")
        print(f"  {'-'*25} {'-'*20} {'-'*15} {'-'*22} {'-'*15}")
        for r in rows:
            assigned = r[3].strftime("%Y-%m-%d %H:%M") if r[3] else ""
            print(f"  {r[0]:<25} {r[1]:<20} {r[2]:<15} {assigned:<22} {r[4]}")


async def add_role(engine, role_name: str, user_id: str, tenant_id: str, actor: str):
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT id FROM role_assignments WHERE user_id = :uid AND role_name = :rn AND tenant_id = :tid"),
            {"uid": user_id, "rn": role_name, "tid": tenant_id},
        )
        if result.fetchone():
            print(f"  skip: {user_id} already holds role {role_name} in tenant {tenant_id}")
            return
        await conn.execute(
            text("""
                INSERT INTO role_assignments (id, user_id, role_name, tenant_id, assigned_by)
                VALUES (uuid_generate_v4(), :uid, :rn, :tid, :actor)
            """),
            {"uid": user_id, "rn": role_name, "tid": tenant_id, "actor": actor},
        )
        print(f"  assigned: {user_id} -> {role_name} (tenant={tenant_id})")


async def remove_role(engine, role_name: str, user_id: str, tenant_id: str):
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM role_assignments WHERE user_id = :uid AND role_name = :rn AND tenant_id = :tid"),
            {"uid": user_id, "rn": role_name, "tid": tenant_id},
        )
        if result.rowcount == 0:
            print(f"  skip: {user_id} does not hold role {role_name} in tenant {tenant_id}")
        else:
            print(f"  removed: {role_name} from {user_id} (tenant={tenant_id})")


async def main():
    parser = argparse.ArgumentParser(description="Manage project memberships and role assignments")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-projects", help="List all project memberships")

    ap = sub.add_parser("add-project", help="Add user to project")
    ap.add_argument("project_id")
    ap.add_argument("user_id")
    ap.add_argument("--role", default="member", choices=["member", "admin"])
    ap.add_argument("--actor", default="admin", help="Who is performing this action")

    rp = sub.add_parser("remove-project", help="Remove user from project")
    rp.add_argument("project_id")
    rp.add_argument("user_id")

    sub.add_parser("list-roles", help="List all role assignments")

    ar = sub.add_parser("add-role", help="Assign role to user")
    ar.add_argument("role_name")
    ar.add_argument("user_id")
    ar.add_argument("--tenant", default="default")
    ar.add_argument("--actor", default="admin", help="Who is performing this action")

    rr = sub.add_parser("remove-role", help="Remove role from user")
    rr.add_argument("role_name")
    rr.add_argument("user_id")
    rr.add_argument("--tenant", default="default")

    args = parser.parse_args()

    db = DatabaseSettings()
    engine = create_async_engine(db.async_url, echo=False)

    try:
        if args.command == "list-projects":
            await list_projects(engine)
        elif args.command == "add-project":
            await add_project(engine, args.project_id, args.user_id, args.role, args.actor)
        elif args.command == "remove-project":
            await remove_project(engine, args.project_id, args.user_id)
        elif args.command == "list-roles":
            await list_roles(engine)
        elif args.command == "add-role":
            await add_role(engine, args.role_name, args.user_id, args.tenant, args.actor)
        elif args.command == "remove-role":
            await remove_role(engine, args.role_name, args.user_id, args.tenant)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
