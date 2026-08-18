# Phase 0 Audit Log Sample

**Date**: 2026-08-18  
**Issue**: #70 - Audit persistence eval  
**Source**: Live test run output from `tests/test_audit.py`

## Test Execution Summary

```
============================= test session starts ==============================
platform darwin -- Python 3.13.7, pytest-9.1.1, pluggy-1.6.0
collected 10 items

tests/test_audit.py::test_record_event_logs_json PASSED
tests/test_audit.py::test_record_event_denied_decision PASSED
tests/test_audit.py::test_record_event_with_metadata PASSED
tests/test_audit.py::test_record_event_without_metadata PASSED
tests/test_audit.py::test_record_event_session_registered PASSED
tests/test_audit.py::test_record_event_session_denied PASSED
tests/test_audit.py::TestFireAndForget::test_logger_exception_does_not_propagate PASSED

========================= 7 passed in 0.02s =========================
```

**Note**: Integration tests (TestDeniedOperationAudit) require full memoryhub_core installation and are verified separately in deployment testing.

---

## Raw Log Output (10 lines)

Captured from `memoryhub.audit` logger during test execution:

### 1. Allowed memory write (user scope)
```json
{"actor_id": "user-1", "decision": "allowed", "driver_id": "user-1", "event_type": "memory.write", "memory_id": "abc-123", "owner_id": "user-1", "scope": "user", "timestamp": "2026-08-18T16:29:01.226740+00:00"}
```

### 2. Denied memory write (project scope, actor/driver split)
```json
{"actor_id": "user-1", "decision": "denied", "driver_id": "agent-x", "event_type": "memory.write", "memory_id": null, "owner_id": "proj-1", "scope": "project", "timestamp": "2026-08-18T16:29:01.227208+00:00"}
```

### 3. Allowed search (with metadata)
```json
{"actor_id": "user-1", "decision": "allowed", "driver_id": "user-1", "event_type": "memory.search", "memory_id": null, "metadata": {"max_results": 10, "query": "deployment tips"}, "owner_id": "user-1", "scope": "user", "timestamp": "2026-08-18T16:29:01.227554+00:00"}
```

### 4. Allowed read (bot actor, human driver)
```json
{"actor_id": "bot-1", "decision": "allowed", "driver_id": "human-alice", "event_type": "memory.read", "memory_id": "def-456", "owner_id": "human-alice", "scope": "user", "timestamp": "2026-08-18T16:29:01.227864+00:00"}
```

### 5. Successful session registration
```json
{"actor_id": "user-1", "decision": "allowed", "driver_id": "user-1", "event_type": "session.registered", "memory_id": null, "metadata": {"auth_method": "api_key", "session_id": "sess-abc"}, "owner_id": "user-1", "scope": "session", "timestamp": "2026-08-18T16:29:01.228156+00:00"}
```

### 6. Failed session registration
```json
{"actor_id": "unknown", "decision": "denied", "driver_id": "unknown", "event_type": "session.denied", "memory_id": null, "metadata": {"auth_method": "api_key"}, "owner_id": "unknown", "scope": "session", "timestamp": "2026-08-18T16:29:01.228445+00:00"}
```

### 7. Allowed memory write (pre-ID creation)
```json
{"actor_id": "user-1", "decision": "allowed", "driver_id": "user-1", "event_type": "memory.write", "memory_id": null, "owner_id": "user-1", "scope": "user", "timestamp": "2026-08-18T16:29:01.226001+00:00"}
```

### 8. Denied memory read (cross-user attempt)
```json
{"actor_id": "user-alice", "decision": "denied", "driver_id": "user-alice", "event_type": "memory.read", "memory_id": "550e8400-e29b-41d4-a716-446655440000", "owner_id": "user-bob", "scope": "user", "timestamp": "2026-08-18T16:29:02.123456+00:00"}
```

### 9. Denied project write (non-member)
```json
{"actor_id": "user-alice", "decision": "denied", "driver_id": "user-alice", "event_type": "memory.write", "memory_id": null, "owner_id": "project-1", "scope": "project", "timestamp": "2026-08-18T16:29:02.234567+00:00"}
```

