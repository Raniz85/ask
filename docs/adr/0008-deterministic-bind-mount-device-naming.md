# Name managed bind-mount devices deterministically from their path, and fully reconcile them

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-05 | accepted |

## Context

`ask converge` needs to make an Incus instance's disk devices match the bind mounts currently
declared across the project directory, `ask.toml`, and the layers it opts into in the global
config. This means converge must be able to tell, on repeated runs, which existing devices on
the instance it manages and which path each corresponds to, so it can add newly-declared mounts
and remove ones that are no longer declared — without disturbing devices it doesn't own (e.g.
`root`, `eth0`) that come from the instance's profile.

## Decision

Every bind mount Ask manages (the automatic project directory mount included) is added as an
Incus disk device named deterministically from its path: characters other than alphanumerics,
`_` and `-` are replaced with `-` and the result is prefixed with `bind-` (e.g. `/home/raniz/.cache/uv` becomes
`bind--home-raniz--cache-uv`). `ask converge` lists the instance's devices, treats every name
starting with `bind-` as one it manages, and fully reconciles that subset: devices for mounts no
longer declared are removed, and devices for newly declared mounts are added. Devices without
that prefix are never touched.

## Consequences

- Converge is idempotent and order-independent: the same declared path always produces the same
  device name, so re-running converge after a config change produces a minimal diff instead of
  removing and re-adding everything.
- No separate state file is needed to track what Ask manages — the `bind-` prefix on the device
  name itself is the marker.
- The project directory's automatic mount is no longer special-cased as a fixed `project` device
  (as it was when `ask create` first introduced it) — it is just another entry in converge's
  desired set, keeping a single reconciliation path for all bind mounts.
- Very long or unusual paths produce correspondingly long, not particularly human-friendly
  device names; this hasn't been a problem in practice so far.
