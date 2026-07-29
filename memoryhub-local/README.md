# memoryhub-local

Persistent, versioned, searchable memory for AI agents -- no infrastructure required.

`memoryhub-local` is the personal edition of [MemoryHub](https://github.com/redhat-ai-americas/memory-hub). It gives AI agents the same memory tool surface as the cluster edition, backed by a local SQLite database instead of PostgreSQL. No API keys, no database servers, no background services.

## Quickstart

```bash
pip install "memoryhub[local]"
claude mcp add memoryhub -- memoryhub mcp
```

That's it. Start a new Claude Code session and your agent has persistent memory.

On first run, the embedding model downloads automatically (~200MB one-time download). Subsequent starts are fast.

### Install from source

If the packages aren't on PyPI yet (e.g. you're working from a feature branch):

```bash
git clone https://github.com/redhat-ai-americas/memory-hub.git
cd memory-hub
pip install -e memoryhub-local -e memoryhub-cli -e sdk
claude mcp add memoryhub -- memoryhub mcp
```

## Scope: one project vs all projects

The Quickstart command registers the MCP server for the current project only (`--scope local`, the default). Other projects are unaffected.

To enable MemoryHub in **all** your projects, register it at user scope instead:

```bash
claude mcp add --scope user memoryhub -- memoryhub mcp
```

To remove it from a single project (or globally, if registered at user scope):

```bash
claude mcp remove memoryhub
```

The three scopes, in priority order:

| Scope | Where it's stored | Shared with team? |
|-------|-------------------|-------------------|
| `local` (default) | `.claude/settings.local.json` | No (gitignored) |
| `project` | `.mcp.json` | Yes (committed) |
| `user` | `~/.claude/settings.json` | No (global) |

## Verify it works

```bash
memoryhub doctor
```

```
MemoryHub Doctor

  Edition:    personal
  Database:   ~/.local/share/memoryhub/memoryhub.db (12.0 KB)
  WAL mode:   yes
  Migration:  e05b0e59db47
  Memories:   0
  Model:      granite-embedding-small-english-r2-onnx
  Embed dim:  384
```

## MCP tool surface

The MCP server exposes four tools to agents. These are the same tools as the cluster edition -- agents cannot tell the difference.

| Tool | Purpose |
|------|---------|
| `register_session` | Session setup (no-op locally). Runs on-connect dreaming to extract facts from unprocessed threads. |
| `memory(action=...)` | All memory operations: search, read, list, write, update, delete, similar, relationships, relate, report, reconstruct, status |
| `thread(action=...)` | Conversation threads: create, append, get, list, archive, delete, extract |
| `admin_memory(action=...)` | Content moderation: search, quarantine, restore, hard_delete |

Cluster-only actions (projects, curation rules, promote/graduate, focus) return a graceful "not available in personal edition" message rather than failing.

## CLI commands

| Command | Description |
|---------|-------------|
| `memoryhub mcp` | Start the local MCP server (stdio). This is what Claude Code calls. |
| `memoryhub doctor` | Health check: database status, model, migrations, memory count |
| `memoryhub dream -m <model>` | Extract facts from threads using a local LLM |

### Offline extraction with `dream`

The `dream` command extracts facts from conversation threads using an OpenAI-compatible LLM endpoint. Designed for Ollama but works with any compatible API.

```bash
pip install "memoryhub[local,dream]"    # adds httpx dependency

memoryhub dream --model llama3.2                          # Ollama (default)
memoryhub dream --model gemini-2.0-flash \
    --url https://generativelanguage.googleapis.com/v1beta/openai \
    --api-key $GEMINI_API_KEY                             # Gemini
memoryhub dream --dry-run --model llama3.2                # preview pending threads
```

## How it works

- **Storage**: SQLite with WAL mode at `~/.local/share/memoryhub/memoryhub.db`
- **Embeddings**: IBM Granite Embedding Small English R2 (ONNX, 384 dimensions), runs locally on CPU
- **Vector search**: sqlite-vec with brute-force KNN
- **Full-text search**: FTS5
- **Versioning**: every update creates a new version; old versions preserved in history
- **Extraction**: via MCP sampling (agent's own LLM) or `memoryhub dream` with a local LLM

All data lives under `~/.local/share/memoryhub/` (or `$XDG_DATA_HOME/memoryhub/`).

## Troubleshooting

### NumPy / scipy crash on Anaconda

If `memoryhub doctor` or `memoryhub mcp` crashes with `A module that was compiled using NumPy 1.x cannot be run in NumPy 2.x`, the Anaconda base environment has a NumPy version conflict with scipy/sklearn. The fix is to install memoryhub-local in its own venv:

```bash
python3 -m venv ~/.memoryhub-venv
~/.memoryhub-venv/bin/pip install "memoryhub[local]"
claude mcp add memoryhub -- ~/.memoryhub-venv/bin/memoryhub mcp
~/.memoryhub-venv/bin/memoryhub doctor   # verify
```

The venv doesn't need to be activated -- `claude mcp add` takes the full path to the binary.

## Notes

- A `[transformers] PyTorch was not found` warning may appear on startup. This is harmless -- only the tokenizer is used, not PyTorch models.
- The embedding model (~200MB) downloads once on first start. Subsequent starts use the cached model.

## Requirements

- Python 3.10+
- Claude Code (for MCP integration)
- Ollama (optional, for `memoryhub dream`)

## License

Apache-2.0. Part of the [MemoryHub](https://github.com/redhat-ai-americas/memory-hub) project.
