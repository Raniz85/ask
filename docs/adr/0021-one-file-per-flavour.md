# Define each flavour in its own file

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-10 | accepted |

## Context

With `docs/adr/0018-select-the-environment-through-flavours.md`, the global `config.toml` held
nothing but flavours, either in place or as references to flavour files. Many users only need a
single flavour, and for them the `flavors` table and the `default = true` marker are pure
ceremony.

## Decision

This supersedes the location in `docs/adr/0007-xdg-global-config-discovery.md`, and the parts of
`docs/adr/0018-select-the-environment-through-flavours.md` on where flavours are written and on a
missing global config.

- There is no `config.toml`. Each `*.toml` file in `$XDG_CONFIG_HOME/ask/flavors/` (falling back
  to `~/.config/ask/flavors/`) defines one flavour, named after the file without its extension.
  Other files in the directory are ignored.
- A flavour file has the flavour's keys at its root. Problems in it are reported against that
  file, by their path in it.
- When there is only one flavour file, that flavour is the default unless it sets
  `default = false`. With several, at most one may set `default = true`.
- A missing or empty flavours directory defines no flavours, so no flavour applies.

## Consequences

- A single-flavour setup is one file with no `flavors` table and no `default` marker.
- Flavours can be added, removed or shared by copying files, without editing a common file.
- Adding a second flavour file takes the implicit default away from the first, so it must then
  be marked with `default = true` if it should still apply everywhere else.
- `ask/flavors/` leaves `ask/` free for other kinds of configuration later.
