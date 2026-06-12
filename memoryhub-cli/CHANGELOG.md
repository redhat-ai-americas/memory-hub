# Changelog — memoryhub-cli

All notable changes to the `memoryhub-cli` package.

## [0.11.0] — 2026-06-12

- **Hook scaffolding**: `memoryhub config init` now generates the full
  hook integration -- `.claude/hooks/load-memories.sh` (portable,
  executable) and `.claude/settings.json` SessionStart entries.
- **Hook script portability**: CLI discovery checks PATH first (pipx/global)
  before project venv paths. JSON parsing uses jq/python3/grep fallback chain.
- **Loading rule refinement**: Rule templates frame hooks as the expected
  path, with manual MCP calls as a degraded fallback.
- **`memoryhub reconstruct`**: Retrieve behavioral memories sorted by
  weight. Supports table, json, quiet, and compact output.
- **`memoryhub admin backfill-entities`**: Run entity extraction on
  memories without extraction_status. Accepts `--limit` and
  `--include-failed`.
- **Thread commands** (from unreleased 0.10.0): `memoryhub thread`
  subgroup with create, append, get, list, archive, extract, fork,
  share, and delete commands.
- **Entity commands** (from unreleased 0.10.0): `memoryhub entity`
  subgroup with list, merge, and rename commands.
- **Session commands** (from unreleased 0.10.0): `memoryhub session`
  subgroup with status, focus, and focus-history commands.
- **Graph commands** (from unreleased 0.10.0): `memoryhub graph`
  subgroup with relate, list, and similar commands.
- **Curation commands** (from unreleased 0.10.0): `memoryhub curation`
  subgroup with report, resolve, and rule commands.
- **Project commands** (from unreleased 0.10.0): `memoryhub project`
  subgroup with list, create, add-member, remove-member, and describe.
- **SDK dependency**: Requires `memoryhub>=0.14.0` (was `>=0.3.0`).

## [0.9.0] — 2026-06-08

- **CLI/SDK parity (#257)**: `memoryhub promote`, `memoryhub graduate`,
  `memoryhub checkpoint`, and `memoryhub project describe` complete
  feature parity with the MCP server.
- **Fix**: Search command `--output` help text now lists `compact` format.
- **Skill**: Added `memoryhub-manage` Claude Code skill for cold-path
  operations (#203 prototype).

## [0.8.0] — 2026-06-03

- **Obsidian export (#245)**: `memoryhub export --format obsidian` generates
  Obsidian-compatible markdown with wikilinks and frontmatter.
- **Hook-aware rule templates**: `memoryhub config init` and
  `memoryhub config regenerate` now generate rule files that check for a
  `<memoryhub-context>` block from SessionStart hooks before falling back
  to the manual `register_session` + `search_memory` flow.

## [0.7.0] — 2026-05-19

- **Content type support (#237)**: Write and search commands accept
  `--content-type` for behavioral memory classification.

## [0.6.0] — 2026-05-07

- **API key authentication (#256)**: The CLI now supports API key auth
  via `MEMORYHUB_API_KEY` env var, `--api-key` flag, or the file at
  `~/.config/memoryhub/api-key`. This enables non-interactive use cases
  like SessionStart hooks.
- **Compact output (#255)**: `--output compact` on search and list commands
  produces content-only text wrapped in `<memoryhub-context>` tags for
  zero-overhead LLM injection.
- **List command**: `memoryhub list` enumerates memories without semantic
  ranking, with cursor-based pagination.
- **Server URL prompt**: `memoryhub config init` now prompts for the
  server URL and saves it to `~/.config/memoryhub/config.json`.

## [0.5.0] — 2026-04-22

- **Structured output (#200)**: Replaced `--json` flag with `--output`
  accepting `table`, `json`, `quiet`, and `compact` formats. All commands
  now return structured JSON envelopes with `--output json`.
- **New sub-apps**: `memoryhub graph` (relate, list, similar),
  `memoryhub curation` (report, resolve), `memoryhub session` (status,
  focus), `memoryhub project` (list, describe, join, leave).
- **Update command**: `memoryhub update` for modifying existing memories
  with version history preservation.
- **Config enhancements**: `--project` and `--non-interactive` flags on
  `memoryhub config init`.

## [0.4.0] — 2026-04-14

- **Admin subcommands (#186)**: Added `memoryhub admin` command group with
  `create-agent`, `list-agents`, `rotate-secret`, and `disable-agent` for
  self-serve agent provisioning via the auth service REST API.
- **`--version` flag**: `memoryhub --version` now prints the installed version.

## [0.3.0] — 2026-04-09

- **Campaign & domain parameter support (#164)**: Added `--project-id` flag to
  search, read, write, delete, and history commands. Added `--domain` flag to
  search and write. When `.memoryhub.yaml` has campaigns configured, `project_id`
  is auto-loaded from the config so the flag can be omitted.

## [0.2.0] — 2026-04-09

- Added campaign enrollment prompt to `memoryhub config init` (#160).
- API key check after config init (#153).

## [0.1.1] — 2026-04-09

- Fix ruff lint errors (import sorting, `Optional` → `X | Y` annotations,
  line length). No functional changes from 0.1.0.

## [0.1.0] — 2026-04-09

- Initial release. Terminal client for MemoryHub with search, read, write,
  delete, and history commands.
- `memoryhub config init` — interactive wizard for generating
  `.memoryhub.yaml` and `.claude/rules/memoryhub-loading.md`.
- `memoryhub config regenerate` — re-render rule file after editing YAML.
- `memoryhub login` — one-time credential setup.
