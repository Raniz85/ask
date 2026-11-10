import subprocess
import sys
from pathlib import Path

ASK = Path(sys.executable).parent / "ask"
TERMINAL_WIDTH = 200


def _config_home_with_a_default_flavor(tmp_path: Path) -> Path:
    config_home = tmp_path / "config"
    (config_home / "ask" / "flavors").mkdir(parents=True)
    (config_home / "ask" / "flavors" / "arch.toml").write_text(
        'distribution = "arch"\n'
    )
    return config_home


def _error_panel(*lines: str) -> str:
    top = "╭─ Error " + "─" * (TERMINAL_WIDTH - 10) + "╮\n"
    rows = "".join(f"│ {line.ljust(TERMINAL_WIDTH - 4)} │\n" for line in lines)
    bottom = "╰" + "─" * (TERMINAL_WIDTH - 2) + "╯\n"
    return top + rows + bottom


def test_ask_reports_a_missing_manifest_without_a_traceback(tmp_path: Path) -> None:
    # given a project directory without an ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    # and an empty global configuration directory
    config_home = tmp_path / "config"
    config_home.mkdir()

    # when running ask converge from within the project directory
    result = subprocess.run(
        [str(ASK), "converge"],
        cwd=project_dir,
        env={
            "PATH": "/usr/bin:/bin",
            "XDG_CONFIG_HOME": str(config_home),
            "COLUMNS": str(TERMINAL_WIDTH),
        },
        capture_output=True,
        text=True,
    )

    # then a one-line error is printed and ask exits with status 1
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        _error_panel(
            f"No ask.toml found in {project_dir}. "
            "Run ask from a project directory containing ask.toml."
        ),
    )


def test_ask_reports_a_missing_incus_binary_without_a_traceback(
    tmp_path: Path,
) -> None:
    # given a project directory with a valid ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")

    # and a global configuration with a default flavour
    config_home = _config_home_with_a_default_flavor(tmp_path)

    # and a PATH on which there is no incus command
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()

    # when running ask enter from within the project directory
    result = subprocess.run(
        [str(ASK), "enter"],
        cwd=project_dir,
        env={
            "PATH": str(empty_bin),
            "XDG_CONFIG_HOME": str(config_home),
            "COLUMNS": str(TERMINAL_WIDTH),
        },
        capture_output=True,
        text=True,
    )

    # then a one-line error is printed and ask exits with status 1
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        _error_panel(
            "The incus command was not found. Is Incus installed and on PATH?"
        ),
    )


def test_ask_does_not_offer_to_create_a_missing_container_without_a_terminal(
    tmp_path: Path,
) -> None:
    # given a project directory with a valid ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")

    # and a global configuration with a default flavour
    config_home = _config_home_with_a_default_flavor(tmp_path)

    # and an incus command that knows of no containers
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_incus = fake_bin / "incus"
    fake_incus.write_text('#!/bin/sh\nif [ "$1" = list ]; then echo "[]"; fi\n')
    fake_incus.chmod(0o755)

    # when running ask enter from within the project directory, with "yes"
    # piped to stdin rather than a terminal
    result = subprocess.run(
        [str(ASK), "enter"],
        cwd=project_dir,
        env={
            "PATH": str(fake_bin),
            "XDG_CONFIG_HOME": str(config_home),
            "COLUMNS": str(TERMINAL_WIDTH),
        },
        input="y\n",
        capture_output=True,
        text=True,
    )

    # then the user is not asked anything, a one-line error is printed and ask
    # exits with status 1
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        _error_panel("No container named 'my-project'. Run `ask create` first."),
    )


def test_ask_creates_a_missing_container_without_asking_when_requested(
    tmp_path: Path,
) -> None:
    # given a project directory with a valid ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")

    # and a global configuration with a default flavour
    config_home = _config_home_with_a_default_flavor(tmp_path)

    # and an incus command that knows of no containers and refuses to launch one
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_incus = fake_bin / "incus"
    fake_incus.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = list ]; then echo "[]"; fi\n'
        'if [ "$1" = launch ]; then echo refused >&2; exit 1; fi\n'
    )
    fake_incus.chmod(0o755)

    # when running ask exec --create from within the project directory
    result = subprocess.run(
        [str(ASK), "exec", "--create", "true"],
        cwd=project_dir,
        env={
            "PATH": str(fake_bin),
            "XDG_CONFIG_HOME": str(config_home),
            "COLUMNS": str(TERMINAL_WIDTH),
        },
        capture_output=True,
        text=True,
    )

    # then the user is not asked anything, and the container is launched
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        "refused\n"
        + _error_panel(
            "`incus launch images:archlinux/current my-project "
            "--config security.nesting=true --config security.privileged=false` "
            "failed with exit status 1."
        ),
    )


