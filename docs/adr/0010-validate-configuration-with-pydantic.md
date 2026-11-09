# Validate configuration with Pydantic

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-09 | accepted |

## Context

`docs/adr/0006-use-dataclasses-for-configuration.md` left open how raw TOML dicts are turned
into the configuration dataclasses with reasonable error messages. Hand-written parsing gave
tracebacks on wrongly shaped input and silently ignored unknown keys and typos. We compared
Pydantic and cattrs on the same invalid input: Pydantic reported every problem with its path
and a readable message, cattrs produced noticeably worse messages.

No TOML parser we looked at (`tomllib`, `rtoml`, `tomlkit`) renders source snippets for syntax
errors, so ADR 0003 stands and snippets are rendered by Ask from `tomllib`'s line and column.

## Decision

Parsed TOML is validated and deserialized with Pydantic's `TypeAdapter`, applied to the
existing standard-library dataclasses. Unknown keys are rejected, and fields use Pydantic's
strict types so TOML values are not coerced (e.g. `"1000"` is not accepted as an integer).
Pydantic errors are translated into Ask's own `ConfigError`, so Pydantic stays an
implementation detail of loading.

## Consequences

- The dataclasses remain the single schema, in line with ADR 0006.
- New runtime dependency on `pydantic` (and `pydantic-core`).
- All structural problems in a file are reported at once, with their TOML paths.
- Rules that depend on Ask's own registries (known shells, agents, distributions) are checked
  separately, after structural validation.
