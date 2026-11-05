import cyclopts

from ask.cli import converge, create

app = cyclopts.App()
app.command(create)
app.command(converge)


def main() -> None:
    app()
