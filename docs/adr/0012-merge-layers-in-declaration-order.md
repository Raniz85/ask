# Merge layers in declaration order, with ask.toml last

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-09 | accepted |

## Context

`docs/adr/0011-ask-toml-is-a-self-contained-trusted-layer.md` applied the manifest as the first
layer, and layers were combined by appending: duplicate packages, bind mounts and agents were
kept, and the same agent in several layers was resolved once per layer. The project's own
settings should take precedence over shared global layers, and combining layers needs a rule
for which value wins.

## Decision

This supersedes the layer order in ADR 0011. The named layers are applied in the order
`ask.toml` lists them, followed by `ask.toml` itself as the last layer. Later layers override
earlier ones, and duplicates are merged:

- Packages and bind mounts are combined, each kept once at its first position.
- Agents are combined by name, each kept once at its first position. Their options are merged,
  a later layer's value winning for the same option.
- `shared_state` is optional. For each agent, the last layer that lists the agent and sets
  `shared_state` decides whether its state is shared; if none sets it, it is not shared.

## Consequences

- A project can override any global layer's setting from `ask.toml`, including turning off
  shared agent state with `shared_state = false`.
- Each agent is installed and mounted once, however many layers enable it.
- Layers cannot remove packages or bind mounts added by earlier layers.
- Options added to layers later need their own merge rule when they are not lists or agents.
