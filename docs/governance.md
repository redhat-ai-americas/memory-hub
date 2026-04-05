# Governance and Compliance

Governance is what separates MemoryHub from "just another vector store with an API." Every memory operation flows through the governance engine, which enforces access control, logs immutably, and applies policy rules. This isn't optional infrastructure -- it's the core value proposition for enterprise adoption.

## Access Control Tiers

Access control is metadata-driven, not ACL-based. The memory's scope, the actor's identity, and the operation type determine whether an action is permitted. There are no per-record permission lists to manage.

### User-scope memories

Fully automatic creation and update. The agent writes memories on behalf of its user without any approval flow. Only the owning user can hand-edit their memories -- no other user, no admin, no agent acting on behalf of another user. This is a security property: if someone else could modify your memories, they could change how your agent behaves and make you appear responsible for the outcome. The governance engine enforces this at the write path. Reads of user memories are restricted to the owning user's agents.

### Project-scope memories

Any agent working within the project context can read and write project memories. The "working within" determination comes from the agent's project context (passed in the MCP request). Automatic creation, no approval required, but all operations are logged and auditable. Project owners can review and modify project memories.

### Role-scope memories

Readable by all agents whose users hold the specified role. Writable only by the curator agent (which detects role-level patterns and promotes individual memories). Role assignment comes from the platform identity system (OpenShift OAuth / RBAC). Auditable, modifiable by role administrators.

### Organizational-scope memories

Readable by all agents in the organization. Writable only by the curator agent after pattern detection and (optionally) human approval. These represent collective organizational knowledge. All operations are auditable, and authorized administrators can modify or retire organizational memories.

### Enterprise/policy-scope memories

Readable by all agents. Writable only with explicit human-in-the-loop approval. These are mandated rules, not detected patterns. Creation and modification require a designated approver to sign off. The governance engine blocks any attempt to write enterprise memories without the approval workflow completing. This is the one scope where automation is not the default.

## Immutable Audit Trail

Every memory operation -- create, read, update, promote, prune, search -- gets an immutable audit log entry. "Immutable" means append-only: entries cannot be modified or deleted, even by administrators. The log is the authoritative record of what happened.

Each audit entry includes: operation type, target memory ID, actor identity (user + agent), timestamp, the memory's state before the operation (for writes), the memory's state after the operation (for writes), and the governance decision (permitted/denied, with reason).

The audit trail is stored in PostgreSQL in a dedicated table with appropriate access controls. It is not stored alongside the memory data in a way that memory access could bypass the audit. The table should use PostgreSQL's built-in row-level security or a separate database role with append-only permissions.

### Audit log at scale

A high-volume deployment generates a lot of audit data. An agent that reads memories on every conversational turn, across hundreds of conversations per day, creates many read log entries. This is a known cost.

The approach will likely involve tiered detail levels: writes and governance decisions always get full-detail entries; reads might get batched or sampled entries depending on configuration. The curator's periodic scans get summary entries rather than per-node entries. Retention policy is configurable via CRD -- full detail for recent history, aggregated summaries for older data.

## Memory Forensics

Forensics is the capability to reconstruct exactly what an agent knew at any point in time. This requires two things: the version history of every memory (provided by the `isCurrent` model) and the audit trail showing which memories were served to which agents at which times.

Forensic queries look like: "What memories were in agent X's context during conversation Y on March 15th?" The answer comes from correlating the audit trail's read entries with the version history of each memory read. If memory M was version 3 on March 15th, and the audit trail shows agent X read memory M at 2:30 PM, then version 3 is what the agent saw.

This capability matters for incident investigation. "Did the agent release source code because the user asked it to, or because a memory was incorrectly configured?" is a question with legal and compliance implications. MemoryHub can answer it.

## FIPS Compliance

MemoryHub's FIPS compliance strategy is "delegate crypto to the platform."

PostgreSQL delegates all cryptographic operations to the OS-level OpenSSL library. On FIPS-enabled RHEL/RHCOS (which OpenShift runs on), that OpenSSL is FIPS 140-2 validated. PostgreSQL uses SCRAM-SHA-256 for authentication (default since PG 14) which works in FIPS mode, unlike the older MD5 authentication. pgvector uses mathematical distance computations -- floating-point arithmetic, not crypto -- so it's unaffected by FIPS restrictions.

MinIO AIStor supports FIPS 140-3 mode via Go 1.24's validated crypto module. In FIPS mode, TLS uses only AES-GCM cipher suites, and data-at-rest encryption uses AES-256-GCM exclusively.

