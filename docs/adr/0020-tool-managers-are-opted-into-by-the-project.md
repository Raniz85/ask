# Tool managers are opted into by the project

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-10 | accepted |

## Context

`docs/adr/0017-hand-tool-installation-to-project-tool-managers.md` enabled every known tool
manager by default and let layers or `ask.toml` opt out. Whether a project uses a tool manager
is a property of the project, not of the user's environment: a `mise.toml` that the project does
not intend Ask to use should not be trusted and installed. Since
`docs/adr/0018-select-the-environment-through-flavours.md`, layers belong to flavours and
describe the user's environment.

## Decision

This supersedes the parts of ADR 0017 that enable tool managers by default and let layers opt
out of them. The rest of ADR 0017 still applies.

- No tool manager is used unless `ask.toml` lists it, e.g. `tool_managers = ["mise"]`.
- Flavour layers cannot list tool managers.
- Names prefixed with `-` are rejected, as there is nothing to remove them from.
- A listed tool manager is still only used when its config files exist in the project.

## Consequences

- A project's tool manager config is only trusted and installed when the project asks for it.
- Projects that relied on mise being used by default must add `tool_managers = ["mise"]` to
  their `ask.toml`.
