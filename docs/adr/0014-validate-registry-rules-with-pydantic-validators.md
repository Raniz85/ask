# Validate registry rules with Pydantic validators

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-09 | accepted |

## Context

`docs/adr/0010-validate-configuration-with-pydantic.md` checks rules that depend on Ask's own
registries (known shells, agents, distributions) separately, after structural validation.
Those checks ended up in a `validation` module, away from the registries they check: adding a
shell or agent means touching one module, while the rules for its name and options live in
another. Knowledge about a distribution is likewise spread over the Incus image aliases, the
package operations and a hard-coded check for the AUR, so a distribution can pass validation
yet have no package operation.

## Decision

This supersedes the part of ADR 0010 that checks registry rules after structural validation.

- Each registry module owns its configuration option type (e.g. `ShellOption` in `shell`,
  `AgentSettings` in `agent`) and validates it with Pydantic validators during loading, so
  registry problems are reported together with structural ones, through the same error path.
- Everything Ask knows about a distribution lives in the modules that use it: the Incus image
  (`known_distributions` and `image_for` in `incus`) and the package operations including extra
  package sources keyed by package prefix (e.g. `aur:` in `provision`). The generic distribution
  type holds no distribution-specific knowledge.
- Rules that span files, such as a manifest referring to layers in the global configuration,
  are checked by the loader of the file that makes the reference.

## Consequences

- Data and the rules that validate it live in the same module.
- Unknown options are reported once per shell or agent, listing every unknown option, rather
  than once per option.
- Adding a distribution, or a package source to one, touches only the `distribution` module and
  the provisioning it refers to.
