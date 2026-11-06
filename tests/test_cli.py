from pathlib import Path
from unittest.mock import patch

from ask.cli import converge, create
from ask.config import ResolvedUser


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


def test_converge_applies_resolved_bind_mounts_including_project_dir(
    tmp_path: Path,
) -> None:
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
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then the instance is converged with the project directory plus every resolved
    # bind mount (project-level and layer-level)
    incus_converge.assert_called_once_with(
        "my-project",
        [project_dir, Path("/configured/mount"), Path("/layer/mount")],
    )


def test_converge_provisions_the_resolved_user(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.provision.provision_user") as provision_user,
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then the resolved user is provisioned into the container
    provision_user.assert_called_once_with(
        "my-project",
        ResolvedUser(
            name="raniz",
            uid=1000,
            shell="zsh",
            group_name="raniz",
            gid=1000,
            extra_groups=[],
        ),
    )


def test_converge_provisions_the_resolved_packages(tmp_path: Path) -> None:
    # given a project directory with ask.toml declaring packages and a layer,
    # and a config declaring that layer's packages
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'distribution = "arch"\npackages.arch = ["project-pkg"]\nlayers = ["python"]\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.python]\npackages.common = ["layer-pkg"]\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages") as provision_packages,
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then the resolved packages (project-level and layer-level) are
    # provisioned for the manifest's distribution, along with the package
    # required by the (default) shell
    provision_packages.assert_called_once_with(
        "my-project", "arch", ["project-pkg", "layer-pkg", "bash"]
    )


def test_converge_includes_the_configured_shells_own_package(tmp_path: Path) -> None:
    # given a project directory with no packages of its own, and a config
    # declaring zsh as the shell
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages") as provision_packages,
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then zsh's own package is included among the packages to provision
    provision_packages.assert_called_once_with("my-project", "arch", ["zsh"])


def test_converge_mounts_the_resolved_shells_rc_file_readonly(tmp_path: Path) -> None:
    # given a project directory, a config declaring zsh as the shell and a
    # user, and a host home directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n')
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc") as converge_shell_rc,
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then the shell's rc file is mounted read-only, from the calling host's
    # home directory to the matching file under the resolved container user's
    # home
    converge_shell_rc.assert_called_once_with(
        "my-project", home_dir / ".zshrc", Path("/home/raniz/.zshrc")
    )


def test_converge_fixes_bind_mount_ownership_after_provisioning_the_user(
    tmp_path: Path,
) -> None:
    # given a project directory with ask.toml declaring a bind mount, and a config
    # declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'distribution = "arch"\nbind_mounts = ["/home/raniz/.cache/uv"]\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership") as fix_ownership,
    ):
        converge()

    # then bind mount ownership is fixed for the resolved user, using the same
    # bind mounts applied to the instance
    fix_ownership.assert_called_once_with(
        "my-project",
        [project_dir, Path("/home/raniz/.cache/uv")],
        ResolvedUser(
            name="raniz",
            uid=1000,
            shell="zsh",
            group_name="raniz",
            gid=1000,
            extra_groups=[],
        ),
    )
