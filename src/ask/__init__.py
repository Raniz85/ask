import cyclopts

from ask.cli import create

app = cyclopts.App()
app.command(create)


def main() -> None:
    app()
