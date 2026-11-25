# Share the apt archive cache between containers with an Incus storage volume

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-25 | accepted |

## Context

ADR 0028 shares pacman's package cache between Arch containers. Debian
containers have the same waste: every one re-downloads the same `.deb` files
into `/var/cache/apt/archives`, and Debian is Ask's other distribution, where
most official packages (pi, oh-my-pi, mise, the JetBrains IDEs) come from
vendor apt repositories whose packages are large and rarely change.

apt stores downloaded archives under `/var/cache/apt/archives`, addressed by
exact filename, so a cache hit from another container is the same file. Like
pacman, apt verifies checksums on install regardless of where the file came
from.

## Decision

- All Debian containers share one custom Incus storage volume, `ask-apt` in
  the `default` pool, attached as device `apt-cache` at the stock
  `/var/cache/apt/archives`. `Dir::Cache` stays untouched, so no apt
  configuration is edited.
- The volume is attached when the container is created — not only on converge —
  mirroring ADR 0028.
- After every converge, `apt-get autoclean` prunes the shared archives: it
  keeps files still listed in the configured repositories' indexes and removes
  old versions. This mirrors pacman's `CleanMethod = KeepCurrent` (ADR 0028):
  apt has no per-container view of what other containers still have installed,
  so "still downloadable from a configured repo" is the only safe keeper rule.

## Consequences

- A fresh container installs packages from the shared archives instead of
  re-downloading them.
- An archive survives until it disappears from every configured repository's
  index (e.g. a vendor repo ships a new version); the first converge after
  that frees it.
- A container whose configured repos no longer list a file cannot have it
  pruned by another container's converge, but its own next converge prunes
  it.
- The volume outlives containers and is never removed by Ask.
- Non-Debian distributions are unaffected; see ADR 0028 for Arch.
