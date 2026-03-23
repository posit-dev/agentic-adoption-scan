# CHANGELOG


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
