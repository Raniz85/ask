from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from ask.agent import AgentError
from ask.cli import FAKE_SSH_ENV, agent, converge, create, enter, exec
from ask.config import ConfigError
from ask.incus import ContainerExistsError, ContainerNotFoundError, Mount
from ask.user import ResolvedUser

_WAYLAND_MOUNT = Mount(
    host_path=Path("/run/user/1000/wayland-0"),
    container_path=Path("/home/raniz/.wayland-socket"),
)
_WAYLAND_ENV = {"WAYLAND_DISPLAY": "/home/raniz/.wayland-socket"}


def test_create_launches_container_and_converges(tmp_path: Path) -> None:
    # given a project directory with an ask.toml declaring a distribution
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when running create from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container.create") as container_create,
        patch("ask.cli.incus.Container.exists", return_value=False),
        patch("ask.cli.converge") as converge_mock,
    ):
        create()

    # then a container named after the project directory is launched for that
    # distribution, and converge is run to apply the rest of the configuration
    container_create.assert_called_once_with("my-project", "arch")
    converge_mock.assert_called_once_with()


def test_create_rejects_a_container_that_already_exists(tmp_path: Path) -> None:
    # given a project directory with a valid ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # and a container for the project that already exists
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container.exists", return_value=True),
        patch("ask.cli.incus.Container.create") as container_create,
        patch("ask.cli.converge") as converge_mock,
        pytest.raises(ContainerExistsError) as error,
    ):
        # when running create from within that project directory
        create()

    # then the error says how to update the container instead, and nothing is
    # launched or converged
    assert str(error.value) == (
        "container 'my-project' already exists; run `ask converge` to update it"
    )
    container_create.assert_not_called()
    converge_mock.assert_not_called()


def test_create_rejects_an_unknown_distribution_before_launching(
    tmp_path: Path,
) -> None:
    # given a project directory with an ask.toml using an unsupported distribution
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "gentoo"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when running create from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container.create") as container_create,
        pytest.raises(ConfigError) as error,
    ):
        create()

    # then the distribution is reported and no container is launched
    assert error.value.problems == [
        "distribution: unknown distribution 'gentoo' (known: arch)"
    ]
    container_create.assert_not_called()


def test_converge_rejects_undefined_layers_before_touching_the_container(
    tmp_path: Path,
) -> None:
    # given a project directory with an ask.toml using a layer the global
    # config doesn't define
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nlayers = ["rust"]\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ConfigError) as error,
    ):
        converge()

    # then the layer is reported and the container is never targeted
    assert error.value.problems == [
        "layers.0: layer 'rust' is not defined in the global config (known: none)"
    ]
    container_cls.assert_not_called()


def test_converge_ensures_the_targeted_container_is_running(
    tmp_path: Path,
) -> None:
    # given a project directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the container named after the project directory is targeted, and
    # ensured to be running before the rest of convergence runs
    container_cls.assert_called_once_with("my-project")
    container.ensure_running.assert_called_once_with()
    provisioner_cls.assert_called_once_with(container)


