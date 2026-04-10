# Scope Isolation: Project and Role

## Problem Statement

Project-scoped and role-scoped memories are visible to any authenticated user regardless of membership. The authz layer (`memory-hub-mcp/src/core/authz.py`) has explicit TBD comments at lines 143 and 152 (read) and 178 (write):

```python
if tier == "project":
    return True  # project membership check TBD
...
if tier == "role":
    return True  # role matching TBD
```

Both `build_authorized_scopes` (line 209) and `_build_search_filters` in the service layer (`src/memoryhub_core/services/memory.py`, line 447) pass project and role scopes through with `None` owner filters, meaning every user with `memory:read:project` or `memory:read:role` sees every project-scoped or role-scoped memory in their tenant. This defeats the purpose of scoped isolation and must be fixed before any production deployment.

Campaign-scoped memories already work correctly. The fix should replicate the proven campaign isolation pattern.

## Reference: Campaign Isolation Pattern

Campaigns are the only non-user, non-org scope with real access control. Here is how the pattern works end to end:

**Schema** (`alembic/versions/009_add_campaigns.py`, `src/memoryhub_core/models/campaign.py`):
- `campaigns` table: id, name, description, status, default_ttl, tenant_id. Unique constraint on (tenant_id, name).
- `campaign_memberships` table: id, campaign_id (FK to campaigns), project_id (VARCHAR), enrolled_at, enrolled_by. Unique constraint on (campaign_id, project_id). Indexes on both campaign_id and project_id.

**Membership resolution** (`src/memoryhub_core/services/campaign.py`):
- `get_campaigns_for_project(session, project_id, tenant_id) -> set[str]` joins campaigns to campaign_memberships, filters by project_id + tenant_id + status='active', returns campaign UUIDs as strings.

**Authorization** (`memory-hub-mcp/src/core/authz.py`):
- `authorize_read`: campaign-scoped memories use `memory.owner_id` as the campaign UUID. The pre-resolved `campaign_ids` set is passed in; read is allowed iff `memory.owner_id in campaign_ids`.
- `authorize_write`: same check -- `owner_id in campaign_ids`.
- The `campaign_ids` parameter is threaded through from the tool layer, not computed inside authz.

**Search filtering** (`src/memoryhub_core/services/memory.py`, lines 425-438):
- In `_build_search_filters`, the `campaign` scope gets a special branch: if `campaign_ids` is non-empty, it adds `AND_(scope == "campaign", owner_id IN campaign_ids)`. If empty/None, campaign scope is skipped entirely (no campaign memories visible).

**MCP tool layer** (`memory-hub-mcp/src/tools/search_memory.py`, lines 344-352; `write_memory.py`, lines 157-169):
- `search_memory` accepts an optional `project_id` parameter. When provided, it calls `get_campaigns_for_project` to resolve campaign_ids, then passes them into the search.
- `write_memory` requires `project_id` when scope is "campaign" and calls the same resolution function. Campaign write authorization checks that the target campaign UUID is in the resolved set.

**Key design properties:**
1. Membership is declarative (a join table row) not implicit.
2. Resolution happens at the tool layer (MCP tools), not deep in the service layer.
3. The service layer receives pre-resolved ID sets and applies them as SQL predicates.
4. Campaign UUID doubles as owner_id on MemoryNode -- no extra column needed on memory_nodes. **Note:** This property is unique to campaigns. For project and role scopes, `owner_id` holds the writing user's identity (not a project/role identifier), so a new `scope_id` column is required. See the project and role designs below.

## Design: Project Scope Isolation

### Schema Changes

New table: `project_memberships`

```sql
CREATE TABLE project_memberships (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id  VARCHAR(255) NOT NULL,    -- the project being joined
    user_id     VARCHAR(255) NOT NULL,    -- the user who is a member
    role        VARCHAR(50)  NOT NULL DEFAULT 'member',  -- member | admin
    joined_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    joined_by   VARCHAR(255) NOT NULL,    -- who performed enrollment
    UNIQUE (project_id, user_id)
);
CREATE INDEX ix_project_memberships_project ON project_memberships (project_id);
CREATE INDEX ix_project_memberships_user    ON project_memberships (user_id);
```

New nullable column on `memory_nodes`: **`scope_id`** (VARCHAR(255), indexed).