All MemoryHub containers use Red Hat UBI9 base images, which include FIPS-validated crypto libraries when running on a FIPS-enabled cluster.

The MCP server (Python / FastAPI) uses the system's OpenSSL for TLS. Python's `ssl` module delegates to OpenSSL, so FIPS mode is inherited from the OS.

There are no components in the stack that implement their own cryptography. This is by design -- using OS-provided FIPS modules is the most defensible compliance posture.

## Secrets and PII Detection

Secrets scanning runs at two points: inline at write time (the MCP server checks content before persisting) and in batch by the curator agent (periodic full scans catch secrets that weren't caught at write time, or that became concerning after the fact).

Detection categories:
- API keys and tokens (common formats: AWS, GCP, Azure, GitHub, etc.)
- Passwords and connection strings
- Private keys (SSH, TLS)
- PII: email addresses, phone numbers, SSNs, credit card numbers

When a secret or PII is detected, the governance engine can take one of several actions (configurable by policy):
- Flag and alert (allow storage but notify administrators)
- Quarantine (remove from active retrieval until reviewed)
- Block (reject the write entirely)

False positives are inevitable. A memory about "how to configure API key rotation" isn't a leaked key, but it mentions "API key" in a context that looks like a secret. Users need a way to review flags and whitelist specific memories. The whitelisting itself gets an audit log entry.

## Policy Enforcement

Enterprise policies about what can and cannot be stored in memory are expressed as MemoryPolicy CRDs (see [operator.md](operator.md)) and enforced by the governance engine.

Example policies:
- "No source code in memories" -- content scanning for code patterns
- "PII must be flagged within 24 hours" -- SLA on detection
- "Organizational memories require provenance" -- structural requirement
- "Maximum 5 enterprise memories per month" -- rate limiting on high-governance scope

Policy evaluation happens at write time (synchronous, in the request path) and during curator scans (asynchronous, for policies that require cross-memory analysis).

## The Attribution Problem

One of the more subtle governance challenges: preventing memory tampering to frame users. If agent memories influence agent behavior, and agent behavior has real consequences (code pushed, data accessed, systems modified), then whoever controls the memories controls the outcome. If someone could plant a memory in another user's scope ("user prefers to commit without code review"), the agent would act on it, and the user would appear to have authorized the behavior.

MemoryHub's defense is layered:

1. User-scope memories can only be written by the user's own agents. No cross-user writes.
2. All writes are audit-logged with actor identity. The provenance of every memory is traceable.
3. The `isCurrent` version model means even if a memory is tampered with, the version history shows the change and who made it.
4. Enterprise/policy memories require human approval, preventing automated injection of high-authority memories.

This doesn't make tampering impossible -- someone with database access could modify records directly. But it makes tampering detectable, which is the practical standard for enterprise compliance.

## EU AI Act Considerations

The EU AI Act enforcement begins August 2026. While MemoryHub isn't an AI system itself (it's infrastructure), it supports compliance for AI systems that use it:

**Transparency**: the audit trail and memory forensics provide the record of what influenced AI decisions. When regulators ask "why did the AI system do X?", the memory state at decision time is part of the answer.

**Human oversight**: the HITL requirement for enterprise/policy memories, plus the audit capability for all tiers, provides the oversight mechanism regulators expect.

**Data governance**: scope-based access control, PII detection, and policy enforcement align with the Act's requirements for data quality and governance in AI systems.

MemoryHub doesn't solve AI Act compliance on its own, but it provides infrastructure that makes compliance achievable. Without something like it, answering regulatory questions about AI decision-making is guesswork.

## Implementation Design

### Enforcement Architecture

Scope enforcement happens at two layers: the infrastructure layer (Authorino) and the service layer (MCP server). Authorino handles authentication — validating that the caller is who they claim to be. The MCP server handles authorization — deciding whether the authenticated caller can perform the requested operation on the target memory.

This separation is deliberate. Authentication is generic infrastructure that belongs at the route level. Authorization requires domain knowledge (memory scopes, ownership rules) that only the application can evaluate.

#### Current state (Phase 2)

The MCP server's `auth.py` provides session-based API key authentication. `register_session` validates a key against a users ConfigMap and stores the identity in process-local state. Individual tools call `require_auth()` or `get_authenticated_owner()` to retrieve the identity.

Enforcement is inconsistent across tools:

| Tool | Auth required | Owner filtering | Scope check |
|------|--------------|----------------|-------------|
| `write_memory` | Yes (if owner_id omitted) | User-scope: must match self | `has_scope` check |
| `search_memory` | No | Defaults to self, but caller can override | None |
| `read_memory` | No | None — UUID lookup only | None |
| `get_similar_memories` | Yes | Implicit (source node's owner) | None |
| `get_relationships` | Yes | None | None |

The gaps are significant: `read_memory` has zero enforcement, `search_memory` accepts arbitrary `owner_id` values, and `write_memory` can be bypassed by passing an explicit `owner_id` without a session.

#### Target state

Every tool that touches memory data must:

1. **Require authentication.** Call `require_auth()` unconditionally. No unauthenticated access to any memory operation.
2. **Enforce ownership on reads.** `search_memory` must filter results to memories the caller is authorized to see. `read_memory` must verify the caller has access to the memory's scope before returning content.
3. **Enforce ownership on writes.** `write_memory` must always validate scope access, regardless of whether `owner_id` is explicitly passed.
4. **Filter cross-references.** `get_similar_memories` and `get_relationships` must not leak memories the caller can't access.

The enforcement logic belongs in a shared authorization function, not duplicated per-tool:

```python
def authorize_read(user_claims: dict, memory: MemoryNode) -> bool:
    """Can this JWT bearer read this memory?"""
    scopes = user_claims.get("scopes", [])
    # Tenant isolation: always enforced
    if memory.tenant_id != user_claims.get("tenant_id"):
        return False
    # Check operational scope
    tier = memory.scope  # e.g., "user", "organizational"
    if f"memory:read:{tier}" in scopes or "memory:read" in scopes:
        # Tier-level policy
        if tier == "user":
            return memory.owner_id == user_claims["sub"]
        if tier in ("enterprise", "organizational"):
            return True  # all authenticated agents can read
        if tier == "project":
            return True  # project membership check TBD
        if tier == "role":
            # TODO: match memory's role tag against user's roles
            return True
    return False

def authorize_write(user_claims: dict, scope: str, owner_id: str) -> bool:
    """Can this JWT bearer write a memory at this scope for this owner?"""
    scopes = user_claims.get("scopes", [])
    if f"memory:write:{scope}" not in scopes and "memory:write" not in scopes:
        return False
    if scope == "user":
        return owner_id == user_claims["sub"]
    if scope == "enterprise":
        return False  # always rejected here; HITL approval flow bypasses this check
    if scope in ("organizational", "role"):
        return user_claims.get("identity_type") == "service"
    if scope == "project":
        return True  # project membership check TBD
    return False
```

These functions are called by tools, not middleware, because authorization decisions depend on the specific memory being accessed — information that's only available after the tool has parsed its arguments and started its query.

### Agent Identity Model

An agent always acts on behalf of an identity. There are two types:

**User-bound agents.** The common case. An agent authenticates with an API key tied to a human user. All operations are scoped to that user's identity. The agent can read/write user-scope memories for its owner, and access broader scopes (project, organizational, enterprise) according to the owner's permissions.

**Service agents.** Autonomous agents that perform system functions — the curator agent is the primary example. A service agent has its own identity (e.g., `curator-agent`) and its own API key. It is not "acting on behalf of" a user; it has its own permissions.

Service agents need carefully scoped permissions:
- The curator agent needs read access across all scopes (to detect patterns) and write access to organizational/role scopes (to promote patterns). It should not have write access to user-scope memories.
- Future service agents (e.g., a compliance scanner) might need read-only access across all scopes.

The identity model maps to the existing users ConfigMap:

```json
{
  "user_id": "curator-agent",
  "name": "Curator Agent",
  "api_key": "mh-svc-curator-2026",
  "scopes": ["memory:read", "memory:write:organizational", "memory:write:role"],
  "identity_type": "service"
}
```

The `identity_type` field (`user` or `service`) distinguishes the two types. Scopes use the operational format defined in the Authentication Architecture section (e.g., `memory:read`, `memory:write:organizational`). Service agents get precisely the permissions they need — the curator can read all memories but only write to organizational and role tiers.

Under the target architecture, identity metadata moves from the ConfigMap to JWT claims issued by the OAuth 2.1 auth service (see Authentication Architecture). The ConfigMap remains as the client registry — mapping API keys to client identities — while the auth service translates these into signed JWTs that carry identity_type, scopes, and tenant_id.

### Authentication Architecture

MemoryHub's auth is built on OAuth 2.1, implemented as a **separate service** from the MCP server. This separation is deliberate: auth is a cross-cutting concern that serves the MCP server, the REST API (for non-MCP clients), the dashboard UI, and the Python SDK. Embedding it in the MCP server would couple auth lifecycle to MCP server deployments.

#### Token model

All authenticated requests carry a short-lived JWT (5–15 minute TTL). The JWT contains:

```json
{
  "sub": "wjackson",
  "identity_type": "user",
  "tenant_id": "org-acme-healthcare",
  "scopes": ["memory:read", "memory:write:user", "memory:read:organizational"],
  "iat": 1743879600,
  "exp": 1743880500,
  "iss": "https://memoryhub-auth.apps.example.com",
  "aud": "memoryhub"
}
```

Key claims:

- `sub` — the authenticated identity (user ID or service agent ID)
- `identity_type` — `user` or `service`
- `tenant_id` — multi-tenant isolation key. Agents in tenant A cannot access tenant B's memories, even with valid tokens. The MCP server filters all queries by tenant.
- `scopes` — operational permissions using a two-dimensional model (see Scope Model below)

Short TTLs limit blast radius: a leaked JWT is useless after expiration. Refresh tokens (longer-lived, revocable) allow long-running agent sessions to obtain new JWTs without re-presenting credentials.

#### Scope model

Scopes combine an **operation** with an optional **access tier**:

| Scope | Meaning |
|-------|---------|
| `memory:read` | Read memories at any accessible tier |
| `memory:read:user` | Read only user-scope memories |
| `memory:read:organizational` | Read organizational-scope memories |
| `memory:write` | Write memories at any accessible tier |
| `memory:write:user` | Write only user-scope memories |
| `memory:write:organizational` | Write organizational-scope (service agents only) |
| `memory:admin` | Administrative operations (key management, tenant config) |

The `authorize_read` and `authorize_write` functions (see Enforcement Architecture) check both the tier-level policy (who can access which scope) and the operational scope in the JWT. A service agent with `memory:read` but not `memory:write:user` can see user memories but cannot modify them.

#### Grant types

Three OAuth 2.1 grant types serve different client populations:

**`client_credentials`** — the workhorse grant for agents and SDKs.

An agent presents a `client_id` + `client_secret` (the API key) to the `/token` endpoint and receives a JWT. This is standard OAuth 2.1 — every language has a library for it.

```
POST /token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id=curator-agent
&client_secret=mh-svc-curator-2026
&scope=memory:read memory:write:organizational
```

Clients: Python SDK (`memoryhub` package), LlamaStack agents, LangChain/LangGraph agents, custom agents in any language, CI/CD pipelines.

**`authorization_code` + PKCE** — for humans in browsers.

The RHOAI dashboard, Claude Desktop (when OAuth support matures), and any browser-based tool. Redirects through OpenShift OAuth/OIDC, returns with a code, exchanges for a JWT. Standard OIDC flow backed by the cluster's identity provider.

Clients: RHOAI dashboard UI, Claude Desktop, browser-based agent UIs.

**Token exchange (RFC 8693)** — for platform-integrated agents.

When agents run on RHOAI or Kubernetes, they already have platform-issued tokens (Kubernetes service account tokens, RHOAI session tokens). Rather than managing separate API keys, they exchange their platform token for a MemoryHub-scoped JWT:

```
POST /token
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:token-exchange
&subject_token=<k8s-service-account-jwt>
&subject_token_type=urn:ietf:params:oauth:token-type:jwt
&scope=memory:read memory:write:user
```

The auth server validates the platform token (via Kubernetes TokenReview), maps the service account to a MemoryHub identity and tenant, and issues a scoped JWT. No API key management needed — identity derives from the platform.

This is how a healthcare system with 50 agents avoids managing 50 API keys. Each agent's identity comes from its Kubernetes service account, scoped by the namespace-to-tenant mapping.

Clients: LlamaStack agents on RHOAI, Kubernetes Jobs, platform-native workflows.

#### Trust configuration

The auth server maintains a trust configuration that defines which token issuers are accepted for token exchange. Initial configuration trusts only the local cluster:

```yaml
trust:
  issuers:
    - name: local-cluster
      type: kubernetes
      issuer_url: https://kubernetes.default.svc
      audiences: ["memoryhub"]
      tenant_mapping:
        source: namespace_annotation
        annotation: memoryhub.redhat.com/tenant-id
```

The trust configuration is designed to be expandable. Future additions:
- External OIDC providers (Azure AD, Okta) for cross-cloud agents
- Other MemoryHub clusters for federated memory access
- Custom token issuers for partner integrations

Each issuer entry defines how to validate incoming tokens and how to map the token's claims to MemoryHub identity (sub, tenant_id, scopes).

#### MCP server integration

The MCP server is a **resource server** in OAuth terms — it validates JWTs but does not issue them. FastMCP's `JWTVerifier` handles this:

```python
from fastmcp import FastMCP
from fastmcp.server.auth import JWTVerifier

auth = JWTVerifier(
    jwks_uri="https://memoryhub-auth.apps.example.com/.well-known/jwks.json",
    issuer="https://memoryhub-auth.apps.example.com",
    audience="memoryhub",
)

mcp = FastMCP("MemoryHub", auth=auth)
```

Tools access the authenticated identity via FastMCP's dependency injection:

```python
from fastmcp.server.dependencies import get_access_token

@mcp.tool
async def search_memory(query: str, ...) -> dict:
    token = get_access_token()
    user_id = token.claims["sub"]
    tenant_id = token.claims["tenant_id"]
    scopes = token.scopes
    # All queries filtered by tenant_id + scope authorization
```

This replaces the current `register_session` / `require_auth()` / `get_authenticated_owner()` pattern entirely. Auth happens at the transport layer before any tool code executes. The `register_session` tool is retained as a **compatibility shim** for MCP clients that cannot send HTTP Authorization headers (due to client bugs or limitations) — it accepts an API key, performs the token exchange internally, and stores the resulting identity for the session.

#### Client integration patterns

**MCP-native clients** (Claude Code, Cursor, OpenCode, Claude Desktop): Discover auth via `/.well-known/oauth-protected-resource` (RFC 9728). Perform OAuth flow or send pre-obtained bearer token. The MCP server advertises its auth requirements; compliant clients handle it automatically.

**SDK clients** (Python, future: TypeScript, Go): The `memoryhub` SDK handles token exchange, caching, refresh, and retry-on-401 transparently:

```python
from memoryhub import MemoryHubClient

# API key auth (client_credentials grant)
client = MemoryHubClient(
    url="https://memoryhub.apps.example.com",
    api_key="mh-dev-wjackson-2026",
)

# Platform auth (token exchange, auto-discovers K8s SA token)
client = MemoryHubClient(
    url="https://memoryhub.apps.example.com",
    platform_token=True,
)

# The developer never manages tokens — the SDK does it
memories = await client.search("deployment patterns")
```

**Non-MCP clients** (REST-only systems, Pi, legacy integrations): Call the same `/token` endpoint directly, then pass the JWT as `Authorization: Bearer <token>` on REST API calls. No MCP protocol required.

#### Authorino as defense-in-depth

Authorino remains available as an optional infrastructure hardening layer. When deployed, it validates tokens at the OpenShift Route before requests reach the MCP server process. This provides:

- Rate limiting and DDoS protection at the infrastructure level
- Token validation without consuming application resources
- Additional policy enforcement (IP allowlists, request size limits)

The MCP server does **not depend on** Authorino — it validates JWTs itself via FastMCP's `JWTVerifier`. Authorino is defense-in-depth, not the primary auth mechanism. The AuthConfig CR uses `apiVersion: authorino.kuadrant.io/v1beta2` (verified on cluster; only v1beta1 and v1beta2 are available).

### Audit Trail Schema

The `audit_log` table records every memory operation. It is append-only: no UPDATE or DELETE operations are permitted on this table.

```sql
CREATE TABLE audit_log (
    id              UUID DEFAULT uuid_generate_v4(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    operation       VARCHAR(20) NOT NULL,  -- create, read, update, prune, search, promote
    actor_id        VARCHAR(255) NOT NULL, -- authenticated user_id or service agent id
    actor_type      VARCHAR(10) NOT NULL,  -- 'user' or 'service'
    memory_id       UUID,                  -- target memory (NULL for search/auth operations)
    memory_scope    VARCHAR(20),           -- scope of the target memory at operation time
    memory_owner_id VARCHAR(255),          -- owner of the target memory at operation time
    decision        VARCHAR(10) NOT NULL,  -- 'permitted' or 'denied'
    denial_reason   TEXT,                  -- NULL if permitted; reason string if denied
    state_before    JSONB,                 -- memory state before mutation (writes only)
    state_after     JSONB,                 -- memory state after mutation (writes only)
    request_context JSONB,                 -- search: query text, result IDs, scope filter;
                                           -- auth: key prefix, success/failure, identity;
                                           -- other: tool parameters
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

-- Monthly partitions created by operator/cron
-- Example: CREATE TABLE audit_log_2026_04 PARTITION OF audit_log
--          FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE INDEX idx_audit_log_actor ON audit_log (actor_id, timestamp);
CREATE INDEX idx_audit_log_memory ON audit_log (memory_id, timestamp);
CREATE INDEX idx_audit_log_operation ON audit_log (operation, timestamp);
CREATE INDEX idx_audit_log_denied ON audit_log (decision, timestamp)
    WHERE decision = 'denied';
```

**Append-only enforcement.** PostgreSQL row-level security (RLS) with a dedicated `audit_writer` role that has INSERT-only permissions. The application connects as this role for audit writes. Even the primary application role cannot UPDATE or DELETE audit rows.

```sql
-- Create restricted role
CREATE ROLE audit_writer;
GRANT INSERT ON audit_log TO audit_writer;
-- No UPDATE, DELETE, or TRUNCATE

-- Enable RLS
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Policy: everyone can read (for forensics), only audit_writer can insert
CREATE POLICY audit_read ON audit_log FOR SELECT USING (true);
CREATE POLICY audit_insert ON audit_log FOR INSERT WITH CHECK (true);
```

**Tiered detail for reads.** High-volume read operations (search, read_memory) can be batched or sampled rather than logged individually. Configuration via curation rules:

- `audit_detail: full` — every operation logged with full state (default for writes)
- `audit_detail: summary` — batch entry per session (e.g., "session X performed 47 reads")
- `audit_detail: sample` — log 1 in N reads (configurable)

Write operations, governance decisions (permitted/denied), and scope promotions always get full-detail entries regardless of configuration.

For search operations, `request_context` must include: the query text, the scope filter applied, the result set (list of memory IDs and versions served), and the embedding vector hash (for reproducibility). For authentication events (`register_session` — both success and failure), `request_context` captures the key prefix, the resolved identity, and the outcome.

**Retention.** Audit data grows linearly with usage. The table is partitioned by month (see DDL above). A configurable retention policy (default: 90 days full-detail, 1 year summaries) is enforced by the operator. Old partitions are archived to S3 (MinIO) before being dropped, preserving data for compliance while keeping the active table performant.

### Visibility Rules for Cross-Reference Tools

**`get_similar_memories`**: Currently returns similar memories scoped to the source node's owner and scope. This is correct for user-scope memories but insufficient for broader scopes. The fix: after retrieving similar nodes, filter through `authorize_read(user, node)` before returning results. Nodes the caller can't access are silently omitted.

**`get_relationships`**: Returns all relationships for a given node. The node itself and all related nodes must pass `authorize_read`. Relationships pointing to inaccessible nodes are omitted from the result, with a count of omitted relationships included so the caller knows the graph is incomplete.

**`search_memory`**: The SQL query must include an ownership predicate. For user-scope memories, filter to `owner_id = authenticated_user_id`. For broader scopes, include memories where the caller `has_scope(scope)`. This filtering happens at the SQL level (not post-query) for performance.

```sql
-- Search query with scope enforcement
-- Bind params derived from JWT: e.g., :has_project_scope = 'memory:read:project' in token.scopes
--                                      or 'memory:read' in token.scopes (wildcard)
SELECT * FROM memory_nodes
WHERE is_current = true
  AND tenant_id = :tenant_id
  AND (
    (scope = 'user' AND owner_id = :caller_id)
    OR (scope = 'project' AND :has_project_scope)
    OR (scope = 'role' AND :has_role_scope)  -- TODO: add role_tag matching
    OR (scope = 'organizational' AND :has_org_scope)
    OR (scope = 'enterprise' AND :has_enterprise_scope)
  )
  AND embedding <=> :query_embedding < :threshold
ORDER BY embedding <=> :query_embedding
LIMIT :max_results;
```

## Design Questions

- How do we implement truly append-only audit logging in PostgreSQL? Row-level security can restrict deletes, but a superuser can bypass it. Do we need an external append-only store (like a blockchain-style hash chain) for tamper evidence?
- What's the right balance between audit detail and storage cost for read operations? Full read logging vs. sampled vs. batched?
- How do we handle cross-cluster forensics? If memories are federated across clusters, forensic queries need to span clusters too.
- Should secrets scanning use an LLM for nuanced detection (fewer false positives) or regex patterns (faster, deterministic, no external API calls)?
- How do we handle the case where a legitimate user's agent writes something that looks like a secret but isn't? The whitelist UX needs to be smooth enough that it doesn't discourage honest use.