def test_converge_applies_resolved_bind_mounts_including_project_dir(
    tmp_path: Path,
) -> None:
    # given a project directory with ask.toml declaring a bind mount and a layer,
    # and a config declaring that layer's bind mount
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    configured_mount = tmp_path / "configured-mount"
    configured_mount.mkdir()
    layer_mount = tmp_path / "layer-mount"
    layer_mount.mkdir()
    (project_dir / "ask.toml").write_text(
        f'distribution = "arch"\nbind_mounts = ["{configured_mount}"]\n'
        'layers = ["python"]\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[layers.python]\nbind_mounts = ["{layer_mount}"]\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the instance is converged with the project directory plus every resolved
    # bind mount (layer-level, then project-level), alongside the shell rc mount
    container.converge.assert_called_once_with(
        [
            Mount(host_path=project_dir, container_path=project_dir),
            Mount(host_path=layer_mount, container_path=layer_mount),
            Mount(host_path=configured_mount, container_path=configured_mount),
            Mount(
                host_path=home_dir / ".bashrc",
                container_path=Path("/home/raniz/.bashrc"),
                readonly=True,
            ),
        ]
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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the resolved user is provisioned into the container
    provisioner_cls.return_value.provision_user.assert_called_once_with(
        ResolvedUser(
            name="raniz",
            uid=1000,
            shell="zsh",
            group_name="raniz",
            gid=1000,
            extra_groups=[],
        ),
    )


def test_converge_provisions_the_user_before_mounting_home_relative_paths(
    tmp_path: Path,
) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    call_order: list[str] = []

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []
        container.converge.side_effect = lambda *a, **k: call_order.append("converge")
        provisioner_cls.return_value.provision_user.side_effect = lambda *a, **k: (
            call_order.append("provision_user")
        )

        converge()

    # then the user, and therefore their home directory, is provisioned
    # before any home-relative path (shell rc, agent state) is mounted into
    # the container, since the mount's container-side ancestor directories
    # must already exist
    assert call_order == ["provision_user", "converge"]


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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the resolved packages (layer-level, then project-level) are
    # provisioned for the manifest's distribution, along with the package
    # required by the (default) shell
    provisioner_cls.return_value.provision_packages.assert_called_once_with(
        "arch", ["layer-pkg", "project-pkg", "bash"]
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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then zsh's own package is included among the packages to provision
    provisioner_cls.return_value.provision_packages.assert_called_once_with(
        "arch", ["zsh"]
    )


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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder") as aur_builder_cls,
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the official packages go through the regular pacman path, the aur
    # package goes through the aur path with its prefix stripped, and the
    # tracked managed set records both by their plain names
    provisioner_cls.return_value.provision_packages.assert_called_once_with(
        "arch", ["git", "bash"]
    )
    aur_builder_cls.return_value.install_packages.assert_called_once_with(
        "arch", ["yay-bin"]
    )
    container.set_managed_packages.assert_called_once_with(["git", "bash", "yay-bin"])


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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = ["bash", "yay-bin"]

        converge()

    # then it is removed the same way as any other stale package, regardless
    # of how it was originally installed
    provisioner_cls.return_value.remove_packages.assert_called_once_with(
        "arch", ["yay-bin"]
    )


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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the shell's rc file is mounted read-only, from the calling host's
    # home directory to the matching file under the resolved container user's
    # home, alongside the project directory mount
    container.converge.assert_called_once_with(
        [
            Mount(host_path=project_dir, container_path=project_dir),
            Mount(
                host_path=home_dir / ".zshrc",
                container_path=Path("/home/raniz/.zshrc"),
                readonly=True,
            ),
        ]
    )


def test_converge_mounts_the_shell_files_enabled_by_its_options(
    tmp_path: Path,
) -> None:
    # given a project directory, a config declaring zsh as the shell with its
    # rc file disabled and zprofile enabled, and a host home directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[shell]\nname = "zsh"\nzshrc = false\nzprofile = true\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then only zprofile is mounted read-only, alongside the project directory
    container.converge.assert_called_once_with(
        [
            Mount(host_path=project_dir, container_path=project_dir),
            Mount(
                host_path=home_dir / ".zprofile",
                container_path=Path("/home/raniz/.zprofile"),
                readonly=True,
            ),
        ]
    )


def test_converge_installs_declared_agent_packages(tmp_path: Path) -> None:
    # given a project directory using a layer that declares the claude agent
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nlayers = ["base"]\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.base]\nagents = ["claude"]\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder") as aur_builder_cls,
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the agent's aur-prefixed package is installed through the aur
    # path, alongside the default shell's official package
    provisioner_cls.return_value.provision_packages.assert_called_once_with(
        "arch", ["bash"]
    )
    aur_builder_cls.return_value.install_packages.assert_called_once_with(
        "arch", ["claude-code"]
    )
    container.set_managed_packages.assert_called_once_with(["bash", "claude-code"])


def test_converge_mounts_agent_state_when_shared_state_is_enabled(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares the claude agent
    # with shared state enabled, a resolved user, and a host home directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nlayers = ["base"]\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[layers.base]\nagents = ["claude"]\nshared_state = true\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    for state_path in [
        ".claude/CLAUDE.md",
        ".claude/.credentials.json",
        ".claude/skills",
        ".claude.json",
        ".claude/settings.json",
    ]:
        path = home_dir / state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then each of the agent's state paths is mounted from the calling host's
    # home directory to the matching path under the resolved container user's
    # home, alongside the project directory and shell rc mounts
    container.converge.assert_called_once_with(
        [
            Mount(host_path=project_dir, container_path=project_dir),
            Mount(
                host_path=home_dir / ".bashrc",
                container_path=Path("/home/raniz/.bashrc"),
                readonly=True,
            ),
            Mount(
                host_path=home_dir / ".claude" / "CLAUDE.md",
                container_path=Path("/home/raniz/.claude/CLAUDE.md"),
            ),
            Mount(
                host_path=home_dir / ".claude" / ".credentials.json",
                container_path=Path("/home/raniz/.claude/.credentials.json"),
            ),
            Mount(
                host_path=home_dir / ".claude" / "skills",
                container_path=Path("/home/raniz/.claude/skills"),
            ),
            Mount(
                host_path=home_dir / ".claude.json",
                container_path=Path("/home/raniz/.claude.json"),
            ),
            Mount(
                host_path=home_dir / ".claude" / "settings.json",
                container_path=Path("/home/raniz/.claude/settings.json"),
            ),
        ]
    )


def test_converge_does_not_mount_agent_state_without_shared_state(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares the claude agent
    # without enabling shared state
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nlayers = ["base"]\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[layers.base]\nagents = ["claude"]\n[user]\nname = "raniz"\nuid = 1000\n'
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then no agent state is mounted, just the project directory and shell rc
    # mounts
    container.converge.assert_called_once_with(
        [
            Mount(host_path=project_dir, container_path=project_dir),
            Mount(
                host_path=home_dir / ".bashrc",
                container_path=Path("/home/raniz/.bashrc"),
                readonly=True,
            ),
        ]
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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = [
            "project-pkg",
            "bash",
            "stale-pkg",
        ]

        converge()

    # then the package no longer declared is removed, and the newly resolved
    # set of packages becomes the tracked set for next time
    provisioner_cls.return_value.remove_packages.assert_called_once_with(
        "arch", ["stale-pkg"]
    )
    container.set_managed_packages.assert_called_once_with(["project-pkg", "bash"])


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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = ["project-pkg", "bash"]

        converge()

    # then nothing is removed
    provisioner_cls.return_value.remove_packages.assert_not_called()


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
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then bind mount ownership is fixed for the resolved user, covering every
    # mount applied to the instance (including the shell rc file's container
    # path, so its ancestor directories end up owned by the user too)
    provisioner_cls.return_value.fix_bind_mount_ownership.assert_called_once_with(
        [
            project_dir,
            Path("/home/raniz/.cache/uv"),
            Path("/home/raniz/.zshrc"),
        ],
        ResolvedUser(
            name="raniz",
            uid=1000,
            shell="zsh",
            group_name="raniz",
            gid=1000,
            extra_groups=[],
        ),
    )


def test_converge_fixes_agent_state_mount_ownership_when_shared_state_is_enabled(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares the claude agent
    # with shared state enabled
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nlayers = ["base"]\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[layers.base]\nagents = ["claude"]\nshared_state = true\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    for state_path in [
        ".claude/CLAUDE.md",
        ".claude/.credentials.json",
        ".claude/skills",
        ".claude.json",
        ".claude/settings.json",
    ]:
        path = home_dir / state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then ownership is fixed using every one of the agent's state paths too,
    # so e.g. the shared ~/.claude ancestor directory ends up owned by the
    # user, not just the project directory and shell rc mounts
    provisioner_cls.return_value.fix_bind_mount_ownership.assert_called_once_with(
        [
            project_dir,
            Path("/home/raniz/.bashrc"),
            Path("/home/raniz/.claude/CLAUDE.md"),
            Path("/home/raniz/.claude/.credentials.json"),
            Path("/home/raniz/.claude/skills"),
            Path("/home/raniz/.claude.json"),
            Path("/home/raniz/.claude/settings.json"),
        ],
        ResolvedUser(
            name="raniz",
            uid=1000,
            shell="bash",
            group_name="raniz",
            gid=1000,
            extra_groups=[],
        ),
    )


def test_enter_ensures_the_targeted_container_is_running(tmp_path: Path) -> None:
    # given a project directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        enter()

    # then the container named after the project directory is targeted, and
    # ensured to be running before entering
    container_cls.assert_called_once_with("my-project")
    container.ensure_running.assert_called_once_with()


def test_enter_rejects_an_unknown_shell_before_touching_the_container(
    tmp_path: Path,
) -> None:
    # given a project directory, and a config declaring an unsupported shell
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "foosh"\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ConfigError) as error,
    ):
        enter()

    # then the shell is reported and the container is never targeted
    assert error.value.problems == [
        "shell.name: unknown shell 'foosh' (known: bash, elvish, fish, ksh, tcsh, zsh)"
    ]
    container_cls.assert_not_called()


def test_enter_runs_the_resolved_users_shell(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user and shell
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        enter()

    # then the resolved shell is executed in the right container, as the
    # resolved user, in the project directory, with environment variables
    # that make it look like an SSH session, and ask exits with its exit code
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["zsh"], env=FAKE_SSH_ENV
    )
    assert exc_info.value.code == 0


def test_enter_propagates_a_non_zero_exit_code(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when the entered shell exits non-zero
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 3

        enter()

    # then ask exits with that same code, rather than raising
    assert exc_info.value.code == 3


def test_enter_forwards_wayland_display_when_gui_is_requested(tmp_path: Path) -> None:
    # given a project directory, a config declaring a user, and a live
    # wayland session
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.gui.wayland_mount", return_value=_WAYLAND_MOUNT),
        patch("ask.gui.acquire") as acquire_mock,
        patch("ask.gui.release") as release_mock,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        enter(gui=True)

    # then the gui session is acquired before, and released after, running
    # the resolved shell with the wayland display environment variable
    # merged into the fake ssh environment
    acquire_mock.assert_called_once_with(container, _WAYLAND_MOUNT)
    release_mock.assert_called_once_with(container, _WAYLAND_MOUNT)
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=FAKE_SSH_ENV | _WAYLAND_ENV
    )
    assert exc_info.value.code == 0


def test_enter_does_not_forward_anything_when_gui_requested_without_a_session(
    tmp_path: Path,
) -> None:
    # given a project directory, a config declaring a user, and no live
    # wayland session on the host
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.gui.wayland_mount", return_value=None),
        patch("ask.gui.acquire") as acquire_mock,
        patch("ask.gui.release") as release_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        enter(gui=True)

    # then no gui session is acquired or released, and the shell runs with
    # just the fake ssh environment, exactly as without --gui
    acquire_mock.assert_not_called()
    release_mock.assert_not_called()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=FAKE_SSH_ENV
    )


def test_enter_creates_a_missing_container_when_the_user_accepts(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container and accepting the offer to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("builtins.input", return_value="y"),
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exists.return_value = False
        container.exec_command.return_value = 0

        enter()

    # then the container is created, and the shell is run in it afterwards
    create_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=FAKE_SSH_ENV
    )


def test_enter_creates_a_missing_container_when_the_user_accepts_the_default(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container and answering the offer with just enter
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("builtins.input", return_value=""),
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exists.return_value = False
        container.exec_command.return_value = 0

        enter()

    # then the container is created
    create_mock.assert_called_once_with()


def test_enter_refuses_a_missing_container_when_the_user_declines(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container and declining the offer to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("builtins.input", return_value="n"),
        patch("ask.cli.create") as create_mock,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        container = container_cls.return_value
        container.exists.return_value = False

        enter()

    # then nothing is created or run, and the user is told how to create it
    assert str(error.value) == (
        "no container named 'my-project'; run `ask create` first"
    )
    create_mock.assert_not_called()
    container.exec_command.assert_not_called()


def test_enter_refuses_a_missing_container_when_stdin_is_closed(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container without an answer being available on stdin
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("builtins.input", side_effect=EOFError),
        patch("ask.cli.create") as create_mock,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        container = container_cls.return_value
        container.exists.return_value = False

        enter()

    # then nothing is created or run, and the user is told how to create it
    assert str(error.value) == (
        "no container named 'my-project'; run `ask create` first"
    )
    create_mock.assert_not_called()
    container.exec_command.assert_not_called()


def test_enter_does_not_offer_to_create_an_existing_container(
    tmp_path: Path,
) -> None:
    # given a project directory with an existing container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("builtins.input") as input_mock,
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exists.return_value = True
        container.exec_command.return_value = 0

        enter()

    # then the user is not asked anything, and nothing is created
    input_mock.assert_not_called()
    create_mock.assert_not_called()


def test_exec_ensures_the_targeted_container_is_running(tmp_path: Path) -> None:
    # given a project directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        exec("ls", "-la")

    # then the container named after the project directory is targeted, and
    # ensured to be running before the command is executed
    container_cls.assert_called_once_with("my-project")
    container.ensure_running.assert_called_once_with()


def test_exec_creates_a_missing_container_when_the_user_accepts(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command and accepting the offer to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("builtins.input", return_value="y"),
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exists.return_value = False
        container.exec_command.return_value = 0

        exec("ls", "-la")

    # then the container is created, and the command is run in it afterwards
    create_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["ls", "-la"]
    )


def test_exec_runs_the_command_as_the_resolved_user(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        exec("ls", "-la")

    # then the command is executed in the right container as the resolved
    # user, in the project directory, and ask exits with the command's exit
    # code
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["ls", "-la"]
    )
    assert exc_info.value.code == 0


def test_exec_propagates_a_non_zero_exit_code(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when the executed command exits non-zero
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 3

        exec("false")

    # then ask exits with that same code, rather than raising
    assert exc_info.value.code == 3


def test_exec_forwards_wayland_display_when_gui_is_requested(tmp_path: Path) -> None:
    # given a project directory, a config declaring a user, and a live
    # wayland session
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.gui.wayland_mount", return_value=_WAYLAND_MOUNT),
        patch("ask.gui.acquire") as acquire_mock,
        patch("ask.gui.release") as release_mock,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        exec("ls", "-la", gui=True)

    # then the gui session is acquired before, and released after, running
    # the command with the wayland display environment variable set
    acquire_mock.assert_called_once_with(container, _WAYLAND_MOUNT)
    release_mock.assert_called_once_with(container, _WAYLAND_MOUNT)
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["ls", "-la"], env=_WAYLAND_ENV
    )
    assert exc_info.value.code == 0


def test_exec_passes_no_env_when_gui_requested_without_a_session(
    tmp_path: Path,
) -> None:
    # given a project directory, a config declaring a user, and no live
    # wayland session on the host
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.gui.wayland_mount", return_value=None),
        patch("ask.gui.acquire") as acquire_mock,
        patch("ask.gui.release") as release_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        exec("ls", "-la", gui=True)

    # then no gui session is acquired or released, and the command runs with
    # no env argument at all, exactly as without --gui
    acquire_mock.assert_not_called()
    release_mock.assert_not_called()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["ls", "-la"]
    )


def test_agent_rejects_undefined_layers_before_touching_the_container(
    tmp_path: Path,
) -> None:
    # given a project directory with an ask.toml using a layer the global
    # config doesn't define
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nlayers = ["rust"]\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when launching an agent without naming one
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ConfigError) as error,
    ):
        agent()

    # then the layer is reported and the container is never targeted
    assert error.value.problems == [
        "layers.0: layer 'rust' is not defined in the global config (known: none)"
    ]
    container_cls.assert_not_called()


def test_agent_launches_the_first_configured_agent_when_none_given(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares two agents, and a
    # resolved user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nlayers = ["base"]\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[layers.base]\nagents = ["claude", "codex"]\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when launching an agent without naming one
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent()

    # then the first configured agent is executed in the container as the
    # resolved user, in the project directory, and ask exits with its exit
    # code
    container.exec_command.assert_called_once_with(1000, 1000, project_dir, ["claude"])
    assert exc_info.value.code == 0


def test_agent_launches_the_named_agent_when_given(tmp_path: Path) -> None:
    # given a project directory with no agents configured, and a resolved user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent by name
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent("claude")

    # then the named agent is executed, regardless of what is configured
    container_cls.assert_called_once_with("my-project")
    container.exec_command.assert_called_once_with(1000, 1000, project_dir, ["claude"])
    assert exc_info.value.code == 0


def test_agent_ensures_the_targeted_container_is_running(tmp_path: Path) -> None:
    # given a project directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent("claude")

    # then the container named after the project directory is targeted, and
    # ensured to be running before the agent is executed
    container_cls.assert_called_once_with("my-project")
    container.ensure_running.assert_called_once_with()


def test_agent_creates_a_missing_container_when_the_user_accepts(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent and accepting the offer to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("builtins.input", return_value="y"),
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exists.return_value = False
        container.exec_command.return_value = 0

        agent("claude")

    # then the container is created, and the agent is run in it afterwards
    create_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(1000, 1000, project_dir, ["claude"])


def test_agent_propagates_a_non_zero_exit_code(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when the launched agent exits non-zero
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 3

        agent("claude")

    # then ask exits with that same code, rather than raising
    assert exc_info.value.code == 3


def test_agent_raises_when_no_agents_are_configured_and_none_given(
    tmp_path: Path,
) -> None:
    # given a project directory with no agents configured anywhere
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent without naming one
    # then a clear error is raised, rather than starting the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        pytest.raises(AgentError) as error,
    ):
        agent()

    assert str(error.value) == "no agents configured in ask.toml or its layers"


def test_agent_raises_for_an_unknown_agent_name(tmp_path: Path) -> None:
    # given a project directory, and a name with no known agent
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when launching it by name
    # then a clear error is raised
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        pytest.raises(AgentError) as error,
    ):
        agent("copilot")

    assert str(error.value) == (
        "unknown agent 'copilot' (known: claude, codex, opencode, pi)"
    )


def test_agent_forwards_extra_arguments_to_the_agent(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent by name with extra arguments
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent("claude", "--resume")

    # then the agent is executed with those arguments appended
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude", "--resume"]
    )


def test_agent_forwards_wayland_display_when_gui_is_requested(
    tmp_path: Path,
) -> None:
    # given a project directory, a config declaring a user, and a live
    # wayland session
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.gui.wayland_mount", return_value=_WAYLAND_MOUNT),
        patch("ask.gui.acquire") as acquire_mock,
        patch("ask.gui.release") as release_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent("claude", gui=True)

    # then the gui session is acquired before, and released after, running
    # the agent with the wayland display environment variable set
    acquire_mock.assert_called_once_with(container, _WAYLAND_MOUNT)
    release_mock.assert_called_once_with(container, _WAYLAND_MOUNT)
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude"], env=_WAYLAND_ENV
    )


def test_agent_treats_a_dash_prefixed_name_as_an_argument_to_the_default_agent(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares the claude agent,
    # and a resolved user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nlayers = ["base"]\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[layers.base]\nagents = ["claude"]\n[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when launching an agent with arguments but without naming one
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent("--resume", "--verbose")

    # then the default agent is executed with all arguments, in order
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude", "--resume", "--verbose"]
    )


@pytest.mark.parametrize(
    "command", [lambda: enter(), lambda: exec("true")], ids=["enter", "exec"]
)
def test_commands_reject_an_invalid_manifest_before_touching_the_container(
    tmp_path: Path, command: Callable[[], None]
) -> None:
    # given a project directory with an ask.toml containing an unknown key
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('distribution = "arch"\nflayers = []\n')
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when running the command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ConfigError) as error,
    ):
        command()

    # then the problem is reported and the container is never targeted
    assert error.value.problems == ["flayers: unknown key"]
    container_cls.assert_not_called()


def test_agent_prints_manifest_warnings_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a project directory with an ask.toml that produces a warning
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'distribution = "arch"\n'
        'agents = ["claude", { name = "-codex", auth = false }]\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_path", return_value=config_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container_cls.return_value.exec_command.return_value = 0
        agent()

    # then the warning is printed exactly once
    assert capsys.readouterr().err == (
        f"ask: warning in {project_dir / 'ask.toml'}\n"
        "  agents.1: options have no effect when removing agent 'codex'\n"
    )
