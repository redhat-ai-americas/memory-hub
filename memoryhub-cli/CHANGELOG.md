# Changelog — memoryhub-cli

All notable changes to the `memoryhub-cli` package.

## [0.8.0] — 2026-06-03

- **New commands (#256)**: `memoryhub promote`, `memoryhub graduate`,
  `memoryhub checkpoint`, and `memoryhub describe` for memory lifecycle
  management.
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
