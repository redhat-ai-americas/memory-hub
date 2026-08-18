# Phase 1: Audit Persistence Backend Evaluation

**Date**: 2026-08-18  
**Issue**: #70 - Audit persistence eval  
**Phase 0 status**: Complete (stub verified, gaps documented)

## Evaluation Criteria

From `docs/identity-model/authorization.md:253-300`:

1. **First-class identity fields**: `actor_id` and `driver_id` as queryable fields, not free-form attributes
2. **Tamper-evidence / append-only**: Audit events must be immutable
3. **Retention**: 6-7 year retention for healthcare compliance
4. **Denied operations**: Both successful and denied operations captured with equal fidelity
5. **Query path**: "Show me everything actor X did during conversation Y" must be efficient

---

## Candidate Backends

| Backend | Complexity | RHOAI Integration | Query Performance | Retention | Tamper-Evidence |
|---------|-----------|-------------------|-------------------|-----------|-----------------|
| **PostgreSQL audit table** | Low | Native (OOTB component) | Excellent (indexed SQL) | Application-managed | RLS + constraints |
| **OpenTelemetry export** | Medium | Platform-native (OTLP) | Good (Loki/Tempo queries) | Platform-managed | Storage-dependent |
| **Platform logs (JSON)** | Minimal | Native (pod logs) | Poor (grep/jq on files) | Platform-managed | Storage-dependent |

---

## Option 1: PostgreSQL Audit Table

**Architecture**: Dedicated `audit_log` table in the existing MemoryHub PostgreSQL database.

### Schema

```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type VARCHAR(64) NOT NULL,
    actor_id VARCHAR(255) NOT NULL,
    driver_id VARCHAR(255) NOT NULL,
    scope VARCHAR(64) NOT NULL,
    owner_id VARCHAR(255) NOT NULL,
    memory_id UUID,
    decision VARCHAR(16) NOT NULL CHECK (decision IN ('allowed', 'denied')),
    metadata JSONB,
    tenant_id VARCHAR(255) NOT NULL
);

-- Indexes for common queries
CREATE INDEX idx_audit_log_actor ON audit_log (actor_id, timestamp DESC);
CREATE INDEX idx_audit_log_event_type ON audit_log (event_type, timestamp DESC);
CREATE INDEX idx_audit_log_decision ON audit_log (decision, timestamp DESC);
CREATE INDEX idx_audit_log_tenant ON audit_log (tenant_id, timestamp DESC);

-- Partitioning for retention management (monthly partitions)
CREATE TABLE audit_log_2026_08 PARTITION OF audit_log
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
```

### Append-Only Enforcement (RLS)

```sql
-- Dedicated audit writer role (used by MCP server)
CREATE ROLE audit_writer;
GRANT INSERT ON audit_log TO audit_writer;

-- Enable RLS to prevent updates/deletes
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Policy: audit_writer can only INSERT
CREATE POLICY audit_insert_only ON audit_log
    FOR INSERT TO audit_writer
    WITH CHECK (true);

-- Policy: readers cannot modify
CREATE POLICY audit_no_modify ON audit_log
    FOR UPDATE TO audit_reader
    USING (false);

CREATE POLICY audit_no_delete ON audit_log
    FOR DELETE TO audit_reader
    USING (false);

-- Revoke UPDATE/DELETE from all roles (defense in depth)
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;
```

### Retention via Partitioning

```sql
-- Monthly partitions with automated retention
-- Drop partitions older than 7 years via scheduled job
-- Example: Drop 2019-08 partition in 2026-08
DROP TABLE IF EXISTS audit_log_2019_08;
```

### Pros

✅ **First-class fields**: SQL columns, fully indexed, type-checked  
✅ **Query performance**: Native SQL with indexes — sub-second queries even for millions of rows  
✅ **Tamper-evidence**: RLS + REVOKE prevents modifications; cryptographic hash chain optional  
✅ **Retention**: Partitioning makes 7-year retention tractable (drop old partitions)  
✅ **Denied ops**: No difference between allowed/denied events (same table)  
✅ **RHOAI integration**: PostgreSQL already deployed as OOTB component  
✅ **Transactional**: Audit events can participate in DB transactions (future: write+audit atomicity)  
✅ **Compliance-friendly**: Healthcare auditors understand SQL; can query directly

