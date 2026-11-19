# Select the environment through flavours

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-10 | accepted |

## Context

`ask.toml` named the distribution and the global layers to use, so every project had to repeat
choices that really belong to the user's environment rather than to the project. The user
setting up the environment, not the project, decides which distribution, shell and user to use.
Projects should still be able to say what they need, and `ask.toml` is often written by
someone other than the user running Ask.

## Decision

This supersedes `docs/adr/0011-ask-toml-is-a-self-contained-trusted-layer.md`, the "missing file"
part of `docs/adr/0007-xdg-global-config-discovery.md`, and the note on distribution keys in
`docs/adr/0013-remove-packages-and-agents-from-lower-layers.md`.

- The global config defines named **flavours** under `flavors`. A flavour holds the
  `distribution`, `shell`, `user` and its own `layers`. There are no layers outside flavours.
- A flavour is written in place (`[flavors.debian]`) or in its own file (`flavors.arch =
  "arch.toml"`), resolved relative to the global config's directory. Problems in a flavour file
  are reported against that file.
- A flavour applies to a project when one of its `when.path` regexes fully matches the project's
  absolute directory. A leading `~` in a regex stands for the escaped home directory. When no
  flavour matches, the one with `default = true` applies. Several matching flavours, several
  defaults, or no match and no default are errors.
- Package lists are plain lists, since a flavour fixes the distribution.
- `ask.toml` is no longer a layer. It sets only project-level options (`packages`,
  `bind_mounts`, `tool_managers`, `services`, `scripts` and `env`), and is applied after the
  flavour's layers. It is still trusted like a build script, because
  bind mounts can expose any host path.
- A missing global config defines no flavours, so no flavour applies.

## Consequences

- Projects describe what they need, not which environment they run in; the same `ask.toml`
  works across flavours.
- `ask.toml` can no longer add agents.
- Package names that differ between distributions must be listed in each flavour.
- Ask cannot be used without a global config defining at least one flavour.
