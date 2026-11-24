"""Generate the configuration reference in docs/config.md.

docs/config.md carries hand-written prose around
`<!-- ask:gen:<name> -->` markers; the content inside each marker is
generated from the pydantic schemas of the configuration dataclasses.
Run `just docs` after changing a configuration struct.
"""

import importlib
import re
import sys

from pydantic import TypeAdapter

# ask.agent and ask.ide are shadowed by the CLI commands in ask/__init__.py
agent = importlib.import_module("ask.agent")
ide = importlib.import_module("ask.ide")
tool_manager = importlib.import_module("ask.tool_manager")
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


def _table(schema: dict, defs: dict) -> list[str]:
    """Render an object schema's properties as a Markdown table.

    Columns are padded to equal width so the output survives dprint fmt
    unchanged (dprint aligns markdown tables).
    """
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
    header = ("Key", "Type", "Required", "Description")
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


def _enum(kind: str, names: list[str]) -> str:
    return f"Known {kind}: {', '.join(f'`{name}`' for name in names)}."


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


def update(doc: str) -> str:
    """Replace the body inside each marker with generated content."""
    generated = sections()

    def replacement(match: re.Match) -> str:
        name = match.group("name")
        assert name in generated, f"docs/config.md has unknown marker ask:gen:{name}"
        return f"{_BEGIN.format(name=name)}\n\n{generated[name]}\n\n<!-- /ask:gen -->\n"

    updated, count = _MARK_RE.subn(replacement, doc)
    missing = generated.keys() - {
        match.group("name") for match in _MARK_RE.finditer(doc)
    }
    assert not missing, f"docs/config.md lacks markers: {', '.join(sorted(missing))}"
    assert count, "docs/config.md has no generation markers"
    return updated


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "docs/config.md"
    with open(path) as f:
        doc = f.read()
    updated = update(doc)
    with open(path, "w") as f:
        f.write(updated)
