# Treat ask.toml as a self-contained, trusted layer

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-09 | accepted |

## Context

Layers are defined in the global config and pulled into a project by name from `ask.toml`.
Only some layer options (bind mounts, packages) could be set in `ask.toml` directly, so a
project needing, for example, an agent required a single-use layer in the global config. A
project's environment should be describable by its `ask.toml` alone.

`ask.toml` usually lives in the project's repository, so it may be written by someone other
than the user running Ask. Several layer options reach outside the container: bind mounts can
expose any host path, and agents mount the user's agent credentials and configuration.

## Decision

The manifest is a layer: `Manifest` inherits from `Layer`, so every option a layer supports is
also accepted at the top level of `ask.toml`. When resolving a project, the manifest is applied
as the first layer, followed by the named layers in the order they are listed.

`ask.toml` is trusted to the same degree as the global config, comparable to a project's
`Makefile` or build script. Ask does not restrict which layer options a project file may use.

## Consequences

- A project can be fully described by its `ask.toml`, without matching global layers.
- New layer options become available in `ask.toml` automatically, and validation of layer
  options applies to both files.
- Entering an environment from an untrusted repository can expose host files and agent
  credentials to that environment; users should review `ask.toml` before use, as they would a
  build script.
- Validation problems are reported in field order, so inherited layer fields are reported
  before manifest-only fields such as `distribution`.
