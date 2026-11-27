import os
import sys
from collections.abc import Sequence
from typing import Annotated, NoReturn

import cyclopts
from cyclopts.panel import CycloptsPanel
from rich.console import Console

from ask import interactive
from ask.cli import (
    agent,
    converge,
    create,
    destroy,
    dump,
    enter,
    exec,
    ide,
    init,
    ls,
    rename,
    resolve_shortcut,
    restart,
    setup,
    stop,
)
from ask.cli import run as run_script
from ask.errors import AskError
from ask.log import configure_debug

app = cyclopts.App()
app.command(create)
app.command(dump, name="config")
app.command(converge)
app.command(destroy)
app.command(enter)
app.command(exec)
app.command(agent)
app.command(ide)
app.command(init)
app.command(ls)
app.command(rename)
app.command(restart)
app.command(setup)
app.command(stop)
app.command(run_script, name="run")


def run(tokens: Sequence[str], debug: bool) -> None:
    if debug:
        configure_debug()
    try:
        app(_expand_shortcut(tokens))
    except (Exception, KeyboardInterrupt) as error:
        if debug:
            raise
        _report(error)


def _expand_shortcut(tokens: Sequence[str]) -> list[str]:
    if not tokens or tokens[0].startswith("-") or tokens[0] in app.resolved_commands():
        return list(tokens)
    target = resolve_shortcut(tokens[0])
    if target is None:
        return list(tokens)
    return [target, "--", *tokens]


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
    path: Annotated[
        str | None,
        cyclopts.Parameter(
            name=("-p", "--path"),
            negative="",
            help="Run the command as if started from this directory instead "
            "of the current one.",
        ),
    ] = None,
    assume_yes: Annotated[
        bool,
        cyclopts.Parameter(
            help="Answer yes to every prompt, for running ask without a terminal."
        ),
    ] = False,
) -> None:
    interactive.assume_yes = assume_yes
    if path is not None:
        try:
            os.chdir(path)
        except OSError as error:
            raise AskError(f"Cannot run from {path!r}: {error.strerror}") from None
    run(tokens, debug=debug or bool(os.environ.get("ASK_DEBUG")))


_PASSTHROUGH_COMMANDS = ("exec", "run", "agent", "ide")


def main(tokens: Sequence[str] | None = None) -> None:
    try:
        app.meta(_separate_passthrough(sys.argv[1:] if tokens is None else tokens))
    except AskError as error:
        # errors raised by the launcher itself (e.g. an unusable --path),
        # outside of run()'s own reporting
        _report(error)


def _separate_passthrough(tokens: Sequence[str]) -> list[str]:
    command_index = _command_index(tokens)
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


# meta options whose value is a separate token, skipped when scanning for
# the command so the value is not mistaken for one
_META_VALUE_OPTIONS = ("-p", "--path")


def _command_index(tokens: Sequence[str]) -> int | None:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            index += 2 if token in _META_VALUE_OPTIONS else 1
            continue
        return index
    return None


def _option_names(command: str) -> set[str]:
    return {
        name
        for argument in app[command].assemble_argument_collection()
        if argument.field_info.kind is argument.field_info.KEYWORD_ONLY
        for name in argument.names
    } | set(app.help_flags)
