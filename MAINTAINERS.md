# Maintainers

## Current maintainers

| Name | GitHub | Areas |
|---|---|---|
| Wes Jackson | [@rdwj](https://github.com/rdwj) | All |
| Sanjay Rampal | [@srampal](https://github.com/srampal) | All |
| Katya Romashko | [@KatyaRomashko](https://github.com/KatyaRomashko) | All |
| Ray Carroll | [@raycarroll](https://github.com/raycarroll) | All |

Maintainers have merge rights, deploy access to the shared demo cluster, and own project-board triage. `.github/CODEOWNERS` mirrors this list and must be updated in the same PR as any change here.

## Review and merge rules

- Every PR requires approval from at least **one maintainer** who is not the PR author, plus green CI (`.github/workflows/test.yml`, version-check, secret scanning).
- Trivial changes (typos, doc formatting, CI config fixes) still require one approval but reviewers should not block on them.
- Disagreements are resolved by discussion on the PR/issue; if consensus isn't reached, the maintainer who owns the affected area decides. Design-level disputes should go through a `design_proposal` issue rather than being settled in a PR thread.

## Becoming a maintainer

There is no fixed quota. A contributor is nominated by an existing maintainer after a track record of:

- Several merged PRs of substantial scope, including at least one that required design-doc work
- Constructive review participation on other people's PRs
- Demonstrated familiarity with the project conventions (CLAUDE.md / CONTRIBUTING.md), especially the same-commit consumer audit and mock-vs-real discipline

Nomination happens in a GitHub Discussion; existing maintainers decide by consensus. New maintainers are added to this file, to CODEOWNERS, and to the GitHub team in one PR.

## Stepping down / removal

Maintainers may step down at any time by PR to this file. A maintainer inactive for 6+ months may be moved to an "emeritus" section by consensus of the remaining maintainers. Conduct-related removal follows the [Code of Conduct](CODE_OF_CONDUCT.md) enforcement process.

