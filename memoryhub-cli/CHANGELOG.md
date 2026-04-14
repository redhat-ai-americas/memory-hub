# Changelog — memoryhub-cli

All notable changes to the `memoryhub-cli` package.

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
