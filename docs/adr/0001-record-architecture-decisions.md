# Record architecturally significant decisions as ADRs

## Status
| date       | state    |
|------------|----------|
| 2026-11-05 | accepted |

## Context

As Ask grows, decisions about core architecture, external tool integration, and data formats
need to be discoverable without digging through chat history or commit messages. We want a
lightweight, append-only record that future contributors — human or agent — can read to
understand *why* something is built the way it is, not just *what* it does.

## Decision

Every architecturally significant decision is recorded as a short ADR in `docs/adr/`, following
the template in `docs/adr/0000-template.md`.

- Files are numbered sequentially starting at `0001`, named `NNNN-kebab-case-title.md`.
- ADRs are kept short: Context, Decision, Consequences — no extended prose.
- Superseding a decision means adding a new ADR that references the old one by number; existing
  ADRs are not rewritten or deleted.
- Minor or local decisions (e.g. the choice of a helper function) do not need an ADR.

## Consequences

- Decisions are easy to find and reference by number (e.g. "see ADR-0002").
- Adds a small amount of process overhead when making significant design choices.
- The ADR log only tells the truth about *decisions made*; it can drift from the code if an
  implementation changes without a corresponding new/superseding ADR, so it's not a substitute
  for reading the code.