**Why a new column is needed:** The existing `owner_id` field does NOT hold a project identifier for project-scoped memories. The `write_memory` tool defaults `owner_id` to `claims["sub"]` (the caller's user ID) for all scopes unless explicitly overridden. Verified against production data -- project-scoped memories have `owner_id = "<user_id>"`, not a project string. This differs from campaign scope, where the tool layer explicitly sets `owner_id` to the campaign UUID.

Rather than adding separate `project_id` and `role_id` columns to `memory_nodes`, a single `scope_id` column serves both scopes (and any future scopes that need a group identifier):

| Scope        | `scope_id` holds           | `owner_id` holds        |
|--------------|----------------------------|-------------------------|
| project      | project identifier string  | user who wrote the memory (attribution) |
| role         | role name string           | user who wrote the memory (attribution) |
| campaign     | NULL (campaigns use `owner_id` for the campaign UUID -- existing pattern, unchanged) | campaign UUID |
| user         | NULL                       | user ID                 |
| organizational | NULL                     | user/service ID         |
| enterprise   | NULL                       | user/service ID         |

```sql
ALTER TABLE memory_nodes ADD COLUMN scope_id VARCHAR(255);
CREATE INDEX ix_memory_nodes_scope_id ON memory_nodes (scope_id);
```

New ORM model: `src/memoryhub_core/models/project.py`

```python
class ProjectMembership(Base):
    __tablename__ = "project_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, ...)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'member'"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), ...)
    joined_by: Mapped[str] = mapped_column(String(255), nullable=False)
```

No separate `projects` table is needed in this phase. Projects are identified by string ID (same as campaign_memberships.project_id). A `projects` table with metadata (name, description, tenant_id) can come later if governance features require it. This keeps the migration minimal.

### Authorization Changes

`memory-hub-mcp/src/core/authz.py`:

`authorize_read` (line 142-143) -- replace the TBD:
```python
if tier == "project":
    if project_ids is None:
        return False
    return memory.scope_id in project_ids
```

`authorize_write` (line 177-178) -- replace the TBD:
```python
if scope == "project":
    if project_ids is None:
        return False
    return scope_id in project_ids
```

Both functions gain a new `project_ids: set[str] | None = None` parameter, threaded from the tool layer in the same way `campaign_ids` is today. The authz check uses `scope_id` (the project identifier on the memory) rather than `owner_id` (which remains the writing user's identity).

`build_authorized_scopes` (lines 204-210): The project scope case must change from `result[tier] = None` (no owner filter) to a sentinel that `_build_search_filters` can act on. Two options:

*Option A (recommended):* Keep `build_authorized_scopes` unchanged (it already returns `None` for project). Instead, handle project filtering in `_build_search_filters` the same way campaigns are handled -- add a special branch that uses a pre-resolved `project_ids` set, filtering on `scope_id` instead of `owner_id`. When `project_ids` is empty/None (i.e., no `project_id` was passed by the caller), project-scoped memories are excluded entirely.

*Option B:* Have `build_authorized_scopes` exclude "project" from the result when no project_ids are available, similar to how campaign scope is skipped.

Option A is recommended because it matches the campaign pattern exactly and keeps `build_authorized_scopes` scope-agnostic. Both options produce the same end behavior given the decision that `project_id` is required for project-scoped memory retrieval (see Open Question 6).

### Search Filtering Changes

`src/memoryhub_core/services/memory.py`, `_build_search_filters` -- add a project branch parallel to the campaign branch (after line 438):

```python
if scope_name == "project":
    if project_ids:
        scope_conditions.append(
            and_(
                MemoryNode.scope == "project",
                MemoryNode.scope_id.in_(project_ids),
            )
        )
    continue
```

The `project_ids` parameter must be threaded through `_build_search_filters`, `search_memories`, `search_memories_with_focus`, and `count_search_matches` -- all of which already accept `campaign_ids` in the same position, so the pattern is well-established. Note that project filtering uses `scope_id` (not `owner_id`), since `owner_id` holds the writing user's identity for project-scoped memories.

### MCP Tool Interface Changes

`search_memory` already accepts `project_id` (used only for campaign resolution today). After this change, `project_id` serves double duty:

1. Resolve campaign memberships (existing behavior).
2. Filter project-scoped memories to the specified project.

**Project-scoped memory retrieval requires `project_id`.** If `project_id` is omitted, project-scoped memories are excluded from results entirely -- the same behavior campaigns use today when `project_id` is absent. This is intentional: the agent's configuration (MCP client config, CLAUDE.md, memoryhub integration rules) should include the project_id value, so the LLM passes a known config value rather than reasoning about which project it is in. The `search_memory` tool description should say: "Pass your configured project_id to include project-scoped memories in results."

When `project_id` is provided, the tool verifies the caller is a member of that project before including project-scoped memories:

New resolution function in `src/memoryhub_core/services/project.py`:
```python
async def get_projects_for_user(
    session: AsyncSession, user_id: str,
) -> set[str]:
    """Return project_ids the user is a member of."""
    stmt = (
        select(ProjectMembership.project_id)
        .where(ProjectMembership.user_id == user_id)
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}
```

In `search_memory`, after resolving campaign_ids, resolve and validate project membership:
```python
project_ids: set[str] | None = None
if project_id:
    session_for_project, gen_for_project = await get_db_session()
    try:
        user_projects = await get_projects_for_user(
            session_for_project, claims["sub"],
        )
    finally:
        await release_db_session(gen_for_project)
    if project_id in user_projects:
        project_ids = {project_id}
    # If the caller is not a member, project_ids stays None
    # and project-scoped memories are excluded.
```

This matches the campaign pattern: the caller explicitly declares the project context per-call, and the tool validates membership before including scoped memories.

`write_memory` with scope="project": the caller must provide a `project_id` parameter (a new tool parameter, distinct from `owner_id`). The tool stores this value as `scope_id` on the memory node. `owner_id` continues to default to `claims["sub"]` (the writing user) for attribution. The tool verifies the caller is a member of the target project before allowing the write:
```python
if scope == "project" and not project_id:
    raise ToolError("scope='project' requires a project_id parameter.")
if scope == "project" and not project_ids:
    raise ToolError("Not a member of any project. ...")
if scope == "project" and project_id not in project_ids:
    raise ToolError(f"Not a member of project '{project_id}'. ...")
# Set scope_id on the memory node
memory_node.scope_id = project_id
```

### Migration Strategy

The migration adds a new `scope_id` column to `memory_nodes`, creates the `project_memberships` table, and backfills existing project-scoped memories in a single automated step.

The Alembic migration includes the backfill SQL as part of the `upgrade()` function:
```sql
UPDATE memory_nodes SET scope_id = 'memory-hub' WHERE scope = 'project' AND scope_id IS NULL;
```
This ensures existing project-scoped memories are visible immediately after migration -- no separate operator action needed. The `owner_id` field on these memories still holds the writing user's ID (not a project identifier), which is correct; `scope_id` now carries the project identifier.

To prevent a disruptive cutover, deploy in two phases:

1. **Phase A (schema + backfill):** Run migration (add `scope_id` column, create `project_memberships` table, backfill existing project-scoped memories with `scope_id = 'memory-hub'`), deploy new code with the authz checks. Add a `MEMORYHUB_PROJECT_ISOLATION_ENABLED` env var (default `false`). When false, fall back to `return True` (current behavior). When true, enforce membership. Create `project_memberships` rows for known users.
2. **Phase B (enable):** Flip the env var to true after verifying memberships are in place.

The feature flag adds a few lines to authz.py and avoids a hard cutover.

## Design: Role Scope Isolation

### Role Identity Model

The codebase has no role-related models, configs, or tables today. The "role" scope exists as a MemoryScope enum value and in ALL_TIERS, but it has no backing identity infrastructure.

Roles should be **flat strings** (e.g., "sre", "data-engineer", "security-reviewer", "architect"). This matches the existing pattern where scope identifiers are simple strings throughout the system (owner_id, project_id are all VARCHAR(255)). Structured role hierarchies (RBAC trees, permission inheritance) add complexity that can be layered on later.

Role sources (decided -- see Open Question 4):

1. **`role_assignments` table**: Declarative, admin-managed, same pattern as project_memberships. Roles exist as rows, not as code.
2. **JWT claims**: The `roles` claim in the JWT token is checked alongside the table. Both sources are merged into a single set by `get_roles_for_user`.

ConfigMap-based roles were considered but rejected -- embedding roles in the users ConfigMap conflates two concerns.

### Schema Changes

New table: `role_assignments`

```sql
CREATE TABLE role_assignments (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     VARCHAR(255) NOT NULL,
    role_name   VARCHAR(100) NOT NULL,
    tenant_id   VARCHAR(255) NOT NULL DEFAULT 'default',
    assigned_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    assigned_by VARCHAR(255) NOT NULL,
    UNIQUE (user_id, role_name, tenant_id)
);
CREATE INDEX ix_role_assignments_user   ON role_assignments (user_id);
CREATE INDEX ix_role_assignments_role   ON role_assignments (role_name);
CREATE INDEX ix_role_assignments_tenant ON role_assignments (tenant_id);
```

Role-scoped memories use the same `scope_id` column added for project scope. For role-scoped memories, `scope_id` holds the role name string (e.g., `scope_id = "sre"`). The `owner_id` remains the writing user's identity (attribution). The authz check verifies the caller holds the role named in `scope_id` via role_assignments.

New ORM model: `src/memoryhub_core/models/role.py`

```python
class RoleAssignment(Base):
    __tablename__ = "role_assignments"

    id: Mapped[uuid.UUID] = mapped_column(...)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("'default'"))
    assigned_at: Mapped[datetime] = mapped_column(...)
    assigned_by: Mapped[str] = mapped_column(String(255), nullable=False)
```

### Authorization Changes

`authorize_read` (line 151-152) -- replace the TBD:
```python
if tier == "role":
    if role_names is None:
        return False
    return memory.scope_id in role_names
```

`authorize_write` (line 175-176) -- keep the service-identity restriction but add role membership check:
```python
if scope == "role":
    if claims.get("identity_type") != "service":
        return False
    if role_names is None:
        return False
    return scope_id in role_names
```

The service-only restriction is intentional (see `docs/governance.md`): role-scoped memories are created by the curator agent promoting patterns it detects across individual user memories, not by direct user writes. This matches the organizational-scope model. The `role_names` check is new — it ensures the service agent can only write to roles it is authorized for, closing the current open-access gap.

Both functions gain `role_names: set[str] | None = None`.

### Search Filtering Changes

Same pattern as project in `_build_search_filters`:

```python
if scope_name == "role":
    if role_names:
        scope_conditions.append(
            and_(
                MemoryNode.scope == "role",
                MemoryNode.scope_id.in_(role_names),
            )
        )
    continue
```

Thread `role_names` through the same functions that already take `campaign_ids` and (after project changes) `project_ids`.

### MCP Tool Interface Changes

New resolution function in `src/memoryhub_core/services/role.py`:
```python
async def get_roles_for_user(
    session: AsyncSession, user_id: str, tenant_id: str,
    claims: dict | None = None,
) -> set[str]:
    """Return role names the user holds in this tenant.

    Merges roles from the role_assignments table with any roles
    present in the JWT claims (claims["roles"]).
    """
    # Source 1: role_assignments table
    stmt = (
        select(RoleAssignment.role_name)
        .where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.tenant_id == tenant_id,
        )
    )
    result = await session.execute(stmt)
    roles = {row[0] for row in result.all()}

    # Source 2: JWT claims
    if claims:
        jwt_roles = claims.get("roles", [])
        if isinstance(jwt_roles, list):
            roles.update(jwt_roles)

    return roles
```

In `search_memory`, resolve alongside project_ids:
```python
role_names = await get_roles_for_user(session, claims["sub"], tenant, claims=claims)
```

For `write_memory` with scope="role": the existing `identity_type == "service"` gate remains (only the curator agent writes role-scoped memories). Additionally, the caller must provide a `role_name` parameter. The tool stores this as `scope_id` on the memory node. The tool verifies the service agent is authorized for the target role:
```python
# identity_type check already handled by authorize_write
if scope == "role" and not role_name:
    raise ToolError("scope='role' requires a role_name parameter.")
if scope == "role" and role_name not in role_names:
    raise ToolError(f"Not authorized for the '{role_name}' role.")
# Set scope_id on the memory node
memory_node.scope_id = role_name
```

### Migration Strategy

Same approach as project -- the Alembic migration handles both schema changes and backfill in a single automated step:

- **Schema:** Create `role_assignments` table. The `scope_id` column on `memory_nodes` is shared with project scope (added once in the same migration).
- **Backfill:** The migration includes a backfill step for any existing role-scoped memories (setting `scope_id` to the appropriate role name). Since the current codebase has role writes restricted to service identities and no known role-scoped memories in production, this backfill is expected to be a no-op, but including it keeps the migration self-contained.

Deploy behind `MEMORYHUB_ROLE_ISOLATION_ENABLED` feature flag (default `false`). Phase A deploys the schema, code, and backfill. Phase B enables the flag after verifying role_assignments are populated (from admin setup or ConfigMap import).

## Implementation Plan

Dependencies flow top-to-bottom; items at the same indent level can be parallelized.

1. **Migration 011: Add scope_id column, project_memberships, role_assignments tables, and backfill** (single Alembic migration)
   - Add `scope_id` column (nullable VARCHAR(255), indexed) to `memory_nodes`
   - Create `project_memberships` table with indexes and constraints
   - Create `role_assignments` table with indexes and constraints
   - Backfill existing project-scoped memories: `UPDATE memory_nodes SET scope_id = 'memory-hub' WHERE scope = 'project' AND scope_id IS NULL`
   - Backfill existing role-scoped memories (expected no-op, but included for completeness)

2. **ORM models** (can parallel with step 3)
   - `src/memoryhub_core/models/project.py` -- ProjectMembership
   - `src/memoryhub_core/models/role.py` -- RoleAssignment
   - Update `src/memoryhub_core/models/__init__.py` to export both

3. **Service layer resolution functions** (can parallel with step 2)
   - `src/memoryhub_core/services/project.py` -- `get_projects_for_user`
   - `src/memoryhub_core/services/role.py` -- `get_roles_for_user`
   - Tests for both

4. **Authz layer changes** (depends on 2, 3)
   - Update `authorize_read` and `authorize_write` signatures to accept `project_ids` and `role_names`
   - Authz checks use `memory.scope_id` (not `owner_id`) for project and role scopes
   - Replace TBD stubs with real checks behind feature flags
   - Update `_build_search_filters` to add project and role branches filtering on `scope_id`
   - Thread new parameters through `search_memories`, `search_memories_with_focus`, `count_search_matches`
   - Update existing authz tests; add new parametric tests for project/role isolation

5. **MCP tool layer changes** (depends on 4)
   - `search_memory.py`: resolve project_ids and role_names from claims, pass to service
   - `write_memory.py`: accept `project_id` param (for scope="project") and `role_name` param (for scope="role"); store as `scope_id` on memory node; validate membership/assignment before write; `owner_id` remains the caller's identity for attribution
   - `read_memory.py`: pass project_ids and role_names for per-row authz (checks against `scope_id`)
   - Update SDK client docstrings if parameter semantics change

6. **Pydantic schemas** (depends on 2)
   - Add `ProjectMembershipCreate`, `ProjectMembershipRead`, `RoleAssignmentCreate`, `RoleAssignmentRead` to schemas.py

7. **Admin tooling** (can follow independently)
   - MCP tools or CLI commands for managing project memberships and role assignments

8. **Feature flag removal** (after validation in staging)
   - Remove `MEMORYHUB_PROJECT_ISOLATION_ENABLED` and `MEMORYHUB_ROLE_ISOLATION_ENABLED`
   - Update tests to assume isolation is always on

## Open Questions

1. **DECIDED: Project writes restricted to project members only.** The caller provides an explicit `project_id` parameter and the tool sets `scope_id` on the memory; `owner_id` stays as the caller for attribution. The authz layer verifies the caller is a member of the target project before allowing the write (as shown in the write_memory validation code above).

2. **DECIDED: Keep service-identity-only restriction for role writes.** This is an intentional governance decision from `docs/governance.md`: role-scoped memories are created by the curator agent promoting patterns it detects across individual user memories, not by direct user writes. The new `role_names` check adds membership verification on top of the existing `identity_type == "service"` gate, closing the open-access gap without changing the write policy.

3. **DECIDED: No `projects` table yet.** Projects remain implicit string IDs in `project_memberships`. A full projects table (id, name, description, tenant_id, created_at) is needed for the UI but not for authz -- a backlog issue will be created to track it separately.

4. **DECIDED: Table + JWT claims.** `get_roles_for_user` checks both the `role_assignments` table AND `claims.get("roles", [])`, merging the results into a single set. This gives immediate admin-managed roles via the table while allowing the OAuth 2.1 auth server to contribute roles via JWT claims as that integration matures.

5. **DECIDED: Automated post-migration backfill.** The Alembic migration itself includes the backfill SQL (`UPDATE memory_nodes SET scope_id = 'memory-hub' WHERE scope = 'project' AND scope_id IS NULL`) as a step within the migration, not as a separate operator guide or manual script. This keeps deployment fully automated and avoids a window where existing project-scoped memories are invisible.

6. **DECIDED: `project_id` required for project-scoped memories.** When the agent wants project-scoped memories, it must pass `project_id`. If `project_id` is omitted, project-scoped memories are excluded from results (same behavior as campaigns today when `project_id` is omitted). The `project_id` value should be part of the agent's configuration (e.g., in the MCP client config, CLAUDE.md, or memoryhub integration rules) so the LLM passes a known config value rather than reasoning about which project it is in. The `search_memory` tool description should guide agents: "Pass your configured project_id to include project-scoped memories in results."
