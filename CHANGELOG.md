# CHANGELOG


## v0.0.2 (2026-03-23)

### Bug Fixes

- **release**: Run go mod tidy in agentic-adoption-scan dir and add goreleaser dry-run to PR checks
  ([`72e68fc`](https://github.com/posit-dev/eng-effectiveness-metrics-tools/commit/72e68fc6ea948169b330d04c0ab9c18e7c6d81db))

The before hook was running 'go mod tidy' in the repo root where there is no go.mod file. Fix by
  specifying dir: agentic-adoption-scan for the hook.

Add a PR checks workflow that runs goreleaser in snapshot mode to catch release configuration errors
  before they reach main.

https://claude.ai/code/session_01HRudjsZUpDGNzKE8Bq6Pa3

- **release**: Use go mod tidy -C flag instead of invalid hook object form
  ([`b5453d1`](https://github.com/posit-dev/eng-effectiveness-metrics-tools/commit/b5453d1c14506bb7cb5fd9395f987c92d290c64e))

goreleaser v2 before.hooks only accepts plain strings, not objects with cmd/dir fields. Use 'go mod
  tidy -C agentic-adoption-scan' (Go 1.21+ flag) to run the command in the correct directory.

https://claude.ai/code/session_01HRudjsZUpDGNzKE8Bq6Pa3


## v0.0.1 (2026-03-23)

### Bug Fixes

- Correct PyPI author email to elliot.murphy@posit.co
  ([`648949d`](https://github.com/posit-dev/eng-effectiveness-metrics-tools/commit/648949d39c65808f892e2e534cb3926702667676))

https://claude.ai/code/session_016xpt8jgRxgSg3yinfupCb1

### Chores

- Switch to python-semantic-release for automated releases
  ([`0bea1ff`](https://github.com/posit-dev/eng-effectiveness-metrics-tools/commit/0bea1ffc584ddb71a284d4d5c8088f500c601fd9))

Replaces release-please (which required a separate release PR) with python-semantic-release,
  matching the posit-dev/vip release strategy. Every merge to main now automatically releases if
  commits include feat: or fix: prefixes. The tag push triggers a separate publish workflow for
  goreleaser binaries and PyPI wheels.

- Add pyproject.toml with semantic-release config - Rewrite .github/workflows/release.yml
  (semantic-release on push to main) - Add .github/workflows/publish.yml (goreleaser + PyPI on tag
  push) - Add .github/workflows/pr-title.yml (enforce conventional commit PR titles) - Remove
  release-please workflow and config files - Update README with new release flow and setup
  instructions

https://claude.ai/code/session_016xpt8jgRxgSg3yinfupCb1
