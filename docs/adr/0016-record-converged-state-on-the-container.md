# Record the converged state on the container

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-09 | accepted |

## Context

Commands other than `ask converge` run in a container that may have been converged with an older
configuration or an older version of Ask. Users should be offered to converge before the command
runs, but finding that out must be cheap enough to do on every `ask enter`, `ask exec` and
`ask agent`.

## Decision

- After a successful converge, Ask records on the container, as Incus config keys:
  - `user.ask.converged.version`: the installed version of Ask,
  - `user.ask.converged.hash`: the SHA-256 of the effective configuration,
  - `user.ask.converged.configuration`: the effective configuration itself, as canonical JSON,
  - `user.ask.converged.at`: when it was converged, in ISO 8601.
- The effective configuration is the manifest, the global layers it uses, and the global `user`
  and `shell` tables. Layers the manifest does not use are not part of it.
- Before running a command, Ask compares the recorded version and hash with the current ones. Any
  difference, or a missing record, counts as changed. Ask then asks whether to converge; without a
  terminal it warns and carries on. `--converge` and `--no-converge` decide without asking.
- Everything Ask reads about the instance on that path comes from a single
  `incus list <name> --format json` call. Unlike `incus query`, it honours the current Incus
  project. It ties Ask to the shape of the instance objects in that JSON output.

## Consequences

- An unchanged configuration costs one Incus call and one hash; no diff is computed.
- The record lives and dies with the container.
- Any change to Ask's version counts as changed, even when it does not affect convergence. During
  development the version is rarely bumped, so code changes alone do not prompt.
- The recorded configuration makes it possible to show what changed, but nothing does so yet.
