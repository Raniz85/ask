from pathlib import Path
from unittest.mock import patch

from ask.cli import converge, create


def test_create_launches_container_and_converges(tmp_path: Path) -> None:
    # given a project directory with an ask.toml declaring a distribution
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')

    # when running create from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.create_container") as create_container,
        patch("ask.cli.converge") as converge_mock,
    ):
        create()

    # then a container named after the project directory is launched for that
    # distribution, and converge is run to apply the rest of the configuration
    create_container.assert_called_once_with("my-project", "arch")
    converge_mock.assert_called_once_with()


def test_converge_applies_resolved_bind_mounts_including_project_dir(tmp_path: Path) -> None:
    # given a project directory with ask.toml declaring a bind mount and a layer,
    # and a config declaring that layer's bind mount
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'distribution = "arch"\nbind_mounts = ["/configured/mount"]\nlayers = ["python"]\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.python]\nbind_mounts = ["/layer/mount"]\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.converge") as incus_converge,
    ):
        converge()

    # then the instance is converged with the project directory plus every resolved
    # bind mount (project-level and layer-level)
    incus_converge.assert_called_once_with(
        "my-project",
        [project_dir, Path("/configured/mount"), Path("/layer/mount")],
    )
