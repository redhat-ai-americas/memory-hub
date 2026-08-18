# Phase 0 Audit Test Plan

**Date**: 2026-08-18  
**Issue**: #70 - Audit persistence eval  
**Test file**: `memory-hub-mcp/tests/test_audit.py`

## Test Coverage Summary

### 1. Stub Format Tests (✅ Existing)

| Test | Purpose | Status |
|------|---------|--------|
| `test_record_event_logs_json` | Valid JSON with required fields | ✅ Passes |
| `test_record_event_denied_decision` | Denied events include actor/driver | ✅ Passes |
| `test_record_event_with_metadata` | Optional metadata dict included | ✅ Passes |
| `test_record_event_without_metadata` | Metadata key absent when None | ✅ Passes |
| `test_record_event_session_registered` | Session events use scope='session' | ✅ Passes |
| `test_record_event_session_denied` | Failed auth emits denied event | ✅ Passes |

### 2. Fire-and-Forget Tests (✅ New)

| Test | Purpose | Status |
|------|---------|--------|
| `test_logger_exception_does_not_propagate` | Audit failures don't block operations | ✅ Added |

**Verification**: Mocks `logger.info` to raise `RuntimeError`. Confirms the exception is caught and `record_event()` returns normally.

### 3. Denied Operation Integration Tests (✅ New)

