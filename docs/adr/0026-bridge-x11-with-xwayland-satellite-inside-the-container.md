# Bridge X11 with xwayland-satellite inside the container

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-23 | accepted |

## Context

GUI sessions share the host's Wayland socket with the container. Some applications, such as
PyCharm, only speak X11. Forwarding the host's X11 socket would let the container observe and
inject input into every X11 client on the host, and requires the host to run an X server.

## Decision

- xwayland-satellite runs inside the container, as the user, on the mounted Wayland socket,
  serving display `:0` inside the container.
- It is started, detached, by the first GUI session and stopped by the last one, under the same
  lock and session count that attach and detach the Wayland socket.
- It is used only when the `xwayland-satellite` package is installed; IDEs that need X11 list it
  among their packages. `DISPLAY` is set only once its socket exists.
- Debian ships no package for it, so X11 is not supported on Debian for now.

## Consequences

- The container sees no more of the host than the Wayland socket it already had.
- X11 support costs nothing for containers that do not install the package.
- A bridge left behind by a crashed session counts as user activity and keeps the instance from
  shutting down when idle (see ADR 0022) until the next GUI session closes.
