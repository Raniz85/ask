from pathlib import Path
from unittest.mock import patch

import pytest

from ask.cli import converge, create, enter, exec
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


def test_converge_starts_the_container_when_not_already_running(
    tmp_path: Path,
) -> None:
    # given a project directory, and a container that is not currently running
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=False),
        patch("ask.cli.incus.start_container") as start_container,
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.remove_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then the container is started before the rest of convergence runs
    start_container.assert_called_once_with("my-project")


def test_converge_does_not_start_an_already_running_container(
    tmp_path: Path,
) -> None:
    # given a project directory, and a container that is already running
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.start_container") as start_container,
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.remove_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then it is not started again
    start_container.assert_not_called()


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
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge") as incus_converge,
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.remove_packages"),
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
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user") as provision_user,
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.remove_packages"),
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
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages") as provision_packages,
        patch("ask.cli.provision.remove_packages"),
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
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages") as provision_packages,
        patch("ask.cli.provision.remove_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then zsh's own package is included among the packages to provision
    provision_packages.assert_called_once_with("my-project", "arch", ["zsh"])


def test_converge_installs_declared_aur_packages_separately(tmp_path: Path) -> None:
    # given a project directory declaring an aur-prefixed package alongside an
    # official one
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'distribution = "arch"\npackages.arch = ["aur:yay-bin", "git"]\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages") as set_managed_packages,
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages") as provision_packages,
        patch("ask.cli.provision.provision_aur_packages") as provision_aur_packages,
        patch("ask.cli.provision.remove_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then the official packages go through the regular pacman path, the aur
    # package goes through the aur path with its prefix stripped, and the
    # tracked managed set records both by their plain names
    provision_packages.assert_called_once_with("my-project", "arch", ["git", "bash"])
    provision_aur_packages.assert_called_once_with("my-project", "arch", ["yay-bin"])
    set_managed_packages.assert_called_once_with("my-project", ["git", "bash", "yay-bin"])


def test_converge_removes_a_package_that_is_no_longer_declared_as_aur(
    tmp_path: Path,
) -> None:
    # given a project directory that no longer declares a package the
    # container previously tracked as aur-installed
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch(
            "ask.cli.incus.get_managed_packages",
            return_value=["bash", "yay-bin"],
        ),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.provision_aur_packages"),
        patch("ask.cli.provision.remove_packages") as remove_packages,
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then it is removed the same way as any other stale package, regardless
    # of how it was originally installed
    remove_packages.assert_called_once_with("my-project", "arch", ["yay-bin"])


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
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc") as converge_shell_rc,
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.remove_packages"),
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then the shell's rc file is mounted read-only, from the calling host's
    # home directory to the matching file under the resolved container user's
    # home
    converge_shell_rc.assert_called_once_with(
        "my-project", home_dir / ".zshrc", Path("/home/raniz/.zshrc")
    )


def test_converge_removes_packages_no_longer_declared(tmp_path: Path) -> None:
    # given a project directory declaring one package, and a container that
    # was previously managing that package plus one no longer declared
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'distribution = "arch"\npackages.arch = ["project-pkg"]\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch(
            "ask.cli.incus.get_managed_packages",
            return_value=["project-pkg", "bash", "stale-pkg"],
        ),
        patch("ask.cli.incus.set_managed_packages") as set_managed_packages,
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.remove_packages") as remove_packages,
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then the package no longer declared is removed, and the newly resolved
    # set of packages becomes the tracked set for next time
    remove_packages.assert_called_once_with("my-project", "arch", ["stale-pkg"])
    set_managed_packages.assert_called_once_with("my-project", ["project-pkg", "bash"])


def test_converge_does_not_remove_packages_when_nothing_is_stale(
    tmp_path: Path,
) -> None:
    # given a project directory declaring the same package the container
    # already tracks as managed
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'distribution = "arch"\npackages.arch = ["project-pkg"]\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch(
            "ask.cli.incus.get_managed_packages",
            return_value=["project-pkg", "bash"],
        ),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.remove_packages") as remove_packages,
        patch("ask.cli.provision.fix_bind_mount_ownership"),
    ):
        converge()

    # then nothing is removed
    remove_packages.assert_not_called()


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
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.converge"),
        patch("ask.cli.incus.converge_shell_rc"),
        patch("ask.cli.incus.get_managed_packages", return_value=[]),
        patch("ask.cli.incus.set_managed_packages"),
        patch("ask.cli.provision.provision_user"),
        patch("ask.cli.provision.provision_packages"),
        patch("ask.cli.provision.remove_packages"),
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


