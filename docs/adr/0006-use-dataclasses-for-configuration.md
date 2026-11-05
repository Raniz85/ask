# Represent configuration structures with dataclasses

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-05 | accepted |

## Context

`ask.toml` and `global.toml` (see `docs/adr/0003-use-toml-for-configuration.md`) describe nested
structures — distributions, layers, per-distro package lists, agent settings, bind mounts, and
so on. We need a way to turn parsed TOML dicts into something code can use safely, with clear
field names/types and without maintaining a separate schema document that can drift from the
code that consumes it.

## Decision

Each configuration structure is represented by exactly one `dataclass`. Parsed TOML is
deserialized into instances of these dataclasses, and the dataclass definitions _are_ the
validation layer (required fields, field types, nested structures) — there is no separate
schema (e.g. JSON Schema) kept in sync by hand.

## Consequences

- Single source of truth: the dataclass fields are simultaneously the schema, the
  documentation, and the object the rest of the code works with.
- Plays well with type checkers and IDEs, consistent with using type annotations throughout.
- Deserializing raw TOML dicts into (possibly nested) dataclass instances, with reasonable
  validation error messages, still needs a chosen approach (hand-written, or a library such as
  `dacite`/`cattrs`) — left open for a follow-up decision once requirements are clearer.
- Dataclasses validate field presence/type on construction, but not arbitrary value constraints
  (e.g. "this string must be a known distribution name") without extra code we write ourselves.
