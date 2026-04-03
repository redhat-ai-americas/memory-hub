# Resource Generator

Generate new MCP resources for serving static or dynamic content.

## Usage

```bash
fips-agents generate resource <name> [options]
```

## Options

- `--async` / `--sync` - Generate async or sync function (default: async)
- `--uri <uri>` - Custom resource URI (default: `resource://<name>`)
- `--mime-type <type>` - MIME type (default: text/plain)
- `--description "..."` - Resource description

## Examples

### Basic Resource
```bash
fips-agents generate resource config --uri "resource://app-config"
```

### JSON Resource
```bash
fips-agents generate resource user-profile --mime-type "application/json"
```

## Generated Files

- `src/resources/<name>.py` - Resource implementation
- `tests/resources/test_<name>.py` - Resource tests

## Template Variables

- `component_name` - Function name (snake_case)
- `description` - Resource description
- `uri` - Resource URI
- `mime_type` - MIME type for content
- `async` - Boolean for async/sync
- `project_name` - Project name
