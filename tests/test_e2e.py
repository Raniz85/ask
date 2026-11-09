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
