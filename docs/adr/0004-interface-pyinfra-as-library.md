# Interface with PyInfra as an in-process library, not via subprocess

## Status

| date       | state    |
| ---------- | -------- |
| 2026-11-05 | accepted |

## Context

Once an Incus container exists, Ask needs to declaratively provision it (packages, shell, IDE
helpers, bind mounts, agent tooling, ...) as described by the layers in `ask.toml` and the
global flavour files.
PyInfra is a Python automation tool that can be used either as a standalone CLI, driven by
deploy files on disk, or imported and driven programmatically from Python code via its own API.

## Decision

Ask depends on PyInfra as a regular Python library and drives it directly through its Python
API — building inventory and operations in-process from parsed TOML layers — rather than
shelling out to the `pyinfra` CLI via `subprocess`.

## Consequences

- Provisioning logic stays in one Python process: Ask can build inventory/operations dynamically
  from parsed config without serializing intermediate deploy files or CLI arguments.
- Errors from PyInfra surface as Python exceptions/return values instead of subprocess exit
  codes, which is simpler to handle and to unit test (no process spawning required).
- Ties Ask to PyInfra's Python API across versions, rather than only its documented CLI contract.
- This intentionally contrasts with the Incus integration (ADR-0002), which goes through
  `subprocess`: Incus has no good Python library, while PyInfra's Python API is its primary,
  officially supported interface.
