# MemoryHub Manage

Manage MemoryHub graph, curation, and project operations via the CLI. This skill wraps cold-path operations that are used less frequently than search/write/read.

Parse the user's natural language request to determine which operation they need, then run the appropriate CLI command via Bash.

## Setup

The CLI must be installed and configured. Verify with:

```bash
memoryhub session status
```

If not configured, the user needs `~/.config/memoryhub/api-key` set (or run `memoryhub login` for OAuth). The server URL must be set via `MEMORYHUB_URL` env var or `~/.config/memoryhub/config.json`.

## Operations

### Graph: Create relationship

Create a directed edge between two memories.

```bash
memoryhub graph relate <source-id> <target-id> <relationship-type> [-p PROJECT_ID] [-o json]
```

Common relationship types: `derived_from`, `supersedes`, `related_to`, `contradicts`, `supports`, `refines`

Example:
```bash
memoryhub graph relate abc-123 def-456 derived_from
```

### Graph: List relationships

Query relationships for a memory node.

```bash
memoryhub graph list <memory-id> [--type TYPE] [--direction both|outgoing|incoming] [-p PROJECT_ID] [-o json]
```

Example:
```bash
memoryhub graph list abc-123 --direction outgoing --type supports
```

### Graph: Find similar

Find near-duplicate memories by cosine similarity.

```bash
memoryhub graph similar <memory-id> [--threshold 0.80] [--max 10] [-p PROJECT_ID] [-o json]
```

Example:
```bash
memoryhub graph similar abc-123 --threshold 0.85 --max 5
```

### Curation: Report contradiction

Flag a memory as contradicting observed behavior.

```bash
memoryhub curation report <memory-id> "<observed-behavior>" [--confidence 0.7] [-p PROJECT_ID] [-o json]
```

Example:
```bash
memoryhub curation report abc-123 "Project now uses FastAPI, not Flask" --confidence 0.9
```

### Curation: Resolve contradiction

Close a reported contradiction.

```bash
memoryhub curation resolve <contradiction-id> --action <resolution> [--note "..."] [-o json]
```

Resolution actions: `accept_new`, `keep_old`, `mark_both_invalid`, `manual_merge`

Example:
```bash
memoryhub curation resolve cont-789 --action accept_new --note "Confirmed migration to FastAPI"
```

### Curation: Manage rules

Create or update a curation rule.

```bash
memoryhub curation rule <name> [--tier embedding|regex] [--action flag|block|quarantine] [--threshold 0.9] [--scope-filter SCOPE] [--priority 10] [--enabled/--disabled] [-o json]
```

Example:
```bash
memoryhub curation rule no-duplicate-decisions --tier embedding --action block --threshold 0.95
```

### Project: List projects

```bash
memoryhub project list [--filter mine|all] [-o json]
```

### Project: Create project

```bash
memoryhub project create <name> [--description "..."] [--invite-only] [-o json]
```

Example:
```bash
memoryhub project create my-service --description "Microservice migration project" --invite-only
```

### Project: Add member

```bash
memoryhub project add-member <project-name> <user-id> [--role member|admin] [-o json]
```

Example:
```bash
memoryhub project add-member my-service alice --role admin
```

### Project: Remove member

```bash
memoryhub project remove-member <project-name> <user-id> [-o json]
```

## Intent mapping

Match the user's request to an operation:

- "find similar memories" / "deduplicate" -> `memoryhub graph similar <id>`
- "link these memories" / "create a relationship" -> `memoryhub graph relate <src> <tgt> <type>`
- "show relationships" / "what's connected to" -> `memoryhub graph list <id>`
- "report a contradiction" / "this memory is wrong" -> `memoryhub curation report <id> "<behavior>"`
- "resolve contradiction" / "close this report" -> `memoryhub curation resolve <id> --action <action>`
- "add a curation rule" / "block duplicates" -> `memoryhub curation rule <name> ...`
- "list projects" / "my projects" -> `memoryhub project list`
- "create a project" -> `memoryhub project create <name>`
- "add someone to a project" -> `memoryhub project add-member <proj> <user>`
- "remove from project" -> `memoryhub project remove-member <proj> <user>`

## Output handling

Use `--output json` (`-o json`) when you need to process the result programmatically (e.g., extracting an ID for a follow-up command). Use default table output for human-readable display. Use `--output quiet` (`-o quiet`) to suppress output when chaining commands.

If the user's request is ambiguous, ask which specific operation they want before running commands.
