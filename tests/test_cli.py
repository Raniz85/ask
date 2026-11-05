from pathlib import Path
from unittest.mock import patch

from ask.cli import create


def test_create_launches_container_named_after_project_directory(tmp_path: Path) -> None:
    # given a project directory with an ask.toml declaring a distribution
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')

    # when running create from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.create_container") as create_container,
    ):
        create()

    # then a container named after the project directory is created for that distribution,
    # bind-mounting the project directory itself, with no additional configured mounts
    create_container.assert_called_once_with("my-project", "arch", project_dir, bind_mounts=[])


def test_create_passes_configured_bind_mounts(tmp_path: Path) -> None:
    # given a project directory with ask.toml declaring bind_mounts
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'distribution = "arch"\nbind_mounts = ["/home/raniz/.config/foo"]\n'
    )

    # when running create from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.create_container") as create_container,
    ):
        create()

    # then the configured bind mounts are passed through to container creation
    create_container.assert_called_once_with(
        "my-project", "arch", project_dir, bind_mounts=[Path("/home/raniz/.config/foo")]
    )
