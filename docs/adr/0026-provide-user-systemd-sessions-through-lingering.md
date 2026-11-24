# Provide user systemd sessions through lingering

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-24 | accepted |

## Context

Tools such as rootless Podman and `systemctl --user` need a user systemd session: a running
`systemd --user` manager, `/run/user/<uid>` and a session bus. Ask runs every command through
`incus exec` (ADR-0002), which bypasses PAM, so logind never starts a session for the user.

Wrapping commands in a session-creating tool (`machinectl shell`, `su -l`,
`systemd-run --user --pty`) would create a real logind session, but each loses or mangles the
working directory, environment or exit code that `incus exec` passes through cleanly.

## Decision

- Convergence enables lingering for the user (`loginctl enable-linger`), so
  `user@<uid>.service` starts at boot. This is always on, with no configuration.
- Before `ask enter`, `ask exec`, `ask agent` and `ask run` start a command as the user, Ask
  starts `user@<uid>.service` as root and waits for it, which covers a freshly booted instance.
- Those commands run with `XDG_RUNTIME_DIR=/run/user/<uid>` and
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus`. `ask enter --root` gets neither.
- This amends ADR-0022: the idle watchdog ignores the user's processes that live in the
  `user@<uid>.service` cgroup, since the lingering manager and its helpers are always running.

## Consequences

- `systemctl --user`, the session bus and anything needing `XDG_RUNTIME_DIR` work in every
  Ask command without changing how commands are executed.
- Every instance runs a user manager, costing a few megabytes.
- Work running under the user manager (user services, detached Podman containers) does not
  keep the instance up; only processes started through `incus exec` do.
- Rootless Podman still needs subordinate ID ranges and a large enough Incus idmap, which this
  decision does not provide.
