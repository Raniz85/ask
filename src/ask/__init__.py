import os
import sys
from collections.abc import Sequence
from typing import Annotated, NoReturn

import cyclopts
from cyclopts.panel import CycloptsPanel
from rich.console import Console

from ask.cli import agent, converge, create, enter, exec, restart
from ask.cli import run as run_script
from ask.errors import AskError

app = cyclopts.App()
app.command(create)
app.command(converge)
app.command(enter)
app.command(exec)
app.command(agent)
app.command(restart)
app.command(run_script, name="run")


def run(tokens: Sequence[str], debug: bool) -> None:
    try:
        app(tokens)
    except (Exception, KeyboardInterrupt) as error:
        if debug:
            raise
        _report(error)


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


def main(tokens: Sequence[str] | None = None) -> None:
    app.meta(tokens)