### Cons

⚠️ **Application-managed retention**: Partition management requires cron job or Alembic migration  
⚠️ **Storage cost**: Full schema per event (vs compressed logs); mitigated by partitioning + archival  
⚠️ **Not distributed**: Single PostgreSQL instance (acceptable for MemoryHub's scale)  
⚠️ **Crypto tamper-evidence**: Hash chain requires application logic; not built-in

### Implementation Effort

- **Alembic migration**: ~50 lines (schema, indexes, RLS policies)
- **Audit service**: Replace `logger.info(json.dumps(...))` with `INSERT INTO audit_log`
- **Retention script**: Cron job or operator to drop old partitions
- **Total**: ~2 days

---

## Option 2: OpenTelemetry Export

**Architecture**: Emit audit events as OpenTelemetry spans/logs, export via OTLP to platform-managed backend (Loki, Tempo, Jaeger).

### Event Structure

```python
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)

def record_event(...):
    with tracer.start_as_current_span("audit.memory.write") as span:
        span.set_attribute("audit.actor_id", actor_id)
        span.set_attribute("audit.driver_id", driver_id)
        span.set_attribute("audit.scope", scope)
        span.set_attribute("audit.owner_id", owner_id)
        span.set_attribute("audit.memory_id", str(memory_id) if memory_id else None)
        span.set_attribute("audit.decision", decision)
        span.set_status(
            Status(StatusCode.OK if decision == "allowed" else StatusCode.ERROR)
        )
```

### Query Path (Loki)

```promql
{job="memory-hub-mcp"} 
  | json 
  | actor_id="user-alice" 
  | line_format "{{.timestamp}} {{.event_type}} {{.decision}}"
```

### Query Path (Tempo/Jaeger)

```
service.name="memory-hub-mcp" 
AND audit.actor_id="user-alice" 
AND audit.decision="denied"
```

### Pros

✅ **Platform integration**: RHOAI already has OTLP collectors, Loki/Tempo backends  
✅ **Distributed tracing**: Correlate audit events with request traces  
✅ **Retention**: Platform-managed (configure in Loki/Tempo)  
✅ **Denied ops**: Same path for allowed/denied  
✅ **Storage backend**: Delegates to platform (S3, block storage, etc.)  
✅ **Tamper-evidence**: Depends on storage backend (immutable S3 buckets possible)

### Cons

⚠️ **Attribute vs first-class**: Fields are span attributes (string key-value), not typed schema  
⚠️ **Query complexity**: PromQL/TraceQL less intuitive than SQL for tabular queries  
⚠️ **Healthcare audit**: Compliance auditors may not have Grafana access; need export path  
⚠️ **Retention limits**: Loki retention often capped at 30-90 days (configurable but expensive)  
⚠️ **No transactional guarantees**: Async export; audit event may arrive after DB commit  
⚠️ **Platform dependency**: Requires OTLP stack deployed and healthy

### Implementation Effort

- **OpenTelemetry SDK**: Add to dependencies, configure OTLP exporter
- **Audit service**: Emit spans instead of log lines
- **Loki configuration**: Ensure 7-year retention (storage costs TBD)
- **Export tool**: Script to dump Loki logs to CSV for compliance queries
- **Total**: ~3 days (plus platform config negotiation)

---

## Option 3: Platform Logs (JSON to stdout)

**Architecture**: Current stub implementation — write JSON to stdout, rely on platform log aggregation (pod logs → Loki/Elasticsearch).

### Current Implementation

```python
logger.info(json.dumps(event, sort_keys=True))
```

Platform captures stdout, routes to log aggregation.

### Query Path

```bash
# Grep pod logs
oc logs deployment/memory-hub-mcp --context mcp-rhoai -n memory-hub-mcp | \
  grep '"actor_id": "user-alice"'

# Loki query (if logs forwarded)
{namespace="memory-hub-mcp", pod=~"memory-hub-mcp-.*"} 
  | json 
  | actor_id="user-alice"
```

### Pros

✅ **Minimal implementation**: Already done (stub is production-ready)  
✅ **Platform integration**: Uses standard pod logging  
✅ **No schema changes**: No Alembic migrations or DB tables  
✅ **Retention**: Platform-managed (configure in Loki/Elasticsearch)  
✅ **Denied ops**: Same path for allowed/denied

### Cons

❌ **No first-class fields**: Fields are string values in JSON blobs, not queryable columns  
❌ **Query performance**: Full log scan for every query (no indexes)  
❌ **Tamper-evidence**: None (logs can be edited/deleted by cluster admins)  
❌ **Retention**: Pod logs rotate frequently (days, not years); Loki retention often short  
❌ **Compliance unfriendly**: No SQL interface; auditors need Grafana access or log exports  
❌ **Scale limits**: Grep-based queries fail at high volume  
❌ **No transactional guarantees**: Log line may be lost on pod restart

### Healthcare Compliance Risk

**Critical gap**: No immutability guarantee. A cluster admin (or compromised workload) can:
1. Edit the JSON log line to change `actor_id`
2. Delete log lines to hide unauthorized operations
3. Inject fake audit events

This violates the core trust property: "the audit log is the authoritative record of who did what."

### Implementation Effort

- **Current state**: Stub is already shipping JSON to stdout
- **Loki query training**: Document Grafana query patterns for operators
- **Export tool**: Script to dump logs to CSV for compliance (brittle)
- **Total**: ~0.5 days (minimal, but weak compliance story)

---

## Recommendation: PostgreSQL Audit Table

**Why PostgreSQL wins**:

1. **Strongest compliance story**: SQL is the lingua franca of healthcare audits. Auditors can run standard SQL queries, export to CSV, and present findings in regulatory reviews. Grafana is not a compliance-friendly tool.

2. **Tamper-evidence**: RLS + `REVOKE UPDATE, DELETE` provides application-enforced immutability. A compromised MCP server can insert new events (which is correct — that's the audit path) but cannot modify or delete historical records. For cryptographic tamper-evidence, add a hash chain in the `metadata` JSONB field (SHA-256 of current row + previous row hash).

3. **7-year retention is tractable**: Monthly partitions + automated drop script makes 7-year retention a solved problem. Each partition is a self-contained table that can be backed up, archived to S3, or dropped independently.

4. **Query performance scales**: Indexed SQL queries return results in milliseconds even with millions of rows. The "show me everything actor X did" query is a single index scan:

   ```sql
   SELECT * FROM audit_log
   WHERE actor_id = 'ed-triage-nurse-01'
     AND timestamp >= '2026-08-01'
     AND timestamp < '2026-08-02'
   ORDER BY timestamp DESC;
   ```

5. **No platform dependency**: PostgreSQL is already deployed as an OOTB component. No negotiation with platform teams to configure Loki retention or OTLP collectors. MemoryHub owns the full audit stack.

6. **Transactional safety (future)**: When we move to intersection authorization, the audit event can be inserted in the same transaction as the memory write. This makes "write succeeded but audit failed" impossible — if the audit insert fails, the transaction rolls back.

**When OpenTelemetry makes sense**:

If RHOAI already has a mature, compliance-ready observability stack with:
- 7-year retention configured and funded
- Immutable storage backend (S3 with object lock)
- SQL-compatible query layer (e.g., Athena on exported logs)
- Buy-in from compliance team

Then OpenTelemetry is the right choice. But that's a big "if" — most platforms cap Loki at 30-90 days.

**Platform logs are not viable** for regulated workloads. No immutability, no long-term retention, no compliance-friendly query path.

---

## Implementation Plan (PostgreSQL)

### Phase 1.1: Schema and Alembic Migration

**File**: `src/memoryhub/alembic/versions/<timestamp>_audit_log_table.py`

```python
def upgrade():
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("driver_id", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("memory_id", sa.UUID(), nullable=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("decision IN ('allowed', 'denied')", name="ck_audit_decision"),
    )
    
    op.create_index("idx_audit_log_actor", "audit_log", ["actor_id", "timestamp"])
    op.create_index("idx_audit_log_event_type", "audit_log", ["event_type", "timestamp"])
    op.create_index("idx_audit_log_decision", "audit_log", ["decision", "timestamp"])
    op.create_index("idx_audit_log_tenant", "audit_log", ["tenant_id", "timestamp"])
    
    # RLS policies (PostgreSQL-specific)
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")
```

### Phase 1.2: Service Layer

**File**: `src/memoryhub/services/audit.py`

```python
from sqlalchemy import insert
from memoryhub_core.models.audit import AuditLog

async def record_event(
    session,  # SQLAlchemy async session
    event_type: str,
    actor_id: str,
    driver_id: str,
    scope: str,
    owner_id: str,
    memory_id: str | None,
    decision: str,
    metadata: dict | None = None,
    tenant_id: str,
) -> None:
    """Insert an audit event into the audit_log table.
    
    Fire-and-forget: exceptions are logged but never propagate to caller.
    """
    try:
        stmt = insert(AuditLog).values(
            event_type=event_type,
            actor_id=actor_id,
            driver_id=driver_id,
            scope=scope,
            owner_id=owner_id,
            memory_id=memory_id,
            decision=decision,
            metadata=metadata,
            tenant_id=tenant_id,
        )
        await session.execute(stmt)
        # Commit is handled by the caller's transaction context
    except Exception as exc:
        logger.error("Audit insert failed: %s", exc, exc_info=True)
        # Swallow the exception (fire-and-forget)
```

### Phase 1.3: Tool Integration

Update all tool call sites from:

```python
from src.core.audit import record_event

record_event(
    event_type="memory.write",
    actor_id=actor_id,
    driver_id=driver_id,
    scope=scope,
    owner_id=owner_id,
    memory_id=None,
    decision="allowed",
)
```

To:

```python
from memoryhub_core.services.audit import record_event

await record_event(
    session=session,  # Current DB session
    event_type="memory.write",
    actor_id=actor_id,
    driver_id=driver_id,
    scope=scope,
    owner_id=owner_id,
    memory_id=None,
    decision="allowed",
    tenant_id=tenant_id,
)
```

**Transaction guarantee**: Since `session` is the same session as the memory write, the audit event participates in the transaction. If the write rolls back, the audit event rolls back. If the write commits, the audit event commits.

### Phase 1.4: Retention Script

**File**: `scripts/drop-old-audit-partitions.sh`

```bash
#!/bin/bash
# Drop audit_log partitions older than 7 years
# Run via cron: 0 2 1 * * /path/to/drop-old-audit-partitions.sh

CUTOFF_MONTH=$(date -d "7 years ago" +%Y-%m)

psql -h memoryhub-pg.memoryhub-db.svc -U memoryhub -c "
DROP TABLE IF EXISTS audit_log_${CUTOFF_MONTH//-/_};
"
```

### Phase 1.5: Query API (Optional)

Expose audit queries via MCP tool or HTTP endpoint:

```python
@mcp.tool
async def query_audit_log(
    actor_id: str | None = None,
    event_type: str | None = None,
    decision: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query the audit log. Restricted to memory:admin scope."""
    # Build SQL WHERE clause from parameters
    # Return JSON results
```

---

## Deliverables

- [ ] Alembic migration: `audit_log` table + indexes + RLS policies
- [ ] Service layer: `memoryhub_core.services.audit.record_event()` (async, fire-and-forget)
- [ ] Update all 8 tools to call new service layer
- [ ] Retention script: `scripts/drop-old-audit-partitions.sh`
- [ ] Integration tests: Verify events are written to DB, RLS prevents updates
- [ ] Query examples: Document SQL patterns for common compliance queries
- [ ] Demo script: Update agriculture Segments 5-6 to show SQL queries

---

## Acceptance Criteria

- [ ] Audit events are written to `audit_log` table
- [ ] All 7 required fields are indexed
- [ ] RLS policies prevent UPDATE/DELETE
- [ ] Denied operations have identical schema as allowed operations
- [ ] Query "show me everything actor X did" returns in <100ms for 1M rows
- [ ] Partition drop script removes 7-year-old data without downtime
- [ ] Fire-and-forget: Audit insert failures are logged but don't block tools
- [ ] Transactional: Memory write + audit event commit together

---

## Open Questions

1. **Cryptographic hash chain**: Do we need SHA-256 hash chain in `metadata.previous_hash` for tamper-evidence, or is RLS + REVOKE sufficient?
2. **Partition automation**: Should partition creation/deletion be handled by Alembic migrations or a separate cron job/operator?
3. **Audit query access control**: Should audit queries be restricted to `memory:admin` scope, or should users see their own audit trail?
4. **Export format**: Do compliance auditors need a CSV export tool, or can they run SQL directly against the read replica?
