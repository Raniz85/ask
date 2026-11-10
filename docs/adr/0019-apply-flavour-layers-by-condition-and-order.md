# Apply flavour layers by condition and order

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-10 | accepted |

## Context

With `docs/adr/0018-select-the-environment-through-flavours.md`, `ask.toml` no longer lists the
layers to use. Ask has to decide which of a flavour's layers apply to a project, and in which
order, from the project itself. Telling whether a layer applies must be cheap, since it happens
on every command.

## Decision

This supersedes the layer order in `docs/adr/0012-merge-layers-in-declaration-order.md`; its
merge rules, and the removal rules from `docs/adr/0013-remove-packages-and-agents-from-lower-layers.md`,
still apply. It also changes what the effective configuration in
`docs/adr/0016-record-converged-state-on-the-container.md` consists of.

- A flavour's `base` layer is always applied, and cannot have `when` conditions.
- Any other layer applies when one of the file names in its `when.files` exists directly in the
  project directory. File names are exact; there are no patterns and no recursion. A layer
  without `when` always applies.
- Layers are applied in this order: `base`, then the other applying layers sorted by `order`
  (default 0, ties kept in declaration order), then `ask.toml`.
- The effective configuration is the selected flavour's distribution, shell and user, the layers
  that apply in the order they are applied, `ask.toml`, and the contents of the tool managers'
  config files. The flavour's name is not part of it, since renaming a flavour changes nothing in
  the container.

## Consequences

- A project picks up the right layers without naming them, e.g. a Python layer through
  `pyproject.toml`.
- Adding or removing a file a layer depends on changes the effective configuration, so Ask
  offers to converge.
- Checking conditions costs one file lookup per listed name.
- Layers cannot depend on files in subdirectories or on file contents.