def _project_with_an_unconverged_container(tmp_path: Path) -> tuple[Path, dict]:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_home = _config_home_with_a_default_flavor(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_incus = fake_bin / "incus"
    fake_incus.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = list ]; then\n'
        '  echo \'[{"name": "my-project", "status": "Running", "config": {}}]\'\n'
        "fi\n"
    )
    fake_incus.chmod(0o755)
    env = {"PATH": str(fake_bin), "XDG_CONFIG_HOME": str(config_home)}
    return project_dir, env


def test_ask_warns_about_a_changed_configuration_without_a_terminal(
    tmp_path: Path,
) -> None:
    # given a project directory whose running container was never converged
    project_dir, env = _project_with_an_unconverged_container(tmp_path)

    # when running ask exec without a terminal
    result = subprocess.run(
        [str(ASK), "exec", "true"],
        cwd=project_dir,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )

    # then a warning is printed, and the command still runs successfully
    assert (result.returncode, result.stdout, result.stderr) == (
        0,
        "",
        "ask: warning: configuration has changed since the container was last "
        "converged; run `ask converge` to apply it\n",
    )


def test_ask_does_not_warn_about_a_changed_configuration_when_told_not_to_converge(
    tmp_path: Path,
) -> None:
    # given a project directory whose running container was never converged
    project_dir, env = _project_with_an_unconverged_container(tmp_path)

    # when running ask exec --no-converge without a terminal
    result = subprocess.run(
        [str(ASK), "exec", "--no-converge", "true"],
        cwd=project_dir,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )

    # then nothing is printed, and the command runs successfully
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_ask_reports_an_unknown_tool_manager_without_a_traceback(
    tmp_path: Path,
) -> None:
    # given a project directory whose ask.toml opts into a tool manager ask
    # doesn't support
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('tool_managers = ["asdf"]\n')

    # and an empty global configuration directory
    config_home = tmp_path / "config"
    config_home.mkdir()

    # when running ask converge from within the project directory
    result = subprocess.run(
        [str(ASK), "converge"],
        cwd=project_dir,
        env={
            "PATH": "/usr/bin:/bin",
            "XDG_CONFIG_HOME": str(config_home),
            "COLUMNS": str(TERMINAL_WIDTH),
        },
        capture_output=True,
        text=True,
    )

    # then the unknown tool manager is reported along with the supported ones,
    # and ask exits with status 1
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        _error_panel(
            f"Invalid configuration in {project_dir / 'ask.toml'}:",
            "  tool_managers.0: unknown tool manager 'asdf' (known: mise)",
        ),
    )


def test_ask_reports_a_project_no_flavor_applies_to_without_a_traceback(
    tmp_path: Path,
) -> None:
    # given a project directory with a valid ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")

    # and a single flavour that is not the default and applies to another path
    config_home = tmp_path / "config"
    (config_home / "ask" / "flavors").mkdir(parents=True)
    (config_home / "ask" / "flavors" / "debian.toml").write_text(
        'distribution = "arch"\ndefault = false\nwhen.path = ["/elsewhere"]\n'
    )

    # when running ask converge from within the project directory
    result = subprocess.run(
        [str(ASK), "converge"],
        cwd=project_dir,
        env={
            "PATH": "/usr/bin:/bin",
            "XDG_CONFIG_HOME": str(config_home),
            "COLUMNS": str(TERMINAL_WIDTH),
        },
        capture_output=True,
        text=True,
    )

    # then the missing flavour is reported, and ask exits with status 1
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        _error_panel(
            f"No flavour applies to {project_dir}. Add a flavour whose when.path "
            "matches it, or mark one with default = true."
        ),
    )


def test_ask_restarts_a_running_container(tmp_path: Path) -> None:
    # given a project directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    # and an incus command that knows of a running container for the project,
    # and records how it is invoked
    invocations = tmp_path / "invocations"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_incus = fake_bin / "incus"
    fake_incus.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {invocations}\n'
        'if [ "$1" = list ]; then\n'
        '  echo \'[{"name": "my-project", "status": "Running", "config": {}}]\'\n'
        "fi\n"
    )
    fake_incus.chmod(0o755)

    # when running ask restart from within the project directory
    result = subprocess.run(
        [str(ASK), "restart"],
        cwd=project_dir,
        env={"PATH": str(fake_bin)},
        capture_output=True,
        text=True,
    )

    # then ask succeeds silently, having asked incus to restart the container
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert invocations.read_text() == (
        "list my-project --format json\nrestart my-project\n"
    )