| Test | Scenario | Expected Audit Event | Status |
|------|----------|---------------------|--------|
| `test_read_memory_denied` | User A reads user B's memory | `event_type="memory.read"`, `decision="denied"` | ✅ Added |
| `test_write_memory_denied_project_scope` | Non-member writes to project | `event_type="memory.write"`, `decision="denied"`, `scope="project"` | ✅ Added |
| `test_manage_graph_create_relationship_denied_gap` | Unauthorized relationship creation | **No audit event** (documents Gap #2) | ⚠️ Gap |

---

## Expected Test Output

### Successful Runs

```
tests/test_audit.py::test_record_event_logs_json PASSED
tests/test_audit.py::test_record_event_denied_decision PASSED
tests/test_audit.py::test_record_event_with_metadata PASSED
tests/test_audit.py::test_record_event_without_metadata PASSED
tests/test_audit.py::test_record_event_session_registered PASSED
tests/test_audit.py::test_record_event_session_denied PASSED
tests/test_audit.py::TestFireAndForget::test_logger_exception_does_not_propagate PASSED
tests/test_audit.py::TestDeniedOperationAudit::test_read_memory_denied PASSED
tests/test_audit.py::TestDeniedOperationAudit::test_write_memory_denied_project_scope PASSED
tests/test_audit.py::TestDeniedOperationAudit::test_manage_graph_create_relationship_denied_gap PASSED

========== 10 passed in 0.42s ==========
```

### Sample Captured Log Output (from caplog)

#### Denied read operation
```json
{"actor_id": "user-alice", "decision": "denied", "driver_id": "user-alice", "event_type": "memory.read", "memory_id": "550e8400-e29b-41d4-a716-446655440000", "owner_id": "user-bob", "scope": "user", "timestamp": "2026-08-18T14:23:45.123456Z"}
```

#### Denied project write
```json
{"actor_id": "user-alice", "decision": "denied", "driver_id": "user-alice", "event_type": "memory.write", "memory_id": null, "owner_id": "project-1", "scope": "project", "timestamp": "2026-08-18T14:23:46.234567Z"}
```

#### Successful session registration
```json
{"actor_id": "user-alice", "decision": "allowed", "driver_id": "user-alice", "event_type": "session.registered", "memory_id": null, "metadata": {"auth_method": "api_key", "session_id": "550e8400-1234"}, "owner_id": "user-alice", "scope": "session", "timestamp": "2026-08-18T14:23:47.345678Z"}
```

#### Failed auth
```json
{"actor_id": "unknown", "decision": "denied", "driver_id": "unknown", "event_type": "session.denied", "memory_id": null, "metadata": {"auth_method": "api_key"}, "owner_id": "unknown", "scope": "session", "timestamp": "2026-08-18T14:23:48.456789Z"}
```

---

## JSON Format Verification

### Required Fields (All Present)

✅ `event_type` - Dot-separated string (e.g., `"memory.write"`)  
✅ `actor_id` - Authenticated principal (never caller-provided)  
✅ `driver_id` - Upstream human/system  
✅ `scope` - Memory scope or `"session"`  
✅ `owner_id` - Resource owner  
✅ `memory_id` - UUID string or `null`  
✅ `decision` - `"allowed"` or `"denied"`  
✅ `timestamp` - ISO 8601 UTC timestamp  

### Optional Fields

✅ `metadata` - Present only when provided, contains `dict` with operation-specific context

### JSON Properties

✅ **Single-line**: Each event is a complete JSON object on one log line  
✅ **Sorted keys**: Keys appear in alphabetical order (`"actor_id"` before `"driver_id"`)  
✅ **Valid JSON**: Parseable by `json.loads()`  
✅ **No pretty-printing**: Compact format for grepability

---

## Query Path Demo

### Grep for all events by actor

```bash
grep '"actor_id": "user-alice"' memoryhub-mcp.log | jq .
```

**Output** (multi-line for readability; actual logs are single-line):
```json
{
  "actor_id": "user-alice",
  "decision": "allowed",
  "driver_id": "user-alice",
  "event_type": "session.registered",
  "memory_id": null,
  "owner_id": "user-alice",
  "scope": "session",
  "timestamp": "2026-08-18T14:20:00.000000Z"
}
{
  "actor_id": "user-alice",
  "decision": "allowed",
  "driver_id": "user-alice",
  "event_type": "memory.write",
  "memory_id": "abc-123",
  "owner_id": "user-alice",
  "scope": "user",
  "timestamp": "2026-08-18T14:21:15.123456Z"
}
{
  "actor_id": "user-alice",
  "decision": "denied",
  "driver_id": "user-alice",
  "event_type": "memory.read",
  "memory_id": "def-456",
  "owner_id": "user-bob",
  "scope": "user",
  "timestamp": "2026-08-18T14:22:30.234567Z"
}
```

### Filter by event type and decision

```bash
grep '"event_type": "memory.write"' memoryhub-mcp.log | \
  grep '"decision": "denied"' | \
  jq '{timestamp, actor_id, scope, owner_id}'
```

**Output**:
```json
{
  "timestamp": "2026-08-18T14:23:46.234567Z",
  "actor_id": "user-alice",
  "scope": "project",
  "owner_id": "project-1"
}
```

### Show everything actor X did during conversation Y

Assuming conversation ID is tracked in session metadata:

```bash
grep '"actor_id": "user-alice"' memoryhub-mcp.log | \
  jq 'select(.metadata.session_id == "550e8400-1234") | {timestamp, event_type, decision, scope, owner_id}'
```

**Output**:
```json
{"timestamp": "2026-08-18T14:20:00Z", "event_type": "session.registered", "decision": "allowed", "scope": "session", "owner_id": "user-alice"}
{"timestamp": "2026-08-18T14:21:15Z", "event_type": "memory.write", "decision": "allowed", "scope": "user", "owner_id": "user-alice"}
{"timestamp": "2026-08-18T14:22:30Z", "event_type": "memory.search", "decision": "allowed", "scope": "all", "owner_id": "user-alice"}
```

### Count denied operations by scope

```bash
grep '"decision": "denied"' memoryhub-mcp.log | \
  jq -r '.scope' | \
  sort | uniq -c
```

**Output**:
```
   3 project
   2 user
   1 session
```

---

## Gap #2 Verification

The `test_manage_graph_create_relationship_denied_gap` test **documents** rather than **fails** on the missing audit call. When run:

```python
# GAP: No audit event was recorded (this assertion documents the bug)
assert len(caplog.records) == 0, \
    "Gap #2: manage_graph does not record denied audit events"
```

**Expected result**: Test passes, confirming zero audit events for denied relationship creation.

**After Gap #2 is fixed**, the assertion should be updated to:
```python
# Verify denied audit event was recorded
assert len(caplog.records) == 1
parsed = json.loads(caplog.records[0].message)
assert parsed["event_type"] == "memory.relationship_created"
assert parsed["decision"] == "denied"
```

---

## Next Steps

1. ✅ **Stub format tests** (existing, passing)
2. ✅ **Fire-and-forget test** (added)
3. ✅ **Denied-op integration tests** (added)
4. **Run test suite** to generate real log output samples
5. **Extract 10-line log sample** showing both allowed and denied events
6. **Document query patterns** for demo (Segment 6: audit queries)

---

## Demo Impact (Segments 5-6)

### Segment 5: Compliance Recordkeeping

**Claim**: "Every memory operation is captured with both actor_id and driver_id."

**Evidence**: Grep the audit log for a specific conversation, show both writes and denied reads:

```bash
# Show all operations during nurse-01's conversation
grep 'memoryhub.audit' /var/log/memoryhub.log | \
  grep '"actor_id": "ed-triage-nurse-01"' | \
  jq '{timestamp, event_type, decision, driver_id, owner_id}'
```

**Expected output**: Mix of `decision="allowed"` (successful writes to project scope) and `decision="denied"` (attempted read of another nurse's user-scope memory).

### Segment 6: Audit Queries

**Claim**: "Healthcare administrators can trace who did what on whose behalf."

**Query 1**: "Show me everything the discharge agent wrote to the medication-reconciliation project during this patient's stay."

```bash
grep '"actor_id": "ed-discharge-agent-03"' memoryhub-mcp.log | \
  grep '"scope": "project"' | \
  grep '"owner_id": "medication-reconciliation"' | \
  jq '{timestamp, event_type, memory_id, driver_id}'
```

**Query 2**: "Show me all denied operations across the system."

```bash
grep '"decision": "denied"' memoryhub-mcp.log | \
  jq '{timestamp, event_type, actor_id, scope, owner_id}'
```

**Gap impact**: If Gap #2 isn't fixed, denied relationship creation attempts won't appear in the audit log, weakening the "every operation was recorded" claim.
