# Use pyinfrincus as the PyInfra connector for Incus containers

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-05 | accepted |

## Context

`docs/adr/0004-interface-pyinfra-as-library.md` decided Ask drives PyInfra through its Python
API rather than the `pyinfra` CLI, but left open how PyInfra actually talks to an Incus
container to run commands there. PyInfra needs a connector for this — the same role its built-in
`@local`/`@ssh`/`@docker` connectors play for other targets — and has no built-in one for Incus.

## Decision

Ask depends on the third-party `pyinfrincus` package, which registers an `incus` PyInfra
connector (executing commands via `incus exec`, transferring files via `incus file push`/`pull`).
Provisioning code builds a PyInfra `Inventory` targeting `@incus/<container name>`, so the
connector resolves the inventory host directly to the bare container name.

## Consequences

- No need to write and maintain an Incus connector ourselves; `pyinfrincus` already implements
  the `BaseConnector` interface PyInfra expects (`run_shell_command`, `put_file`, `get_file`,
  `connect`/`disconnect`, `make_names_data`).
- Ties Ask to `pyinfrincus`'s connector contract and its own dependency on PyInfra's connector
  API, both of which are far less widely used/stable than PyInfra itself.
- Commands run inside the container via `incus exec`, so they're subject to the same constraints
  as running `incus exec` by hand (e.g. the container must be running).
