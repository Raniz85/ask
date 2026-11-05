# Invoke Incus through subprocess calls to the incus CLI

## Status
| date       | state    |
|------------|----------|
| 2026-11-05 | accepted |

## Context

Ask needs to create, start, stop, and otherwise manage Incus containers to host the declarative
dev environments it builds. Incus does not ship an official, stable Python client library; its
primary supported interface is the `incus` command-line tool. The underlying REST API (exposed
over a unix socket) is available, but talking to it directly means owning API-version coupling,
authentication/socket handling, and request/response (de)serialization that the CLI already
handles for us.

## Decision

Ask manages containers by invoking the `incus` CLI through Python's `subprocess` module, rather
than talking to the Incus REST API directly or depending on an unofficial client library. Where
available, CLI calls use `--format json` so output can be parsed structurally instead of
screen-scraped.

## Consequences

- Matches how administrators already interact with Incus, so behavior stays predictable and any
  failing call can be reproduced by hand on the command line.
- Avoids coupling to the undocumented/unstable REST API shape, auth, and socket handling.
- Subprocess calls need explicit handling of exit codes and stderr, and are slower than a direct
  library/API call would be.
- Correctness depends on the CLI's (JSON) output format staying stable across Incus versions we
  support.
