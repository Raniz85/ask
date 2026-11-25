# Share the pacman package cache between containers with an Incus storage volume

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-25 | accepted |

## Context

Every Arch container downloads its own copies of the same package tarballs into
`/var/cache/pacman/pkg`; a fresh container re-downloads everything `ask.toml`
and the flavour declare, even though identical tarballs already sit on the host
in other containers' caches. ADR 0015 already shares paru's state this way.

Unlike paru, pacman's cache is safe to share: tarballs are addressed by
`name-version` so a hit from another container is the exact same file, pacman
downloads into a random-named `.part` file under `CacheDir` and renames it on
success (so concurrent converges cannot corrupt each other), and signatures
are verified at install time regardless of where the file came from.

The cache is written by pacman's unprivileged `alpm` download user (Arch's
stock `pacman.conf` sets `DownloadUser = alpm`), so the directory must stay
world-writable.

## Decision

- All Arch containers share one custom Incus storage volume, `ask-pacman` in
  the `default` pool, attached as device `pacman-cache` at the stock
  `/var/cache/pacman/pkg` (`CacheDir` stays untouched).
- The volume is attached when the container is created — not only on converge —
  so every pacman invocation in the container populates or reuses the shared
  cache, permanently.
- The mount point is set to mode 1777, what Arch ships, so the `alpm` download
  user can write to it; no ownership is forced.
- `pacman.conf` gets `CleanMethod = KeepCurrent`: the default `KeepInstalled`
  judges "still installed" per cleaning container, so one container's clean
  would delete entries only another container has installed. `KeepCurrent`
  keeps whatever the sync repos still list.
- After every converge, `pacman -Sc --noconfirm` runs to drop cache versions
  the sync repos no longer list. Its default answer is "yes", so
  `--noconfirm` really deletes.

## Consequences

- A fresh container installs declared packages from the shared cache instead
  of re-downloading them.
- A cache entry survives while the sync repos still list its version; the
  first converge after a repo drops a version frees it, no matter who has it
  installed.
- Concurrent pacman runs in two containers download distinct `.part` temp
  files and the loser's rename overwrites a complete, identical tarball; safe.
- The volume outlives containers and is never removed by Ask.
- Non-Arch distributions are unaffected.
