# Ask to converge containers not converged in a week

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-26 | accepted |

## Context

Configuration changes are offered for convergence on every command, per
`docs/adr/0016-record-converged-state-on-the-container.md`. But an unchanged
configuration converges to the same state forever: packages pinned by the
flavour's image or installed once never update, and a container that has not
been converged for a long time drifts from what a fresh `ask create` would
produce, without any prompt.

## Decision

- Independently of the configuration fingerprint, Ask compares
  `user.ask.converged.at` with the current time before running a command. If
  the last convergence is more than one week old, Ask asks whether to converge
  again, exactly as it does for a changed configuration: a prompt on a
  terminal, a warning without one, and `--converge`/`--no-converge` decide
  without asking.
- The stale check only runs when the configuration is unchanged; a changed
  configuration already prompts, and the user is never asked twice.
- A missing or unreadable `user.ask.converged.at` counts as not stale; a
  missing record already counts as changed by the fingerprint comparison.

## Consequences

- Containers are re-converged at least weekly when used through Ask, keeping
  them close to a fresh create.
- The week is a fixed constant, not configurable; making it configurable
  would add it to the effective configuration and thus trigger prompts on
  change.
