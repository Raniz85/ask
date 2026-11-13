# Read the invocation timestamp via the guest config endpoint

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-11 | accepted |

## Context

ADR 0022 has the in-instance watchdog read `user.ask.invocation.at` from
`GET /1.0` on the in-instance Incus socket. That endpoint does not return the
instance config; it returns only API version, location, instance type, and
state. The query therefore always came back empty, the watchdog fell back to
counting idleness from instance start, and a fresh instance whose provisioning
runs longer than the idle threshold was powered off mid-convergence.

## Decision

The watchdog reads the timestamp from the guest socket's config endpoint,
`GET /1.0/config/user.ask.invocation.at`, which returns the raw `user.*` value
(200), or 404 when the key is unset. A 404 keeps the count-from-start fallback;
any other failure or an unreachable socket keeps the instance up. `jq` is no
longer needed, so only `curl` is provisioned.

## Consequences

- The watchdog now sees the same invocation timestamp the host records and
  refreshes, so a running `ask converge` keeps the instance up.
- The fallback semantics of ADR 0022 (count from instance start when no
  invocation is recorded, stay up when the metadata is unreadable) are unchanged.
