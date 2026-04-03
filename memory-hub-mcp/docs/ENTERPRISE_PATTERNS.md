# Enterprise Patterns for FastMCP Servers

This guide demonstrates best practices for building production-ready, enterprise-grade MCP servers using FastMCP 2.11.0+. It covers patterns essential for FIPS-compliant government and enterprise environments.

## Table of Contents

1. [Overview](#overview)
2. [Multi-Tenant Architecture](#multi-tenant-architecture)
3. [Authentication &amp; Authorization](#authentication--authorization)
4. [Audit Logging &amp; Compliance](#audit-logging--compliance)
5. [State Management](#state-management)
6. [Progress Reporting](#progress-reporting)
7. [Security Best Practices](#security-best-practices)
8. [Complete Example](#complete-example)

## Overview

Enterprise MCP servers require:

- **Multi-tenancy**: Data isolation between tenants
- **Security**: Authentication, authorization, and encryption
- **Compliance**: Comprehensive audit logging
- **Reliability**: Error handling and progress reporting
- **Scalability**: Efficient resource usage and state management

## Multi-Tenant Architecture

### Tenant Isolation Pattern

Extract tenant ID from JWT claims and use it to filter all data access:

```python
async def check_tenant_access(ctx: Context, resource_tenant_id: str) -> bool:
    """Verify user has access to resources in the specified tenant."""
    user_tenant_id = ctx.get_state("tenant_id")

    if not user_tenant_id:
        await ctx.warning("No tenant context found for user")
        return False

    if user_tenant_id != resource_tenant_id:
        await ctx.warning(
            f"Tenant mismatch: user={user_tenant_id}, resource={resource_tenant_id}"
        )
        return False

    return True
```

**Implementation:**

1. Middleware extracts `tenant_id` from JWT and stores in Context state
2. All database queries must filter by `tenant_id`
3. Every data access validates tenant ownership
4. Audit logs record tenant context

**See:** `src/middleware/examples/state_middleware.py` for middleware implementation.

## Authentication & Authorization

### Token-Based Authentication

Use FastMCP's `get_access_token()` for accessing user credentials:

```python
from fastmcp.server.dependencies import get_access_token

async def get_user_info() -> dict:
    """Get authenticated user information."""
    token = get_access_token()

    if token is None:
        return {"authenticated": False}

    return {
        "user_id": token.claims.get("sub"),
        "tenant_id": token.claims.get("tenant_id"),
        "scopes": token.scopes,
    }
```

### Scope-Based Authorization

Check fine-grained permissions before operations:

```python
from core.auth import get_token_scopes

async def check_permission(ctx: Context, required_scope: str) -> bool:
    """Check if user has required permission scope."""
    scopes = ctx.get_state("scopes") or get_token_scopes()

    if required_scope in scopes:
        return True

    user_id = ctx.get_state("user_id") or "unknown"
    await ctx.warning(f"Permission denied: {user_id} lacks scope {required_scope}")
    return False
```

**Common Scopes:**

- `read:documents` - Read access to documents
- `write:documents` - Create/update documents
- `delete:documents` - Delete documents
- `admin` - Administrative access
- `write:classified` - Access to classified data

**See:** `src/core/auth.py` for complete authentication utilities.

## Audit Logging & Compliance

### Comprehensive Audit Records

Create structured audit logs for compliance tracking:

```python
@dataclass
class AuditRecord:
    """Structured audit record for compliance tracking."""
    action: str                    # create, read, update, delete
    resource_type: str             # document, user, config
    resource_id: str | None
    user_id: str
    tenant_id: str | None
    timestamp: str
    ip_address: str
    status: str                    # success, failed, denied
    details: dict
```

### Audit Logging Pattern

Log before and after operations, including failures:

```python
async def create_audit_record(
    ctx: Context,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    status: str = "success",
    details: dict | None = None,
) -> AuditRecord:
    """Create comprehensive audit record."""
    user_id = ctx.get_state("user_id") or "anonymous"
    tenant_id = ctx.get_state("tenant_id")
    timestamp = ctx.get_state("request_timestamp")

    # Get client IP from headers
    headers = get_http_headers()
    ip_address = headers.get("x-forwarded-for", "unknown").split(",")[0].strip()

    audit = AuditRecord(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        tenant_id=tenant_id,
        timestamp=timestamp,
        ip_address=ip_address,
        status=status,
        details=details or {},
    )

    await ctx.info(
        f"AUDIT: {user_id}@{tenant_id} {action} {resource_type}:{resource_id} "
        f"from {ip_address} - {status}"
    )

    # In production: persist audit to database or SIEM
    return audit
```

**Best Practices:**

- Log all data access (create, read, update, delete)
- Include user, tenant, timestamp, and IP address
- Log both successful and failed operations
- Include reason for denials
- Persist to tamper-proof audit log store

**See:** `src/tools/examples/enterprise_patterns.py` for complete audit implementation.

## State Management

### Middleware State Pattern

Use middleware to extract and store request context:

```python
class StateManagementMiddleware(Middleware):
    """Extract auth info and store in Context state."""

    async def on_call_tool(self, context, call_next):
        # Extract from token
        token = get_access_token()
        if token:
            context.fastmcp_context.set_state("user_id", token.claims.get("sub"))
            context.fastmcp_context.set_state("tenant_id", token.claims.get("tenant_id"))
            context.fastmcp_context.set_state("scopes", list(token.scopes))

        # Set request metadata
        context.fastmcp_context.set_state("request_timestamp", datetime.utcnow().isoformat())

        return await call_next(context)
```

### Accessing State in Tools

Tools can access state set by middleware:

```python
@mcp.tool
async def get_tenant_data(resource_type: str, ctx: Context) -> dict:
    """Get tenant-specific data with automatic isolation."""
    tenant_id = ctx.get_state("tenant_id")
    user_id = ctx.get_state("user_id")

    if not tenant_id:
        raise ToolError("No tenant context available")

    # Query database filtered by tenant_id
    return {"tenant_id": tenant_id, "data": [...]}
```

**Key Points:**

- State is request-scoped (not shared between requests)
- Middleware sets state before tool execution
- Tools read state for user/tenant context
- Eliminates need to parse tokens in every tool

**See:** `src/middleware/examples/state_middleware.py` for complete examples.

## Progress Reporting

### Long-Running Operations

Report progress for bulk operations:

```python
async def bulk_process_documents(
    document_ids: list[str],
    operation: str,
    ctx: Context,
) -> dict:
    """Process multiple documents with progress reporting."""
    total = len(document_ids)

    # Report initial progress
    await ctx.report_progress(progress=0, total=total)

    for i, doc_id in enumerate(document_ids):
        # Process document...

        # Report progress every 10 items
        if (i + 1) % 10 == 0 or (i + 1) == total:
            await ctx.report_progress(progress=i + 1, total=total)
            await ctx.info(f"Progress: {i + 1}/{total}")

    # Final progress
    await ctx.report_progress(progress=total, total=total)

    return {"processed": total}
```

**Best Practices:**

- Report at start (0%) and end (100%)
- Update every N items or percentage threshold
- Combine with logging for visibility
- Handle errors without breaking progress tracking

**See:** `src/tools/examples/advanced_examples.py` for progress reporting examples.

## Security Best Practices

### 1. Input Validation

Use Pydantic Field constraints:

```python
async def create_document(
    title: Annotated[str, Field(min_length=1, max_length=200)],
    classification: Annotated[str, Field(pattern="^(public|internal|confidential|secret)$")],
    ctx: Context,
) -> dict:
    """Create document with validated inputs."""
    # Input already validated by Pydantic
```

### 2. Permission Checks

Always check permissions before operations:

```python
if not await check_permission(ctx, "write:documents"):
    _audit = await create_audit_record(ctx, "create", "document", status="denied")
    raise ToolError("Permission denied")
```

### 3. Tenant Verification

Verify tenant ownership for all data access:

```python
if not await check_tenant_access(ctx, document["tenant_id"]):
    _audit = await create_audit_record(ctx, "read", "document", status="denied")
    raise ToolError("Access denied: wrong tenant")
```

### 4. Security Classification

Implement additional checks for sensitive data:

```python
if classification in ["confidential", "secret"]:
    if not await check_permission(ctx, "write:classified"):
        raise ToolError("Requires 'write:classified' scope")
```

### 5. IP Logging

Always log client IP for audit trails:

```python
headers = get_http_headers()
ip_address = headers.get("x-forwarded-for", "unknown").split(",")[0].strip()
```

## Complete Example

The `enterprise_patterns.py` module demonstrates a complete enterprise implementation:

**Tools:**

1. `fetch_tenant_document` - Multi-tenant document retrieval with audit
2. `bulk_process_documents` - Batch processing with progress reporting
3. `create_secure_document` - Document creation with classification
4. `get_user_activity_summary` - User context and permissions

**Utilities:**

- `create_audit_record` - Structured audit logging
- `check_tenant_access` - Tenant isolation verification
- `check_permission` - Scope-based authorization

**Pattern Flow:**

```
Request → StateManagementMiddleware (extracts auth/tenant)
       → Tool (checks permission)
       → Tool (verifies tenant access)
       → Tool (performs operation)
       → Tool (creates audit record)
       → Response
```

**See:** `src/tools/examples/enterprise_patterns.py` for complete implementation.

## FIPS Compliance Considerations

For FIPS 140-2/140-3 compliance:

1. **Cryptography**: Use FIPS-approved algorithms (AES, RSA, SHA-256)
2. **TLS**: Require TLS 1.2+ for all communication
3. **Token Validation**: Verify JWT signatures using approved algorithms
4. **Audit Logging**: Maintain tamper-evident audit trails
5. **Data Encryption**: Encrypt sensitive data at rest and in transit
6. **Access Control**: Implement role-based access control (RBAC)

## Testing Enterprise Patterns

Test security and compliance features:

```python
@pytest.mark.asyncio
async def test_tenant_isolation():
    """Verify tenant isolation."""
    # Create mock context with tenant A
    ctx = create_mock_context(tenant_id="tenant_a")

    # Try to access tenant B's document
    with pytest.raises(ToolError, match="Access denied"):
        await fetch_tenant_document("doc_in_tenant_b", ctx=ctx)

@pytest.mark.asyncio
async def test_permission_check():
    """Verify permission enforcement."""
    ctx = create_mock_context(scopes=["read:documents"])

    # Should fail without write scope
    with pytest.raises(ToolError, match="Permission denied"):
        await create_secure_document("Title", "Content", ctx=ctx)
```

## Additional Resources

- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Tools Development Guide](./TOOLS_GUIDE.md)
- [Authentication Utilities](../src/core/auth.py)
- [State Management Middleware](../src/middleware/examples/state_middleware.py)
- [Enterprise Patterns Examples](../src/tools/examples/enterprise_patterns.py)
- [Runtime Dependencies](./TOOLS_GUIDE.md#runtime-dependencies)
