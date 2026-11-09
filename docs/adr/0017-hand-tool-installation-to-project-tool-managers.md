# Hand tool installation to the project's tool managers

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-09 | accepted |

## Context

Many projects already declare their toolchain for a tool manager such as [mise](https://mise.jdx.dev),
e.g. pinned Erlang and Elixir versions in a `mise.toml`. Repeating those as distribution packages
in `ask.toml` duplicates the declaration, and distributions rarely ship the pinned versions.

A project's mise config can run arbitrary code (`[env]` sources, hooks, tasks), which is why mise
itself refuses to load it until it is trusted. Unlike `ask.toml`
(`docs/adr/0011-ask-toml-is-a-self-contained-trusted-layer.md`), it is not written for Ask.

## Decision

- Ask knows a fixed set of tool managers; mise is the first. A tool manager is used when it is
  enabled and its config files exist in the project directory. For mise those are the project-local
  TOML config locations mise documents; `.tool-versions` is not one of them.
- Every tool manager is enabled by default. A layer or `ask.toml` opts out with
  `tool_managers = ["-mise"]` and opts back in with `"mise"`, merged as in
  `docs/adr/0013-remove-packages-and-agents-from-lower-layers.md`.
- On converge, after the user, mounts and packages, Ask:
  - installs the tool manager as a distribution package,
  - shows its config files and asks before running `mise trust` on each, unless the SHA-256 of
    their paths and contents matches the one recorded in `user.ask.mise.trusted` on the container.
    Without a terminal, converge fails instead of asking,
  - runs `mise install` as the user in the project directory,
  - sets the container's `environment.PATH` to mise's shims directory followed by Incus' default
    PATH, or to Incus' default PATH alone when no tool manager is used.
- The contents of the used config files are part of the effective configuration from
  `docs/adr/0016-record-converged-state-on-the-container.md`, so changing them offers to converge.

## Consequences

- Tools declared for mise are on the PATH of `ask enter`, `ask exec` and `ask agent` in every
  shell, without changing the read-only mounted shell rc files.
- Shims only give mise's `[env]` to the tools they run; the shell itself only gets it if the
  user's rc runs `mise activate`.
- Each new container asks to trust the mise config again; trust is not shared between containers.
- A changed config is shown in full, not as a diff against what was trusted before.
- Ask owns `environment.PATH` on its containers; a value set by hand is overwritten on converge.