def test_enter_starts_the_container_when_not_already_running(tmp_path: Path) -> None:
    # given a project directory, and a container that is not currently running
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=False),
        patch("ask.cli.incus.start_container") as start_container,
        patch("ask.cli.incus.exec_command", return_value=0),
        pytest.raises(SystemExit),
    ):
        enter()

    # then the container is started before entering
    start_container.assert_called_once_with("my-project")


def test_enter_does_not_start_an_already_running_container(tmp_path: Path) -> None:
    # given a project directory, and a container that is already running
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.start_container") as start_container,
        patch("ask.cli.incus.exec_command", return_value=0),
        pytest.raises(SystemExit),
    ):
        enter()

    # then it is not started again
    start_container.assert_not_called()


def test_enter_runs_the_resolved_users_shell(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user and shell
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.start_container"),
        patch("ask.cli.incus.exec_command", return_value=0) as exec_command,
        pytest.raises(SystemExit) as exc_info,
    ):
        enter()

    # then the resolved shell is executed in the container as the resolved
    # user, in the project directory, and ask exits with its exit code
    exec_command.assert_called_once_with(
        "my-project", 1000, 1000, project_dir, ["zsh"]
    )
    assert exc_info.value.code == 0


def test_enter_propagates_a_non_zero_exit_code(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when the entered shell exits non-zero
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.start_container"),
        patch("ask.cli.incus.exec_command", return_value=3),
        pytest.raises(SystemExit) as exc_info,
    ):
        enter()

    # then ask exits with that same code, rather than raising
    assert exc_info.value.code == 3


def test_exec_starts_the_container_when_not_already_running(tmp_path: Path) -> None:
    # given a project directory, and a container that is not currently running
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=False),
        patch("ask.cli.incus.start_container") as start_container,
        patch("ask.cli.incus.exec_command", return_value=0),
        pytest.raises(SystemExit),
    ):
        exec("ls", "-la")

    # then the container is started before the command is executed
    start_container.assert_called_once_with("my-project")


def test_exec_does_not_start_an_already_running_container(tmp_path: Path) -> None:
    # given a project directory, and a container that is already running
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.start_container") as start_container,
        patch("ask.cli.incus.exec_command", return_value=0),
        pytest.raises(SystemExit),
    ):
        exec("ls", "-la")

    # then it is not started again
    start_container.assert_not_called()


def test_exec_runs_the_command_as_the_resolved_user(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.start_container"),
        patch("ask.cli.incus.exec_command", return_value=0) as exec_command,
        pytest.raises(SystemExit) as exc_info,
    ):
        exec("ls", "-la")

    # then the command is executed in the container as the resolved user, in
    # the project directory, and ask exits with the command's exit code
    exec_command.assert_called_once_with(
        "my-project", 1000, 1000, project_dir, ["ls", "-la"]
    )
    assert exc_info.value.code == 0


def test_exec_propagates_a_non_zero_exit_code(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when the executed command exits non-zero
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.is_running", return_value=True),
        patch("ask.cli.incus.start_container"),
        patch("ask.cli.incus.exec_command", return_value=3),
        pytest.raises(SystemExit) as exc_info,
    ):
        exec("false")

    # then ask exits with that same code, rather than raising
    assert exc_info.value.code == 3
