import cyclopts

from ask.cli import agent, converge, create, enter, exec

app = cyclopts.App()
app.command(create)
app.command(converge)
app.command(enter)
app.command(exec)
app.command(agent)


def main() -> None:
    app()
