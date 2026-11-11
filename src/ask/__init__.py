import os
import sys
from collections.abc import Sequence
from typing import Annotated, NoReturn

import cyclopts
from cyclopts.panel import CycloptsPanel
from rich.console import Console

from ask.cli import (
    agent,
    converge,
    create,
    enter,
    exec,
    init,
    resolve_shortcut,
    restart,
)
from ask.cli import run as run_script
from ask.errors import AskError

app = cyclopts.App()
app.command(create)
app.command(converge)
app.command(enter)
app.command(exec)
app.command(agent)
app.command(init)
app.command(restart)
app.command(run_script, name="run")


def run(tokens: Sequence[str], debug: bool) -> None:
    try:
        app(_expand_shortcut(tokens))
    except (Exception, KeyboardInterrupt) as error:
        if debug:
            raise
        _report(error)


def _expand_shortcut(tokens: Sequence[str]) -> list[str]:
    if not tokens or tokens[0].startswith("-") or tokens[0] in app.resolved_commands():
        return list(tokens)
    return [resolve_shortcut(tokens[0]), "--", *tokens]


def _report(error: BaseException) -> NoReturn:
    console = Console(stderr=True)
    match error:
        case KeyboardInterrupt():
            console.print(CycloptsPanel("Interrupted."))
            sys.exit(130)
        case AskError():
            console.print(CycloptsPanel(str(error)))
        case _:
            console.print(
                CycloptsPanel(
                    f"Unexpected error: {type(error).__name__}: {error}\n"
                    "Run with --debug or ASK_DEBUG=1 for the full traceback."
                )
            )
    sys.exit(1)


@app.meta.default
def _launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
    debug: Annotated[
        bool,
        cyclopts.Parameter(
            negative="", help="Show the full traceback when a command fails."
        ),
    ] = False,
) -> None:
    run(tokens, debug=debug or bool(os.environ.get("ASK_DEBUG")))


_PASSTHROUGH_COMMANDS = ("exec", "run", "agent")


def main(tokens: Sequence[str] | None = None) -> None:
    app.meta(_separate_passthrough(sys.argv[1:] if tokens is None else tokens))


def _separate_passthrough(tokens: Sequence[str]) -> list[str]:
    command_index = next(
        (i for i, token in enumerate(tokens) if not token.startswith("-")), None
    )
    if command_index is None or tokens[command_index] not in _PASSTHROUGH_COMMANDS:
        return list(tokens)
    own_options = _option_names(tokens[command_index])
    for index in range(command_index + 1, len(tokens)):
        token = tokens[index]
        if token == "--":
            break
        if token.split("=", 1)[0] not in own_options:
            return [*tokens[:index], "--", *tokens[index:]]
    return list(tokens)


def _option_names(command: str) -> set[str]:
    return {
        name
        for argument in app[command].assemble_argument_collection()
        if argument.field_info.kind is argument.field_info.KEYWORD_ONLY
        for name in argument.names
    } | set(app.help_flags)
