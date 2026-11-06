import cyclopts

from ask.cli import converge, create, exec

app = cyclopts.App()
app.command(create)
app.command(converge)
app.command(exec)


def main() -> None:
    app()
