# Tool Generator

Generate new MCP tools with best practices and comprehensive tests.

## Usage

```bash
fips-agents generate tool <name> [options]
```

## Options

- `--async` / `--sync` - Generate async or sync function (default: async)
- `--with-context` - Include FastMCP Context parameter for logging
- `--with-auth` - Include authentication decorator
- `--description "..."` - Tool description
- `--read-only` - Mark as read-only operation
- `--open-world` - Mark as open-world (can interact with external systems)

## Examples

### Basic Sync Tool
```bash
fips-agents generate tool echo --sync --description "Echo a message"
```

### Async Tool with Context
```bash
fips-agents generate tool fetch-data --async --with-context
```

### Authenticated Tool
```bash
fips-agents generate tool admin-action --async --with-auth --with-context
```

## Generated Files

- `src/tools/<name>.py` - Tool implementation
- `tests/tools/test_<name>.py` - Tool tests

## Template Variables

- `component_name` - Function name (snake_case)
- `description` - Tool description
- `async` - Boolean for async/sync
- `with_context` - Include Context parameter
- `with_auth` - Include auth decorator
- `read_only` - Mark as read-only
- `idempotent` - Mark as idempotent
- `open_world` - Mark as open-world
- `params` - Parameter definitions
- `project_name` - Project name
