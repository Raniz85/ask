# Run xwayland-satellite inside the user session environment

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-24 | accepted |

Supersedes 0026 (bridge X11 with xwayland-satellite inside the container).

## Context

xwayland-satellite binds its own `xwls` Wayland listening socket through
wayland-server's `ListeningSocket::bind_auto`, which requires `XDG_RUNTIME_DIR`
and binds inside it. The start command in 0026 passed only `WAYLAND_DISPLAY`
and `HOME`, so the satellite exited immediately on every launch and X11
applications never worked.

Debian ships no xwayland-satellite package, and the project's releases carry no
binaries; 0026 left X11 unsupported on Debian.

## Decision

- The satellite is started with the container user's session environment
  (`XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` from the systemd user
  session, started before every GUI session), so its `xwls` socket binds in
  `/run/user/<uid>`.
- On Debian, converge builds the latest xwayland-satellite release from source
  when a JetBrains IDE is configured, installing `Xwayland` and purging the
  build dependencies afterwards. On Arch it stays a distribution package.

## Consequences

- X11 bridging works on both distributions wherever the binary is present.
- The Debian build adds compile time to the first converge of an X11 project
  and downloads crates from crates.io inside the container.
