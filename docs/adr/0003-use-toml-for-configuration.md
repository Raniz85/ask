# Use TOML for configuration files

## Status
| date       | state    |
|------------|----------|
| 2026-11-05 | accepted |

## Context

Ask needs both a per-project configuration (`ask.toml`) describing the distribution and layers
for that project's environment, and a global configuration (`global.toml`) describing user-wide
defaults and layer definitions shared across projects. The format needs to be easy to hand-edit,
have a stable reader available without extra dependencies, and ideally already be familiar from
other tooling (e.g. `pyproject.toml`, `Cargo.toml`).

## Decision

Configuration for Ask — both project-local (`ask.toml`) and global (`global.toml`) — is written
in TOML. Reading uses Python's standard library `tomllib`. If writing TOML is ever needed, it
goes through an explicit TOML-writing dependency rather than hand-rolled string serialization.

## Consequences

- No extra dependency for reading on Python `>=3.11` (`tomllib` is stdlib).
- Consistent, familiar format already used across the Python ecosystem and other infra tools.
- TOML has no native anchors/includes, so any sharing of config fragments between `global.toml`
  and `ask.toml` (e.g. layer definitions) is Ask's responsibility to resolve, not the format's.
