import sys

import cyclopts

from ask.cli import agent, converge, create, enter, exec
from ask.config import ConfigError

app = cyclopts.App()
app.command(create)
app.command(converge)
app.command(enter)
app.command(exec)
app.command(agent)


def main() -> None:
    try:
        app()
    except ConfigError as error:
        print(f"ask: {error}", file=sys.stderr)
        sys.exit(1)
