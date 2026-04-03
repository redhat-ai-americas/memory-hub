# Middleware Generator

Generate new MCP middleware for cross-cutting concerns.

## Usage

```bash
fips-agents generate middleware <name> [options]
```

## Options

- `--async` - Generate async middleware (default: true)
- `--hook-type <type>` - Hook point (before_tool, after_tool, on_error)
- `--description "..."` - Middleware description

## Examples

### Request Logger
```bash
fips-agents generate middleware request-logger --description "Log all requests"
```

### Rate Limiter
```bash
fips-agents generate middleware rate-limiter --description "Limit request rate"
```

### Custom Auth
```bash
fips-agents generate middleware custom-auth --description "Custom authentication"
```

## Generated Files

- `src/middleware/<name>.py` - Middleware implementation
- `tests/middleware/test_<name>.py` - Middleware tests

## Template Variables

- `component_name` - Function name (snake_case)
- `description` - Middleware description
- `async` - Boolean for async/sync (usually async)
- `hook_type` - Execution hook point
- `project_name` - Project name

## Middleware Patterns

Middleware wraps tool execution with this signature:

```python
async def middleware_name(
    ctx: Context,
    next_handler: Callable,
    *args: Any,
    **kwargs: Any
) -> Any:
    # Pre-execution logic
    result = await next_handler(*args, **kwargs)
    # Post-execution logic
    return result
```

## Common Use Cases

1. **Logging** - Track invocations, timing, errors
2. **Authentication** - Verify tokens, check permissions
3. **Rate Limiting** - Throttle requests per user/tool
4. **Caching** - Cache tool results
5. **Metrics** - Collect performance metrics
6. **Error Handling** - Transform or log errors
7. **Request Validation** - Validate common requirements
