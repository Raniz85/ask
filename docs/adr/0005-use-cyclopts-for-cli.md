# Build the CLI command structure with cyclopts

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-05 | accepted |

## Context

Ask is driven as a CLI with subcommands (`ask init`, `ask enter`, ...), each taking its own
arguments and options. We want subcommand definitions to read as plain, type-annotated Python
functions rather than requiring a separate argument-parser schema (as with stdlib `argparse`) or
decorator-heavy boilerplate.

## Decision

The CLI command tree is built with [cyclopts](https://cyclopts.readthedocs.io), which derives
commands, arguments, and help text from type-annotated function signatures.

## Consequences

- Command definitions stay close to plain Python functions, consistent with using type
  annotations throughout the codebase.
- Less boilerplate than `argparse`, with built-in subcommand and help support.
- Adds a third-party dependency; cyclopts is younger and less widely used than `click`/`typer`,
  so its API may move faster between versions.
