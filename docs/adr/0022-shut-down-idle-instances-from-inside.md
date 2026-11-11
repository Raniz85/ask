# Shut down idle instances from inside the instance

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-11 | accepted |

## Context

Ask instances are persistent containers that stay running once started, even when nobody is
using them. Shutting them down when idle frees the resources, but the host cannot tell when an
instance is idle: `ask enter` and `ask exec` run through `incus exec`, which leaves no login
session record, and the host has no view of the processes running as the user inside.

## Decision

- Every command or session Ask runs in an instance (`ask enter`, `ask exec`, `ask agent`, and
  `ask converge`) records the time as `user.ask.invocation.at` on the instance, an ISO 8601 UTC
  timestamp, via `incus config set` — the same mechanism as the other Ask metadata on `user.*`
  keys. It is recorded when the instance is ensured running, both before the command starts and
  after it ends, so the idle window starts when the last command or session ends.
- While an Ask command is still running, the host keeps refreshing that timestamp once a minute
  from a background thread. This matters for `ask converge`, whose provisioning runs as root
  through the Incus connector and is therefore invisible to the watchdog's user-process check:
  without the refresh, a convergence longer than the idle threshold would be shut down
  mid-flight. The same refresh covers waiting at the "converge now?" prompt.
- Convergence provisions a systemd timer, `ask-idle-shutdown.timer`, running every minute, which
  triggers the oneshot service `ask-idle-shutdown.service` running
  `/usr/local/bin/ask-idle-shutdown` as root. The script:
  - reads `user.ask.invocation.at` from the instance's own config through the in-instance Incus
    socket (`curl --unix-socket /dev/incus/sock http://localhost/1.0`), with `curl` and `jq`
    installed for this purpose;
  - stays up while the user has a login session (`who`) or any program running (`ps -u`), which
    is what covers `ask enter`/`ask exec` sessions, since `incus exec` creates no utmp entry;
  - otherwise powers the instance off (`systemctl poweroff`) once five minutes have passed since
    the last recorded activity. With no recorded invocation it counts from instance start, and
    if the metadata cannot be read it stays up rather than risk shutting down a busy instance.

## Consequences

- The instance decides its own idleness from state it can observe about itself; the host only
  records when Ask last used it.
- A command or session running as the user always keeps the instance up, regardless of the
  recorded timestamp.
- The watchdog runs as root, so its own processes never count as user activity; querying the
  socket as root avoids permission issues with `/dev/incus/sock`.
- The record lives and dies with the instance, like the other `user.ask.*` keys.
- The five-minute threshold and one-minute check interval are constants in `ask.idle`, not
  user configuration.
