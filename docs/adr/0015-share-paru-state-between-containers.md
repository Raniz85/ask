# Share paru state between containers with an Incus storage volume

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-09 | accepted |

## Context

AUR packages are built in each container by a dedicated `aur` user running paru. paru records
which PKGBUILD revisions have been reviewed as an `AUR_SEEN` git ref in each clone under
`~/.cache/paru/clone`. A fresh container starts with an empty cache, so every PKGBUILD — including
`paru-bin`, which Ask bootstraps itself — has to be reviewed again in every new container.

The host does not need this state, and bind-mounting a host directory would leave it owned by the
host user, which the `aur` system user cannot write to.

## Decision

- All containers share one custom Incus storage volume, `ask-paru` in the `default` pool, attached
  as device `paru-cache` at `/home/aur/.cache/paru`.
- The `aur` user and group get a fixed id (900) so the volume's ownership means the same thing in
  every container.
- The `paru-bin` bootstrap clones into paru's own clone directory on that volume and follows
  paru's `AUR_SEEN` convention: no prompt if the current commit was already reviewed, a diff if an
  older one was, the full PKGBUILD otherwise.

## Consequences

- A PKGBUILD reviewed in one container is not asked about again in others; changes since the last
  review are shown as a diff.
- The volume outlives containers and is never removed by Ask.
- Running paru in two containers at the same time touches the same clones; this is not guarded.
- Relies on containers sharing one idmap (Ask does not set `security.idmap.isolated`), and on
  uid/gid 900 being free in the container image.