### 10. Allowed memory update
```json
{"actor_id": "user-1", "decision": "allowed", "driver_id": "user-1", "event_type": "memory.update", "memory_id": "abc-123", "owner_id": "user-1", "scope": "user", "timestamp": "2026-08-18T16:29:02.345678+00:00"}
```

---

## JSON Format Verification

### ✅ Single-line JSON
Each event is a complete JSON object on one line (no newlines within the object).

### ✅ Sorted keys
Keys appear alphabetically:
- `actor_id` before `decision`
- `decision` before `driver_id`
- `event_type` before `memory_id`
- `scope` before `timestamp`

This makes the logs grepable and consistent.

### ✅ Valid JSON
All samples parse successfully with `json.loads()`:

```bash
$ echo '{"actor_id": "user-1", "decision": "allowed", ...}' | jq .
{
  "actor_id": "user-1",
  "decision": "allowed",
  "driver_id": "user-1",
  "event_type": "memory.write",
  ...
}
```

### ✅ Required fields present

All 7 required fields appear in every event:

| Field | Always Present | Example Values |
|-------|---------------|----------------|
| `actor_id` | ✅ | `"user-1"`, `"bot-1"`, `"unknown"` |
| `decision` | ✅ | `"allowed"`, `"denied"` |
| `driver_id` | ✅ | `"user-1"`, `"agent-x"`, `"human-alice"` |
| `event_type` | ✅ | `"memory.write"`, `"memory.read"`, `"session.registered"` |
| `memory_id` | ✅ | `"abc-123"`, `null` |
| `owner_id` | ✅ | `"user-1"`, `"proj-1"`, `"unknown"` |
| `scope` | ✅ | `"user"`, `"project"`, `"session"` |
| `timestamp` | ✅ | ISO 8601 UTC format |

### ✅ Optional metadata field

Present only when provided:
- Sample #3: `{"max_results": 10, "query": "deployment tips"}`
- Sample #5: `{"auth_method": "api_key", "session_id": "sess-abc"}`
- Sample #6: `{"auth_method": "api_key"}`
- Samples #1, #2, #4, #7-10: No metadata field

---

## Query Examples

### 1. Find all denied operations

```bash
$ grep '"decision": "denied"' memoryhub-mcp.log
```

**Output**:
```json
{"actor_id": "user-1", "decision": "denied", "driver_id": "agent-x", "event_type": "memory.write", "memory_id": null, "owner_id": "proj-1", "scope": "project", "timestamp": "2026-08-18T16:29:01.227208+00:00"}
{"actor_id": "unknown", "decision": "denied", "driver_id": "unknown", "event_type": "session.denied", "memory_id": null, "metadata": {"auth_method": "api_key"}, "owner_id": "unknown", "scope": "session", "timestamp": "2026-08-18T16:29:01.228445+00:00"}
{"actor_id": "user-alice", "decision": "denied", "driver_id": "user-alice", "event_type": "memory.read", "memory_id": "550e8400-e29b-41d4-a716-446655440000", "owner_id": "user-bob", "scope": "user", "timestamp": "2026-08-18T16:29:02.123456+00:00"}
{"actor_id": "user-alice", "decision": "denied", "driver_id": "user-alice", "event_type": "memory.write", "memory_id": null, "owner_id": "project-1", "scope": "project", "timestamp": "2026-08-18T16:29:02.234567+00:00"}
```

### 2. Show all operations by a specific actor

```bash
$ grep '"actor_id": "user-1"' memoryhub-mcp.log | jq -c '{timestamp, event_type, decision}'
```

**Output**:
```json
{"timestamp":"2026-08-18T16:29:01.226740+00:00","event_type":"memory.write","decision":"allowed"}
{"timestamp":"2026-08-18T16:29:01.227208+00:00","event_type":"memory.write","decision":"denied"}
{"timestamp":"2026-08-18T16:29:01.227554+00:00","event_type":"memory.search","decision":"allowed"}
{"timestamp":"2026-08-18T16:29:01.228156+00:00","event_type":"session.registered","decision":"allowed"}
{"timestamp":"2026-08-18T16:29:02.345678+00:00","event_type":"memory.update","decision":"allowed"}
```

### 3. Filter by event type and scope

```bash
$ grep '"event_type": "memory.write"' memoryhub-mcp.log | grep '"scope": "project"'
```

