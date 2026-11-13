# Configure agents and environment variables as tables

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-13 | accepted |

## Context

Instances need environment variables at three scopes: the whole instance, every agent invocation
and a single agent. Agents were an array in each flavour layer, which leaves no place for
settings shared by all agents, such as their environment variables or which agent is the default.

## Decision

This supersedes the agent parts of `docs/adr/0012-merge-layers-in-declaration-order.md` and
`docs/adr/0013-remove-packages-and-agents-from-lower-layers.md`.

- `agents` in a flavour layer is a table keyed by agent name. The value is `true` to enable the
  agent, `false` to remove it from lower layers, or a table of its options and its `env`.
- `env` and `default` are reserved keys in the `agents` table. `env` applies to every agent
  invocation, `default` names the agent `ask agent` runs when none is given.
- Agents are merged by name and kept at their first position. A removal drops the agent's merged
  options and environment. Without a `default`, the first merged agent is the default.
- `env` on a flavour layer and in `ask.toml` applies to the whole instance. It is written to
  `/etc/profile.d/` and passed to every command Ask runs in the instance.
- Environment variables are merged per name, a later layer winning. Setting a variable to `false`
  removes it from lower layers.
- An agent invocation gets the instance environment, overridden by `agents.env`, overridden by
  the agent's own `env`. Variables Ask sets itself, such as `HOME`, take precedence over all.

## Consequences

- Agent names `env` and `default` are reserved.
- Agents are removed with `false`, while packages keep the `-` prefix.
- Agent environment and the default agent only affect invocations, so changing them does not
  require converging the instance.
- The instance environment reaches non-login shells and commands run through `incus exec`, not
  only login shells.
