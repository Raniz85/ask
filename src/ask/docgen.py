"""Generate the configuration reference in docs/config.md and docs/commands.md.

The docs carry hand-written prose around
`<!-- ask:gen:<name> -->` markers; the content inside each marker is
generated from the pydantic schemas of the configuration dataclasses
and the cyclopts app's registered commands.
Run `just docs` after changing a configuration struct or CLI signature.
"""

import importlib
import inspect
import re
import sys
from collections.abc import Sequence

from pydantic import TypeAdapter

# ask.agent and ask.ide are shadowed by the CLI commands in ask/__init__.py
agent = importlib.import_module("ask.agent")
ide = importlib.import_module("ask.ide")
tool_manager = importlib.import_module("ask.tool_manager")
from ask import app
from ask.config import Config
from ask.incus import known_distributions
from ask.manifest import Manifest

_BEGIN = "<!-- ask:gen:{name} -->"
_MARK_RE = re.compile(
    r"<!-- ask:gen:(?P<name>[\w-]+) -->\n(?P<body>.*?)<!-- /ask:gen -->\n",
    re.DOTALL,
)

_TYPE_HINTS = {
    "string": "string",
    "boolean": "boolean",
    "integer": "integer",
    "array": "list",
    "object": "table",
    "regex": "pattern",
}


def _type(node: dict, defs: dict) -> str:
    """A TOML-ish type name for a (possibly $ref/anyOf) schema node."""
    if "$ref" in node:
        return _type(defs[node["$ref"].split("/")[-1]], defs)
    if "anyOf" in node:
        parts = [
            part
            for part in node["anyOf"]
            if part.get("type") != "null" or "anyOf" not in node
        ]
        return " or ".join(_type(part, defs) for part in parts) or "none"
    extra = node.get("additionalProperties")
    if isinstance(extra, dict):
        return f"table of {_type(extra, defs)}"
    if node.get("format") == "regex":
        return "pattern"
    return _TYPE_HINTS.get(node.get("type", ""), node.get("type", "any"))


def _default(prop: dict) -> str:
    if "default" not in prop:
        return ""
    value = prop["default"]
    if isinstance(value, bool):
        return f" Defaults to `{str(value).lower()}`."
    if value is None:
        return " Defaults to `null`."
    return f" Defaults to `{value!r}`."


def _padded(header: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> list[str]:
    """Render rows as a width-aligned Markdown table.

    Columns are padded to equal width so the output survives dprint fmt
    unchanged (dprint aligns markdown tables).
    """
    widths = [
        max(len(row[column]) for row in (header, *rows))
        for column in range(len(header))
    ]
    padded = [
        "| "
        + " | ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        + " |"
        for row in (header, *rows)
    ]
    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return [padded[0], separator, *padded[1:]]


def _table(schema: dict, defs: dict) -> list[str]:
    """Render an object schema's properties as a Markdown table."""
    required = set(schema.get("required", []))
    rows = [
        (
            f"`{name}`",
            _type(prop, defs),
            "yes" if name in required else "no",
            f"{prop.get('description', '')}{_default(prop)}",
        )
        for name, prop in schema["properties"].items()
    ]
    return _padded(("Key", "Type", "Required", "Description"), rows)


def _enum(kind: str, names: list[str]) -> str:
    return f"Known {kind}: {', '.join(f'`{name}`' for name in names)}."


def _argument_default(argument) -> str:
    """A 'Defaults to' suffix for an argument, or an empty string."""
    info = argument.field_info
    if info.required or info.default is inspect.Parameter.empty:
        return ""
    value = (
        str(info.default).lower() if isinstance(info.default, bool) else info.default
    )
    return f" Defaults to `{value}`."


def _command(name: str, sub) -> list[str]:
    """Render one CLI command: heading, description, and an argument table."""
    lines = [f"### `ask {name}`", "", sub.help]
    rows = []
    for a in sub.assemble_argument_collection():
        kind = a.field_info.kind
        label = (
            f"{a.names[0].lstrip('-').upper()} {' '.join(a.names)}"
            if kind.name == "POSITIONAL_OR_KEYWORD"
            else f"{' '.join(a.names)}{'...' if kind.name == 'VAR_POSITIONAL' else ''}"
        )
        rows.append(
            (
                f"`{label}`",
                f"{(a.parameter.help or '')}{_argument_default(a)}",
            )
        )
    if rows:
        lines += ["", *_padded(("Argument", "Description"), rows)]
    return lines


def _cli_commands():
    """The app's commands as (name, sub-app) pairs, in registration order."""
    return [
        (name, sub)
        for name, sub in app._registered_commands.items()
        if not name.startswith("-")
    ]


def _agent_options() -> list[str]:
    return [
        f"- `{name}`: {', '.join(f'`{key}`' for key in sorted(resolved.option_keys()))}"
        for name in agent.known_names()
        if (resolved := agent.resolve(name))
    ]


def sections() -> dict[str, str]:
    """Render each generation marker's content, keyed by marker name."""
    flavor_schema = TypeAdapter(Config).json_schema()
    defs = flavor_schema["$defs"]

    def config_def(name: str) -> dict:
        return defs[name]

    # shortcut: blank lines mirror what dprint fmt emits, so generated
    # sections survive `just format` unchanged
    return {
        "manifest": "\n".join(
            [
                *_table(TypeAdapter(Manifest).json_schema(), {}),
                "",
                _enum("tool managers", tool_manager.known_names()),
            ]
        ),
        "flavor": "\n".join(
            [
                *_table(config_def("Flavor"), defs),
                "",
                _enum("distributions", known_distributions()),
            ]
        ),
        "user": "\n".join(_table(config_def("User"), defs)),
        "layer": "\n".join(
            [
                *_table(config_def("Layer"), defs),
                "",
                f"{_enum('IDEs', ide.known_names())} In a flavour, `ides` are configured per layer; the manifest has no `ides` key.",
            ]
        ),
        "agents": "\n".join(
            [
                "_Per-agent settings (`[layers.<layer>.agents.<name>]`, or `true`/`false` shorthand):_",
                "",
                *_table(config_def("AgentSettings"), defs),
                "",
                "_Layer-level agent table (`[layers.<layer>.agents]`):_",
                "",
                *_table(config_def("AgentTable"), defs),
                "",
                "_Agent options:_",
                "",
                *_agent_options(),
            ]
        ),
    }


def _cli_section() -> dict[str, str]:
    return {
        "commands": "\n\n".join(
            "\n".join(_command(name, sub)) for name, sub in _cli_commands()
        ),
    }


def update(doc: str, generated: dict[str, str]) -> str:
    """Replace the body inside each marker with generated content."""

    def replacement(match: re.Match) -> str:
        name = match.group("name")
        assert name in generated, f"doc has unknown marker ask:gen:{name}"
        return f"{_BEGIN.format(name=name)}\n\n{generated[name]}\n\n<!-- /ask:gen -->\n"

    updated, count = _MARK_RE.subn(replacement, doc)
    missing = generated.keys() - {
        match.group("name") for match in _MARK_RE.finditer(doc)
    }
    assert not missing, f"doc lacks markers: {', '.join(sorted(missing))}"
    assert count, "doc has no generation markers"
    return updated


if __name__ == "__main__":
    for path in sys.argv[1:] or ["docs/config.md", "docs/commands.md"]:
        generated = _cli_section() if path.endswith("commands.md") else sections()
        with open(path) as f:
            doc = f.read()
        with open(path, "w") as f:
            f.write(update(doc, generated))
