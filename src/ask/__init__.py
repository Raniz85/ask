import cyclopts

from ask.cli import converge, create, enter, exec

app = cyclopts.App()
app.command(create)
app.command(converge)
app.command(enter)
app.command(exec)


def main() -> None:
    app()