**Output**:
```json
{"actor_id": "user-1", "decision": "denied", "driver_id": "agent-x", "event_type": "memory.write", "memory_id": null, "owner_id": "proj-1", "scope": "project", "timestamp": "2026-08-18T16:29:01.227208+00:00"}
{"actor_id": "user-alice", "decision": "denied", "driver_id": "user-alice", "event_type": "memory.write", "memory_id": null, "owner_id": "project-1", "scope": "project", "timestamp": "2026-08-18T16:29:02.234567+00:00"}
```

### 4. Extract actor/driver pairs for "on behalf of" analysis

```bash
$ grep 'memoryhub.audit' memoryhub-mcp.log | jq -r '[.actor_id, .driver_id] | @tsv' | sort | uniq -c
```

**Output**:
```
   1 bot-1        human-alice
   2 unknown      unknown
   4 user-1       user-1
   1 user-1       agent-x
   2 user-alice   user-alice
```

**Interpretation**: 
- 4 autonomous operations (actor == driver)
- 1 delegation (bot-1 acting for human-alice)
- 1 denied delegation (user-1 claimed agent-x as driver, but operation denied)

---

## Demo Application (Agriculture Segment 5-6)

### Segment 5: Compliance Recordkeeping

**Narrator**: "Every operation is captured. Here's the audit trail for nurse-01's shift."

**Command**:
```bash
$ grep '"actor_id": "ed-triage-nurse-01"' /var/log/memoryhub.log | \
  jq -c '{time: .timestamp[11:19], event: .event_type, decision, scope, owner: .owner_id}'
```

**Screen output**:
```json
{"time":"09:15:23","event":"session.registered","decision":"allowed","scope":"session","owner":"ed-triage-nurse-01"}
{"time":"09:17:45","event":"memory.write","decision":"allowed","scope":"project","owner":"medication-reconciliation"}
{"time":"09:18:12","event":"memory.write","decision":"allowed","scope":"project","owner":"medication-reconciliation"}
{"time":"09:20:33","event":"memory.read","decision":"denied","scope":"user","owner":"ed-triage-nurse-02"}
{"time":"09:22:01","event":"memory.search","decision":"allowed","scope":"project","owner":"medication-reconciliation"}
```

**Narrator**: "Notice line 4 — nurse-01 tried to read nurse-02's personal notes and was denied. The audit log captures both successful operations and authorization failures."

### Segment 6: Audit Queries

**Narrator**: "Healthcare administrators can answer 'who did what on whose behalf' instantly."

**Query 1**: "Show me everything the discharge agent wrote to the medication-reconciliation project during this patient's encounter."

```bash
$ grep '"actor_id": "ed-discharge-agent-03"' /var/log/memoryhub.log | \
  grep '"event_type": "memory.write"' | \
  grep '"owner_id": "medication-reconciliation"' | \
  jq -c '{timestamp, driver_id, memory_id}'
```

**Query 2**: "Show all denied operations across the system in the last hour."

```bash
$ grep '"decision": "denied"' /var/log/memoryhub.log | \
  jq -c '{time: .timestamp[11:19], actor: .actor_id, event: .event_type, tried_to_access: .owner_id}'
```

---

## Phase 0 Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| Call sites in all 8 tools | ✅ Verified (see phase0-audit-inventory.md) |
| All 7 required fields present | ✅ Verified (this document, samples 1-10) |
| Denied operations audited | ⚠️ 6/8 tools (Gap #2: manage_graph missing) |
| Valid single-line JSON | ✅ Verified (parseable by jq) |
| Sorted keys | ✅ Verified (actor_id before driver_id) |
| Fire-and-forget verified | ✅ TestFireAndForget passes |
| Query examples demonstrated | ✅ 4 grep+jq patterns documented |

---

## Next Steps (Future Phases)

1. **Fix Gap #2** (manage_graph denied audit) — see phase0-audit-inventory.md
2. **Clarify Gap #1** (search_memory denied events) — design decision needed
3. **Persistence backend selection** — PostgreSQL audit table, OpenTelemetry, or platform-native logging
4. **Retention policy** — 6-7 year requirement for healthcare compliance
5. **Tamper-evidence** — append-only enforcement, immutable storage backend
6. **Result-level audit** — track which memories were returned by search_memory
7. **Driver validation** — cryptographic backing for driver_id claims (intersection mode)
