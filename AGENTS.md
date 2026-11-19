# AGENTS.md

Guidance for any agent (human or AI) working on Ask.

## What Ask is

Ask creates persistent, isolated, declarative development environments on top of
[Incus](https://linuxcontainers.org/incus) containers, provisioned with [PyInfra](https://pyinfra.com).
See `README.md` for the pitch and a quickstart sketch.

## Tech stack and integration constraints

- **Language**: Python, `>=3.13`. Dependency management via `uv`.
- **Incus**: managed by invoking the `incus` CLI through `subprocess`. There is no official
  stable Incus client library, so we shell out rather than talk to its REST API directly.
  See `docs/adr/0002-invoke-incus-via-subprocess.md`.
- **PyInfra**: used as an in-process Python library (imported and driven through its Python
  API), never invoked via `subprocess`. See `docs/adr/0004-interface-pyinfra-as-library.md`.
- **Configuration**: TOML. Per-project config lives in `ask.toml`; user-wide/shared config
  lives in the flavour files under `$XDG_CONFIG_HOME/ask/`. See
  `docs/adr/0003-use-toml-for-configuration.md` and
  `docs/adr/0021-one-file-per-flavour.md`. Each configuration structure is represented by
  exactly one `dataclass`, with Pydantic validators applied on top for validation. See
  `docs/adr/0006-use-dataclasses-for-configuration.md` and
  `docs/adr/0010-validate-configuration-with-pydantic.md`.
- **CLI**: built with [cyclopts](https://cyclopts.readthedocs.io), deriving commands/arguments
  from type-annotated function signatures. See `docs/adr/0005-use-cyclopts-for-cli.md`.

These two integrations are intentionally asymmetric (subprocess for Incus, in-process library
for PyInfra) — don't "fix" that inconsistency without reading the relevant ADRs first.

## Recording decisions (ADRs)

Major decisions — architecture, external interfaces, data formats, anything hard to reverse —
are recorded as lightweight Architecture Decision Records under `docs/adr/`.

- Use `docs/adr/0000-template.md` as the template.
- Number sequentially (`0001-...`, `0002-...`), filename is `NNNN-kebab-case-title.md`.
- Keep them short: Context, Decision, Consequences. No extended prose.
- Superseding a past decision means adding a new ADR that references the old one by number,
  not editing or deleting the old one.
- Small/local implementation choices do not need an ADR — use judgement, or ask if unsure.

See `docs/adr/0001-record-architecture-decisions.md` for the rationale.

## Working conventions

- Use type annotations wherever possible — function signatures, dataclass fields, module-level
  values. This is also what lets cyclopts and the config dataclasses do their job.
- Follow TDD: a failing test before implementation code; stubs return real values, never
  raise/panic.
- Prefer simple, readable solutions over clever/concise ones.
- Keep changes scoped to the task at hand; file unrelated issues/ideas separately instead of
  fixing them inline.
- Match existing style/formatting in the file you're editing.
- Preferred package installation sources:
  1. Official package manager repositories, search for the correct package, don't rely on training data or memory
  2. Official package manager 3rd party repositories - i.e. Anthropics APT repository for claude, Mise's APT repository for mise
  3. Relaiable package manager community-operated repositories - i.e. the AUR, listed PPAs
  4. Official installation method that does not go through a package manager. This is a last resort

### Task Automation

Common development tasks are automated using a [`Justfile`](https://just.systems).
Run these commands via `just <command>` to ensure consistency:

- `check`: Run all formatting, linting, typechecking, and tests.
- `sync`: Update and sync dependencies using `uv`.
- `format`: Format code using `dprint`.
- `lint`: Lint code using `ruff`.
- `typecheck`: Run type checking using `mypy`.
- `test`: Run tests with coverage.

No task is complete until `just check` passes
