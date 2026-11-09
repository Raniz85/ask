import os
import sys
from collections.abc import Sequence
from typing import Annotated, NoReturn

import cyclopts

from ask.cli import agent, converge, create, enter, exec
from ask.errors import AskError

app = cyclopts.App()
app.command(create)
app.command(converge)
app.command(enter)
app.command(exec)
app.command(agent)


def run(tokens: Sequence[str], debug: bool) -> None:
    try:
        app(tokens)
    except (Exception, KeyboardInterrupt) as error:
        if debug:
            raise
        _report(error)


def _report(error: BaseException) -> NoReturn:
    match error:
        case KeyboardInterrupt():
            print("ask: interrupted", file=sys.stderr)
            sys.exit(130)
        case AskError():
            print(f"ask: {error}", file=sys.stderr)
        case _:
            print(
                f"ask: unexpected error: {type(error).__name__}: {error}\n"
                "ask: run with --debug or ASK_DEBUG=1 for the full traceback",
                file=sys.stderr,
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
