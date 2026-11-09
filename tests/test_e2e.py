import subprocess
import sys
from pathlib import Path

ASK = Path(sys.executable).parent / "ask"


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
        env={"PATH": "/usr/bin:/bin", "XDG_CONFIG_HOME": str(config_home)},
        capture_output=True,
        text=True,
    )

    # then a one-line error is printed and ask exits with status 1
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        f"ask: no ask.toml found in {project_dir} "
        "(ask must be run from a project directory containing ask.toml)\n",
    )


def test_ask_reports_a_missing_incus_binary_without_a_traceback(
    tmp_path: Path,
) -> None:
    # given a project directory with a valid ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')

    # and an empty global configuration directory
    config_home = tmp_path / "config"
    config_home.mkdir()

    # and a PATH on which there is no incus command
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()

    # when running ask enter from within the project directory
    result = subprocess.run(
        [str(ASK), "enter"],
        cwd=project_dir,
        env={"PATH": str(empty_bin), "XDG_CONFIG_HOME": str(config_home)},
        capture_output=True,
        text=True,
    )

    # then a one-line error is printed and ask exits with status 1
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        "ask: incus command not found; is Incus installed and on PATH?\n",
    )


def test_ask_does_not_offer_to_create_a_missing_container_without_a_terminal(
    tmp_path: Path,
) -> None:
    # given a project directory with a valid ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')

    # and an empty global configuration directory
    config_home = tmp_path / "config"
    config_home.mkdir()

    # and an incus command that knows of no containers
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_incus = fake_bin / "incus"
    fake_incus.write_text(
        '#!/bin/sh\nif [ "$1" = list ]; then echo "[]"; fi\n'
    )
    fake_incus.chmod(0o755)

    # when running ask enter from within the project directory, with "yes"
    # piped to stdin rather than a terminal
    result = subprocess.run(
        [str(ASK), "enter"],
        cwd=project_dir,
        env={"PATH": str(fake_bin), "XDG_CONFIG_HOME": str(config_home)},
        input="y\n",
        capture_output=True,
        text=True,
    )

    # then the user is not asked anything, a one-line error is printed and ask
    # exits with status 1
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        "ask: no container named 'my-project'; run `ask create` first\n",
    )


def test_ask_creates_a_missing_container_without_asking_when_requested(
    tmp_path: Path,
) -> None:
    # given a project directory with a valid ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')

    # and an empty global configuration directory
    config_home = tmp_path / "config"
    config_home.mkdir()

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

    # when running ask --create exec from within the project directory
    result = subprocess.run(
        [str(ASK), "--create", "exec", "true"],
        cwd=project_dir,
        env={"PATH": str(fake_bin), "XDG_CONFIG_HOME": str(config_home)},
        capture_output=True,
        text=True,
    )

    # then the user is not asked anything, and the container is launched
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "",
        "refused\n"
        "ask: `incus launch images:archlinux/current my-project "
        "--config security.nesting=true --config security.privileged=false` "
        "failed with exit status 1\n",
    )


def _project_with_an_unconverged_container(tmp_path: Path) -> tuple[Path, dict]:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_home = tmp_path / "config"
    config_home.mkdir()
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

    # when running ask --no-converge exec without a terminal
    result = subprocess.run(
        [str(ASK), "--no-converge", "exec", "true"],
        cwd=project_dir,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )

    # then nothing is printed, and the command runs successfully
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
