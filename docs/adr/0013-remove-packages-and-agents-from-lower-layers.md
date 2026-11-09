# Remove packages and agents from lower layers with a "-" prefix

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-09 | accepted |

## Context

`docs/adr/0012-merge-layers-in-declaration-order.md` merges layers so later layers override
earlier ones, but a layer can only add packages and agents. A project using a shared global
layer had no way to drop a package or agent it does not want.

## Decision

A package or agent name prefixed with `-` (e.g. `"-git"`, `"-claude"`) removes that package or
agent from the lower layers. Removing something no lower layer adds has no effect.

- Removals only affect lower layers; additions in the same layer are applied after them, so a
  layer listing both `"git"` and `"-git"` installs `git`.
- Packages are removed by name, whichever distribution key they were listed under.
- Removing an agent also drops its merged options and `shared_state`; an agent added again by a
  higher layer starts with neither.
- Removed agents are validated by their name without the prefix. Options given on a removal
  have no effect and produce a warning.

## Consequences

- A project can opt out of parts of a shared layer from its `ask.toml`.
- Package and agent names cannot start with `-`.
- Bind mounts cannot be removed this way.
