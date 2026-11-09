# Discover the global config file via XDG_CONFIG_HOME, defaulting to no layers if absent

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-05 | accepted |

## Context

Besides the per-project `ask.toml` (see `docs/adr/0003-use-toml-for-configuration.md`), Ask
needs a user-wide config file defining shared layers (e.g. their `bind_mounts`) that projects can
opt into by name. Ask needs a predictable, conventional place to find this file without requiring
explicit configuration, and needs to decide what happens for users who haven't created one yet.

## Decision

Ask resolves the global config file at `$XDG_CONFIG_HOME/ask/config.toml`, falling back to
`~/.config/ask/config.toml` if `XDG_CONFIG_HOME` is unset or empty. If the resolved path doesn't
exist, it is treated as an empty config (no layers defined) rather than an error.

## Consequences

- Matches the broader convention (XDG base directory-style config discovery) that other CLI
  tools use, without requiring a first-run setup step.
- A project referencing a layer that isn't defined (whether because the global config is
  missing entirely or just missing that layer) fails with the same clear "unknown layer" error
  from `ask.manifest.resolve_bind_mounts`, rather than a raw file-not-found error.
- Only `XDG_CONFIG_HOME` is consulted; no other XDG base directory variables (such as
  `XDG_CONFIG_DIRS`) are.
