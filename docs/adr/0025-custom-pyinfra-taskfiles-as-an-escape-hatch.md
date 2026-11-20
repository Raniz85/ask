# Run custom PyInfra taskfiles as the last converge step

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-20 | accepted |

## Context

Ask's own provisioning steps (user, mounts, packages, services, environment, idle
shutdown, tool managers) cover the common cases, but some projects need custom
provisioning that Ask does not model. PyInfra deploy files ("taskfiles") are the
natural escape hatch: they are plain Python driving the same operations Ask uses
internally (ADR-0004).

Both layers in flavour files and `ask.toml` (which is itself a layer, ADR-0011)
should be able to name taskfiles. A relative path must mean the same thing no
matter which file declares it, so it is resolved against the directory of the
file that declared it; absolute paths are used as given.

## Decision

`Layer` and `Manifest` accept a `taskfiles` list of paths, resolved against the
declaring file's directory at load time. During `ask converge`, after all of
Ask's own provisioning, the resolved taskfiles (layers in order, then the
manifest, deduplicated) are executed against the container in one PyInfra
session, in order. Missing taskfiles are reported as configuration problems,
like missing bind mounts. Taskfile contents are hashed into the converged
configuration, so editing a taskfile triggers a re-converge.

## Consequences

- Taskfiles run as root inside the container via the Incus connector, exactly
  like Ask's own operations; a taskfile in `ask.toml` is trusted code, like the
  rest of the manifest (ADR-0011).
- Taskfiles run last, so they can rely on everything Ask provisioned (packages,
  services, environment) already being in place.
- Because the file contents are part of the config hash, converge re-runs them
  when they change; PyInfra operations remain idempotent, so re-running is safe.
- Execution uses PyInfra's in-process API with per-host context, not the
  `pyinfra` CLI (ADR-0004).
