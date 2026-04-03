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

## Design Questions

- How do we implement truly append-only audit logging in PostgreSQL? Row-level security can restrict deletes, but a superuser can bypass it. Do we need an external append-only store (like a blockchain-style hash chain) for tamper evidence?
- What's the right balance between audit detail and storage cost for read operations? Full read logging vs. sampled vs. batched?
- How do we handle cross-cluster forensics? If memories are federated across clusters, forensic queries need to span clusters too.
- Should secrets scanning use an LLM for nuanced detection (fewer false positives) or regex patterns (faster, deterministic, no external API calls)?
- How do we handle the case where a legitimate user's agent writes something that looks like a secret but isn't? The whitelist UX needs to be smooth enough that it doesn't discourage honest use.
