import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from ask.agent import AgentError, Claude
from ask.cli import (
    FAKE_SSH_ENV,
    _refresh_invocations,
    agent,
    converge,
    create,
    destroy,
    dump,
    enter,
    exec,
    init,
    rename,
    resolve_shortcut,
    restart,
    run,
    stop,
)
from ask.config import ConfigError, Flavor, FlavorError, User
from ask.convergence import effective_configuration, fingerprint
from ask.errors import AskError
from ask.incus import (
    ContainerExistsError,
    ContainerNotFoundError,
    ConvergedState,
    Fingerprint,
    InstanceSnapshot,
    Mount,
)
from ask.manifest import Manifest, ResolvedManifest
from ask.manifest import load as load_manifest
from ask.user import ResolvedUser
from ask.validation import ManifestNotFoundError

_WAYLAND_MOUNT = Mount(
    host_path=Path("/run/user/1000/wayland-0"),
    container_path=Path("/home/raniz/.wayland-socket"),
)
_WAYLAND_ENV = {"WAYLAND_DISPLAY": "/home/raniz/.wayland-socket"}
_HOME_ENV = {"HOME": "/home/raniz"}
_FLAVOR = 'distribution = "arch"\ndefault = true\n'
_DEBIAN_FLAVOR = 'distribution = "debian"\ndefault = true\n'
_PROJECT_FLAVOR = Flavor(
    distribution="arch", default=True, user=User(name="raniz", uid=1000)
)


def _flavor_path(tmp_path: Path) -> Path:
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir(exist_ok=True)
    return flavors_dir / "arch.toml"


def _run_in_project(
    tmp_path: Path,
    command: Callable[[], None],
    manifest: str = "",
    layer: str = "agents = { claude = true }\n",
) -> tuple[Path, Mock]:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(manifest)
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + "[layers.base]\n" + layer + '[user]\nname = "raniz"\nuid = 1000\n'
    )
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.converge"),
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0
        command()
    return project_dir, container


@pytest.mark.parametrize(
    ("command", "expected_command"),
    [
        (lambda: exec("erl"), ["erl"]),
        (lambda: agent(), ["claude"]),
    ],
    ids=["exec", "agent"],
)
def test_commands_run_with_the_users_home_directory(
    tmp_path: Path, command: Callable[[], None], expected_command: list[str]
) -> None:
    # given a project directory and a config declaring a user
    # when running a command in the project's container
    project_dir, container = _run_in_project(tmp_path, command)

    # then it runs with HOME set to the user's home directory, since incus
    # does not set it for the user it runs commands as
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, expected_command, env=_HOME_ENV
    )


def test_enter_runs_the_shell_with_the_users_home_directory(tmp_path: Path) -> None:
    # given a project directory and a config declaring a user
    # when entering the project's container
    project_dir, container = _run_in_project(tmp_path, lambda: enter())

    # then the shell runs with HOME set to the user's home directory, alongside
    # the variables that make it look like an SSH session
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def test_enter_with_root_runs_the_shell_as_root(tmp_path: Path) -> None:
    # given a project directory and a config declaring a user
    # when entering the project's container with --root
    project_dir, container = _run_in_project(tmp_path, lambda: enter(root=True))

    # then the shell runs as root with root's home directory, alongside the
    # variables that make it look like an SSH session
    container.exec_command.assert_called_once_with(
        0, 0, project_dir, ["bash"], env={"HOME": "/root"} | FAKE_SSH_ENV
    )


def test_enter_with_root_sets_home_to_root_even_when_a_layer_configures_it(
    tmp_path: Path,
) -> None:
    # given a layer setting HOME for the instance
    # when entering the project's container with --root
    project_dir, container = _run_in_project(
        tmp_path, lambda: enter(root=True), layer='env = { HOME = "/elsewhere" }\n'
    )

    # then the shell runs with HOME set to root's home directory
    container.exec_command.assert_called_once_with(
        0, 0, project_dir, ["bash"], env={"HOME": "/root"} | FAKE_SSH_ENV
    )


_ENV_LAYER = (
    'env = { EDITOR = "nvim", LANG = "C" }\n'
    "agents = { "
    'env = { EDITOR = "vi", AGENT = "any" }, '
    'claude = { env = { AGENT = "claude" } } }\n'
)
_ENV_MANIFEST = 'env = { LANG = "C.UTF-8" }\n[scripts]\ntest = "pytest"\n'


@pytest.mark.parametrize(
    ("command", "expected_command"),
    [(lambda: exec("erl"), ["erl"]), (lambda: run("test"), ["pytest"])],
    ids=["exec", "run"],
)
def test_commands_run_with_the_instance_environment_variables(
    tmp_path: Path, command: Callable[[], None], expected_command: list[str]
) -> None:
    # given a layer and a manifest setting variables for the instance and the
    # agents
    # when running a command in the project's container
    project_dir, container = _run_in_project(
        tmp_path, command, _ENV_MANIFEST, _ENV_LAYER
    )

    # then it runs with the instance variables only
    container.exec_command.assert_called_once_with(
        1000,
        1000,
        project_dir,
        expected_command,
        env={"EDITOR": "nvim", "LANG": "C.UTF-8"} | _HOME_ENV,
    )


def test_enter_runs_the_shell_with_the_instance_environment_variables(
    tmp_path: Path,
) -> None:
    # given a layer and a manifest setting variables for the instance and the
    # agents
    # when entering the project's container
    project_dir, container = _run_in_project(
        tmp_path, lambda: enter(), _ENV_MANIFEST, _ENV_LAYER
    )

    # then the shell runs with the instance variables only
    container.exec_command.assert_called_once_with(
        1000,
        1000,
        project_dir,
        ["bash"],
        env={"EDITOR": "nvim", "LANG": "C.UTF-8"} | _HOME_ENV | FAKE_SSH_ENV,
    )


def test_agent_runs_with_the_agent_environment_variables(tmp_path: Path) -> None:
    # given a layer and a manifest setting variables for the instance, every
    # agent and the agent
    # when launching the agent
    project_dir, container = _run_in_project(
        tmp_path, lambda: agent(), _ENV_MANIFEST, _ENV_LAYER
    )

    # then it runs with the instance variables, overridden by those of every
    # agent, overridden by its own
    container.exec_command.assert_called_once_with(
        1000,
        1000,
        project_dir,
        ["claude"],
        env={"EDITOR": "vi", "LANG": "C.UTF-8", "AGENT": "claude"} | _HOME_ENV,
    )


def test_variables_ask_sets_win_over_configured_ones(tmp_path: Path) -> None:
    # given a layer setting HOME for the instance
    # when entering the project's container
    project_dir, container = _run_in_project(
        tmp_path, lambda: enter(), layer='env = { HOME = "/elsewhere" }\n'
    )

    # then the shell runs with the HOME Ask sets
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def _run_in_child_dir(
    tmp_path: Path, command: Callable[[], None]
) -> tuple[Path, Path, Mock, Mock]:
    project_dir = tmp_path / "my-project"
    child_dir = project_dir / "src" / "deep"
    child_dir.mkdir(parents=True)
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + "[layers.base]\nagents = { claude = true }\n"
        '[user]\nname = "raniz"\nuid = 1000\n'
    )
    with (
        patch("ask.cli.Path.cwd", return_value=child_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.converge"),
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0
        command()
    return project_dir, child_dir, container, container_cls


def test_exec_from_a_child_directory_runs_with_the_child_directory_as_cwd(
    tmp_path: Path,
) -> None:
    # given a project whose ask.toml is in a parent of the current directory
    # when running a command in the project's container from the child
    project_dir, child_dir, container, container_cls = _run_in_child_dir(
        tmp_path, lambda: exec("erl")
    )

    # then the container is named after the project directory, and the command
    # runs with the child directory as its working directory
    assert project_dir != child_dir
    container_cls.assert_called_with("my-project")
    container.exec_command.assert_called_once_with(
        1000, 1000, child_dir, ["erl"], env=_HOME_ENV
    )


def test_enter_from_a_child_directory_enters_with_the_child_directory_as_cwd(
    tmp_path: Path,
) -> None:
    # given a project whose ask.toml is in a parent of the current directory
    # when entering the project's container from the child
    _, child_dir, container, _ = _run_in_child_dir(tmp_path, lambda: enter())

    # then the shell runs with the child directory as its working directory
    container.exec_command.assert_called_once_with(
        1000, 1000, child_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def test_destroy_from_a_child_directory_targets_the_project_container(
    tmp_path: Path,
) -> None:
    # given a project directory with a stopped container, and a child directory
    project_dir = tmp_path / "my-project"
    child_dir = project_dir / "src"
    child_dir.mkdir(parents=True)
    (project_dir / "ask.toml").write_text("")

    # when destroying from the child directory
    with (
        patch("ask.cli.Path.cwd", return_value=child_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})

        destroy()

    # then the container named after the project directory is deleted
    container_cls.assert_called_once_with("my-project")
    assert container.method_calls == [call.snapshot(), call.delete()]


def test_commands_from_a_directory_without_any_ask_toml_report_the_missing_manifest(
    tmp_path: Path,
) -> None:
    # given a directory tree without any ask.toml up to the root
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when running a command from there
    with (
        patch("ask.cli.Path.cwd", return_value=orphan),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        pytest.raises(ManifestNotFoundError) as error,
    ):
        exec("erl")

    # then the error points at the directory ask was called from
    assert str(error.value) == (
        f"No ask.toml found in {orphan}. "
        "Run `ask init` to create one, or run ask from a project directory "
        "containing ask.toml."
    )


def test_create_launches_container_and_converges(tmp_path: Path) -> None:
    # given a project directory with an ask.toml declaring a distribution
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when running create from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container.create") as container_create,
        patch("ask.cli.incus.Container.snapshot", return_value=None),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # and a container for the project that already exists
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch(
            "ask.cli.incus.Container.snapshot",
            return_value=InstanceSnapshot(status="Running", config={}),
        ),
        patch("ask.cli.incus.Container.create") as container_create,
        patch("ask.cli.converge") as converge_mock,
        pytest.raises(ContainerExistsError) as error,
    ):
        # when running create from within that project directory
        create()

    # then the error says how to update the container instead, and nothing is
    # launched or converged
    assert str(error.value) == (
        "Container 'my-project' already exists. Run `ask converge` to update it."
    )
    container_create.assert_not_called()
    converge_mock.assert_not_called()


def test_create_rejects_an_unknown_distribution_before_launching(
    tmp_path: Path,
) -> None:
    # given a project directory, and a default flavour using an unsupported
    # distribution
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text('distribution = "gentoo"\ndefault = true\n')

    # when running create from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container.create") as container_create,
        pytest.raises(ConfigError) as error,
    ):
        create()

    # then the distribution is reported and no container is launched
    assert error.value.problems == [
        "distribution: unknown distribution 'gentoo' (known: arch, debian)"
    ]
    container_create.assert_not_called()


def test_converge_rejects_projects_no_flavor_applies_to_before_touching_the_container(
    tmp_path: Path,
) -> None:
    # given a project directory, and a flavours directory without any flavours
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(FlavorError) as error,
    ):
        converge()

    # then the missing flavour is reported and the container is never targeted
    assert str(error.value) == (
        f"No flavour applies to {project_dir}. Add a flavour whose when.path "
        "matches it, or mark one with default = true."
    )
    container_cls.assert_not_called()


def test_converge_starts_a_stopped_targeted_container(
    tmp_path: Path,
) -> None:
    # given a project directory with a stopped container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})
        container.get_managed_packages.return_value = []

        converge()

    # then the container named after the project directory is targeted, and
    # started, since it was stopped
    container_cls.assert_called_once_with("my-project")
    container.start.assert_called_once_with()
    provisioner_cls.assert_called_once_with(container)


def test_converge_creates_a_missing_container_without_asking_when_requested(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when converging from a terminal with missing containers to be created
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input") as input_mock,
        patch("ask.cli.create") as create_mock,
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
        container.get_managed_packages.return_value = []

        converge(create_missing=True)

    # then the container is created without asking the user
    create_mock.assert_called_once_with()
    input_mock.assert_not_called()


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
    (project_dir / "ask.toml").write_text(f'bind_mounts = ["{configured_mount}"]\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + f'[layers.python]\nbind_mounts = ["{layer_mount}"]\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + 'shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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


def test_converge_prepares_the_user_and_mounts_before_installing_packages(
    tmp_path: Path,
) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    call_order: list[str] = []

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []
        container.converge.side_effect = lambda *a, **k: call_order.append("converge")
        provisioner = provisioner_cls.return_value
        for step in (
            "provision_user",
            "fix_bind_mount_ownership",
            "provision_packages",
        ):
            getattr(provisioner, step).side_effect = lambda *a, step=step, **k: (
                call_order.append(step)
            )

        converge()

    # then the user, and therefore their home directory, is provisioned
    # before any home-relative path (shell rc, agent state) is mounted into
    # the container, since the mount's container-side ancestor directories
    # must already exist
    # and the mounts' ancestors are handed to the user before anything else
    # runs, so packages installed afterwards can write beneath them
    assert call_order == [
        "provision_user",
        "converge",
        "fix_bind_mount_ownership",
        "provision_packages",
    ]


def test_converge_provisions_the_instance_environment_variables(
    tmp_path: Path,
) -> None:
    # given a project directory with ask.toml and a layer setting variables
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('env = { LANG = "C.UTF-8" }\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + '[layers.base]\nenv = { EDITOR = "nvim", LANG = "C" }\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container_cls.return_value.get_managed_packages.return_value = []

        converge()

    # then the merged instance variables are provisioned
    provisioner_cls.return_value.provision_instance_env.assert_called_once_with(
        {"EDITOR": "nvim", "LANG": "C.UTF-8"}
    )


def test_converge_provisions_the_resolved_packages(tmp_path: Path) -> None:
    # given a project directory with ask.toml declaring packages and a layer,
    # and a config declaring that layer's packages
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('packages = ["project-pkg"]\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[layers.python]\npackages = ["layer-pkg"]\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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


def test_converge_provisions_the_resolved_pi_extensions(tmp_path: Path) -> None:
    # given a project directory, and a config declaring extensions for pi
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + '[layers.base.agents.pi]\nextensions = ["@foo/bar", "@baz/qux"]\n'
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the pi extensions are provisioned for the resolved user
    provisioner_cls.return_value.provision_pi_extensions.assert_called_once_with(
        ResolvedUser(
            name="raniz",
            uid=1000,
            shell="bash",
            group_name="raniz",
            gid=1000,
            extra_groups=[],
        ),
        ["@foo/bar", "@baz/qux"],
    )


def test_converge_does_not_provision_pi_extensions_without_any(tmp_path: Path) -> None:
    # given a project directory, and a config enabling pi without extensions
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + "[layers.base.agents]\npi = true\n"
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then no pi extensions are provisioned
    provisioner_cls.return_value.provision_pi_extensions.assert_not_called()


def test_converge_installs_pi_standalone_on_debian_before_its_extensions(
    tmp_path: Path,
) -> None:
    # given a debian flavour enabling the pi agent with extensions
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _DEBIAN_FLAVOR
        + '[layers.base.agents.pi]\nextensions = ["npm:pi-subagents"]\n'
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then pi itself is installed on debian, before its extensions
    provisioner = provisioner_cls.return_value
    provisioner.provision_pi.assert_called_once_with()
    provisioner.provision_pi_extensions.assert_called_once()
    names = [c[0] for c in provisioner.method_calls]
    assert names.index("provision_pi") < names.index("provision_pi_extensions")


def test_converge_installs_npm_agents_on_debian(tmp_path: Path) -> None:
    # given a debian flavour enabling the codex agent, which is npm-based
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _DEBIAN_FLAVOR
        + "[layers.base.agents]\ncodex = true\n"
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then nodejs and npm are installed via apt, and codex via npm
    provisioner = provisioner_cls.return_value
    provisioner.provision_packages.assert_called_once_with(
        "debian", ["bash", "nodejs", "npm"]
    )
    provisioner.provision_npm_packages.assert_called_once_with(["@openai/codex"])


def test_converge_installs_claude_from_anthropics_apt_repo_on_debian(
    tmp_path: Path,
) -> None:
    # given a debian flavour enabling the claude agent, which Anthropic
    # publishes through its own signed apt repository
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _DEBIAN_FLAVOR
        + "[layers.base.agents]\nclaude = true\n"
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then Anthropic's apt repository is provisioned before the distro
    # packages are installed, claude-code is installed via apt, and no
    # npm install runs
    provisioner = provisioner_cls.return_value
    provisioner.provision_apt_repository.assert_called_once_with(
        Claude().apt_repositories[0]
    )
    provisioner.provision_packages.assert_called_once_with(
        "debian", ["bash", "claude-code"]
    )
    provisioner.provision_npm_packages.assert_not_called()
    names = [c[0] for c in provisioner.method_calls]
    assert names.index("provision_apt_repository") < names.index("provision_packages")


def test_converge_does_not_provision_apt_repositories_on_arch(tmp_path: Path) -> None:
    # given an arch flavour enabling the claude agent, which comes from the
    # AUR there
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + "[layers.base.agents]\nclaude = true\n"
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container_cls.return_value.get_managed_packages.return_value = []

        converge()

    # then no apt repository is provisioned; the AUR package covers claude
    provisioner_cls.return_value.provision_apt_repository.assert_not_called()


def test_converge_does_not_install_npm_packages_on_arch(tmp_path: Path) -> None:
    # given an arch flavour enabling the codex agent, which comes from a
    # distro package there
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + "[layers.base.agents]\ncodex = true\n"
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then no npm install runs; the arch package covers codex
    provisioner_cls.return_value.provision_npm_packages.assert_not_called()


def test_converge_does_not_install_pi_standalone_on_arch(tmp_path: Path) -> None:
    # given an arch flavour enabling the pi agent, where pi comes from the AUR
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + "[layers.base.agents]\npi = true\n"
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the standalone pi install is not used; the AUR package covers it
    provisioner_cls.return_value.provision_pi.assert_not_called()


def test_converge_provisions_services_from_layers(tmp_path: Path) -> None:
    # given a project with services configured
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + '[layers.base]\nservices."sshd.service" = "enabled"\nservices."man-db.timer" = "disabled"\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the resolved services are provisioned
    provisioner_cls.return_value.provision_services.assert_called_once_with(
        {
            "sshd.service": "enabled",
            "man-db.timer": "disabled",
        }
    )


def test_converge_provisions_services_from_manifest(tmp_path: Path) -> None:
    # given a project with services configured in the manifest
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'services."project.service" = "enabled"\nservices."another.service" = "masked"\n'
    )
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the resolved services are provisioned
    provisioner_cls.return_value.provision_services.assert_called_once_with(
        {
            "project.service": "enabled",
            "another.service": "masked",
        }
    )


def test_converge_manifest_services_override_layer_services(tmp_path: Path) -> None:
    # given a project with services configured in both layers and manifest
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'services."conflict.service" = "enabled"\nservices."manifest.service" = "disabled"\n'
    )
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + '[layers.base]\nservices."sshd.service" = "enabled"\nservices."conflict.service" = "disabled"\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the resolved services are provisioned, with manifest taking precedence
    provisioner_cls.return_value.provision_services.assert_called_once_with(
        {
            "sshd.service": "enabled",
            "conflict.service": "enabled",  # Overridden by manifest
            "manifest.service": "disabled",
        }
    )


def test_converge_includes_the_configured_shells_own_package(tmp_path: Path) -> None:
    # given a project directory with no packages of its own, and a config
    # declaring zsh as the shell
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + 'shell = "zsh"\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text('packages = ["aur:yay-bin", "git"]\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + 'shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n'
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + '[shell]\nname = "zsh"\nzshrc = false\nzprofile = true\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.Path.home", return_value=home_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + "[layers.base]\nagents = { claude = true }\n")

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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


def test_converge_mounts_the_state_of_configured_agents(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares the claude agent,
    # a resolved user, and a host home directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + '[layers.base]\nagents = { claude = true }\n[user]\nname = "raniz"\nuid = 1000\n'
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
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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


def test_converge_removes_packages_no_longer_declared(tmp_path: Path) -> None:
    # given a project directory declaring one package, and a container that
    # was previously managing that package plus one no longer declared
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('packages = ["project-pkg"]\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text('packages = ["project-pkg"]\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text('bind_mounts = ["/home/raniz/.cache/uv"]\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + 'shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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


def test_converge_fixes_agent_state_mount_ownership(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares the claude agent
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + '[layers.base]\nagents = { claude = true }\n[user]\nname = "raniz"\nuid = 1000\n'
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
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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


def test_run_executes_script_command(tmp_path: Path) -> None:
    # given a project directory with a script defined in ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('scripts.test = "pytest"\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when running the script
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        run("test")

    # then the script command is executed in the container
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["pytest"], env=_HOME_ENV
    )


def test_run_executes_script_command_with_args(tmp_path: Path) -> None:
    # given a project directory with a script defined in ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('scripts.test = "pytest"\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when running the script with additional arguments
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        run("test", "-v", "--cov")

    # then the script command and arguments are executed in the container
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["pytest", "-v", "--cov"], env=_HOME_ENV
    )


def test_run_splits_the_script_command_with_shell_quoting_rules(
    tmp_path: Path,
) -> None:
    # given a project directory with a script command containing quoted arguments
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'scripts.greet = "echo \\"hello world\\" \'hi there\'"\n'
    )
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when running the script
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        run("greet")

    # then the quotes are honoured and not passed through as part of the arguments
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["echo", "hello world", "hi there"], env=_HOME_ENV
    )


def test_run_rejects_undefined_script(tmp_path: Path) -> None:
    # given a project directory without the requested script in ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('scripts.lint = "ruff check"\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when running the undefined script
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(AskError) as error,
    ):
        run("test")

    # then the error reports the undefined script
    assert str(error.value) == "Script 'test' is not defined in ask.toml."
    container_cls.assert_not_called()


def _resolve_in_project(project_dir: Path, config_path: Path, name: str) -> str | None:
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
    ):
        return resolve_shortcut(name)


def test_resolve_shortcut_maps_a_known_agent_name_to_agent(tmp_path: Path) -> None:
    # given a project without any scripts
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when resolving an unknown command that names a known agent
    target = _resolve_in_project(project_dir, config_path, "claude")

    # then it dispatches to the agent command
    assert target == "agent"


def test_resolve_shortcut_maps_a_script_name_to_run(tmp_path: Path) -> None:
    # given a project with a script defined in ask.toml
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('scripts.build = "make"\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when resolving an unknown command that names the script
    target = _resolve_in_project(project_dir, config_path, "build")

    # then it dispatches to the run command
    assert target == "run"


def test_resolve_shortcut_rejects_a_name_matching_both_an_agent_and_a_script(
    tmp_path: Path,
) -> None:
    # given a project whose script has the same name as a known agent
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('scripts.claude = "make claude"\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when resolving the ambiguous name
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        pytest.raises(AskError) as error,
    ):
        resolve_shortcut("claude")

    # then the error tells the user to pick ask agent or ask run explicitly
    assert "ask agent" in str(error.value)
    assert "ask run" in str(error.value)


def test_resolve_shortcut_returns_none_for_a_name_matching_neither_an_agent_nor_a_script(
    tmp_path: Path,
) -> None:
    # given a project with an unrelated script
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text('scripts.build = "make"\n')
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when resolving a name that matches nothing
    target = _resolve_in_project(project_dir, config_path, "nope")

    # then there is no shortcut, letting cyclopts report the unknown command
    assert target is None


def test_converge_records_the_converged_state_last(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # and an installed ask version and a clock
    converged_at = datetime(2026, 11, 9, 12, 30, tzinfo=UTC)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
        patch("ask.convergence.version", return_value="1.2.3"),
        patch("ask.cli.datetime") as datetime_mock,
    ):
        datetime_mock.now.return_value = converged_at
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the effective configuration, its fingerprint and the time are
    # recorded as the last thing done to the container
    configuration = effective_configuration(
        ResolvedManifest(Manifest(), _PROJECT_FLAVOR, project_dir)
    )
    # the clock is read once to record the invocation and once for the
    # converged state
    assert datetime_mock.now.call_args_list == [call(UTC), call(UTC)]
    assert container.method_calls[-1] == call.set_converged_state(
        ConvergedState(
            fingerprint=Fingerprint(
                version="1.2.3",
                config_hash=hashlib.sha256(configuration.encode()).hexdigest(),
            ),
            configuration=configuration,
            at=converged_at,
        )
    )


def test_converge_does_not_record_the_state_when_provisioning_fails(
    tmp_path: Path,
) -> None:
    # given a project directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # and provisioning that fails
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
        pytest.raises(RuntimeError),
    ):
        provisioner_cls.return_value.provision_packages.side_effect = RuntimeError
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        # when converging from within that project directory
        converge()

    # then no converged state is recorded
    container.set_converged_state.assert_not_called()


_RANIZ = ResolvedUser(
    name="raniz",
    uid=1000,
    shell="bash",
    group_name="raniz",
    gid=1000,
    extra_groups=[],
)


def _converge_with_mise(
    tmp_path: Path, ask_toml: str, flavor: str = _FLAVOR
) -> tuple[Path, MagicMock]:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir(exist_ok=True)
    (project_dir / "ask.toml").write_text(ask_toml)
    config_path = _flavor_path(tmp_path)
    config_path.write_text(flavor + '[user]\nname = "raniz"\nuid = 1000\n')

    steps = MagicMock()
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
        patch("ask.cli.provision.MiseProvisioner") as mise_provisioner_cls,
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []
        steps.attach_mock(container, "container")
        steps.attach_mock(provisioner_cls.return_value, "provisioner")
        steps.attach_mock(mise_provisioner_cls.return_value, "mise")

        converge()

    return project_dir, steps


def _step_names(steps: MagicMock) -> list[str]:
    return [name for name, _, _ in steps.mock_calls]


def test_converge_hands_tool_installation_to_mise_for_a_project_with_mise_config(
    tmp_path: Path,
) -> None:
    # given a project directory with a mise.toml
    (tmp_path / "my-project").mkdir()
    (tmp_path / "my-project" / "mise.toml").write_text('[tools]\nerlang = "29"\n')

    # when converging with an ask.toml that opts into mise
    project_dir, steps = _converge_with_mise(tmp_path, 'tool_managers = ["mise"]\n')

    # then mise is installed alongside the shell's package
    steps.provisioner.provision_packages.assert_called_once_with(
        "arch", ["bash", "mise"]
    )

    # and once packages and mount ownership are in place, the mise config is
    # trusted and its tools installed as the user
    names = _step_names(steps)
    assert names.index("provisioner.fix_bind_mount_ownership") < names.index(
        "mise.trust"
    )
    assert [c for c in steps.mock_calls if c[0].startswith("mise.")] == [
        call.mise.trust(project_dir, _RANIZ, [Path("mise.toml")]),
        call.mise.install(project_dir, _RANIZ),
    ]

    # and mise's shims are put on the PATH of commands run in the container
    steps.container.set_path_prefix.assert_called_once_with(
        [Path("/home/raniz/.local/share/mise/shims")]
    )

    # and the standalone mise install is not used; the arch package covers it
    steps.provisioner.provision_mise.assert_not_called()


def test_converge_installs_mise_standalone_on_debian_before_trusting_it(
    tmp_path: Path,
) -> None:
    # given a debian project directory with a mise.toml, opting into mise
    (tmp_path / "my-project").mkdir()
    (tmp_path / "my-project" / "mise.toml").write_text('[tools]\nerlang = "29"\n')

    # when converging
    _, steps = _converge_with_mise(
        tmp_path, 'tool_managers = ["mise"]\n', flavor=_DEBIAN_FLAVOR
    )

    # then the standalone mise binary is installed before mise is trusted
    steps.provisioner.provision_mise.assert_called_once_with()
    names = _step_names(steps)
    assert names.index("provisioner.provision_mise") < names.index("mise.trust")


def test_converge_leaves_mise_out_of_a_project_without_mise_config(
    tmp_path: Path,
) -> None:
    # given a project directory without mise config
    # when converging with an ask.toml that opts into mise
    _, steps = _converge_with_mise(tmp_path, 'tool_managers = ["mise"]\n')

    # then mise is neither installed nor run
    steps.provisioner.provision_packages.assert_called_once_with("arch", ["bash"])
    steps.provisioner.provision_mise.assert_not_called()
    assert [c for c in steps.mock_calls if c[0].startswith("mise.")] == []

    # and the PATH of commands run in the container is the default one
    steps.container.set_path_prefix.assert_called_once_with([])


def test_converge_leaves_mise_out_of_a_project_that_does_not_opt_into_it(
    tmp_path: Path,
) -> None:
    # given a project directory with a mise.toml
    (tmp_path / "my-project").mkdir()
    (tmp_path / "my-project" / "mise.toml").write_text('[tools]\nerlang = "29"\n')

    # when converging with an ask.toml that does not opt into mise
    _, steps = _converge_with_mise(tmp_path, "")

    # then mise is neither installed nor run
    steps.provisioner.provision_packages.assert_called_once_with("arch", ["bash"])
    assert [c for c in steps.mock_calls if c[0].startswith("mise.")] == []

    # and the PATH of commands run in the container is the default one
    steps.container.set_path_prefix.assert_called_once_with([])


def test_enter_starts_a_stopped_targeted_container(tmp_path: Path) -> None:
    # given a project directory with a stopped container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})
        container.exec_command.return_value = 0

        enter()

    # then the container named after the project directory is targeted, and
    # started, since it was stopped
    container_cls.assert_called_once_with("my-project")
    container.start.assert_called_once_with()


def test_enter_does_not_start_an_already_running_container(tmp_path: Path) -> None:
    # given a project directory with a running container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Running", config={})
        container.exec_command.return_value = 0

        enter()

    # then the container is not started again
    container.start.assert_not_called()


def test_enter_rejects_an_unknown_shell_before_touching_the_container(
    tmp_path: Path,
) -> None:
    # given a project directory, and a config declaring an unsupported shell
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + 'shell = "foosh"\n')

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + 'shell = "zsh"\n[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when entering the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
        1000, 1000, project_dir, ["zsh"], env=_HOME_ENV | FAKE_SSH_ENV
    )
    assert exc_info.value.code == 0


def test_enter_propagates_a_non_zero_exit_code(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when the entered shell exits non-zero
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV | _WAYLAND_ENV
    )
    assert exc_info.value.code == 0


def test_enter_does_not_forward_anything_when_gui_requested_without_a_session(
    tmp_path: Path,
) -> None:
    # given a project directory, a config declaring a user, and no live
    # wayland session on the host
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def test_enter_creates_a_missing_container_when_the_user_accepts(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container from a terminal and accepting the offer to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input", return_value="y"),
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
        container.exec_command.return_value = 0

        enter()

    # then the container is created, and the shell is run in it afterwards
    create_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def test_enter_creates_a_missing_container_when_the_user_accepts_the_default(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container from a terminal and answering the offer with
    # just enter
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input", return_value=""),
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container from a terminal and declining the offer to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input", return_value="n"),
        patch("ask.cli.create") as create_mock,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None

        enter()

    # then nothing is created or run, and the user is told how to create it
    assert str(error.value) == (
        "No container named 'my-project'. Run `ask create` first."
    )
    create_mock.assert_not_called()
    container.exec_command.assert_not_called()


def test_enter_refuses_a_missing_container_when_stdin_is_closed(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container from a terminal without an answer being
    # available on stdin
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input", side_effect=EOFError),
        patch("ask.cli.create") as create_mock,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None

        enter()

    # then nothing is created or run, and the user is told how to create it
    assert str(error.value) == (
        "No container named 'my-project'. Run `ask create` first."
    )
    create_mock.assert_not_called()
    container.exec_command.assert_not_called()


def test_enter_creates_a_missing_container_without_asking_when_requested(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container from a terminal with missing containers to be created
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input") as input_mock,
        patch("ask.cli.create") as create_mock,
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
        container.exec_command.return_value = 0

        enter(create_missing=True)

    # then the container is created without asking the user
    create_mock.assert_called_once_with()
    input_mock.assert_not_called()


def test_enter_does_not_offer_to_create_a_missing_container_without_a_terminal(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container with stdin not connected to a terminal
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input") as input_mock,
        patch("ask.cli.create") as create_mock,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        stdin_mock.isatty.return_value = False
        container = container_cls.return_value
        container.snapshot.return_value = None

        enter()

    # then the user is not asked anything, nothing is created, and the user is
    # told how to create it
    assert str(error.value) == (
        "No container named 'my-project'. Run `ask create` first."
    )
    input_mock.assert_not_called()
    create_mock.assert_not_called()


def test_enter_does_not_offer_to_create_an_existing_container(
    tmp_path: Path,
) -> None:
    # given a project directory with an existing, converged container
    project_dir, config_path = _project(tmp_path)

    # when entering the container from a terminal
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input") as input_mock,
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = _converged_snapshot(project_dir)
        container.exec_command.return_value = 0

        enter()

    # then the user is not asked anything, and nothing is created
    input_mock.assert_not_called()
    create_mock.assert_not_called()


_CHANGED_PROMPT = (
    "Configuration has changed since the container was last converged. "
    "Converge now? [Y/n] "
)
_CHANGED_WARNING = (
    "ask: warning: configuration has changed since the container was last "
    "converged; run `ask converge` to apply it\n"
)


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')
    return project_dir, config_path


def _converged_snapshot(
    project_dir: Path, m: Manifest | None = None
) -> InstanceSnapshot:
    converged = fingerprint(
        effective_configuration(
            ResolvedManifest(m or Manifest(), _PROJECT_FLAVOR, project_dir)
        )
    )
    return InstanceSnapshot(
        status="Running",
        config={
            "user.ask.converged.version": converged.version,
            "user.ask.converged.hash": converged.config_hash,
        },
    )


_STALE_SNAPSHOT = InstanceSnapshot(
    status="Running",
    config={
        "user.ask.converged.version": "0.0.1",
        "user.ask.converged.hash": "stale",
    },
)


def _enter_with(
    project_dir: Path,
    config_path: Path,
    snapshot: InstanceSnapshot,
    tty: bool,
    answer: str = "",
    **kwargs: bool | None,
) -> tuple[Mock, Mock, Mock]:
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input", return_value=answer) as input_mock,
        patch("ask.cli.converge") as converge_mock,
        pytest.raises(SystemExit),
    ):
        stdin_mock.isatty.return_value = tty
        container = container_cls.return_value
        container.snapshot.return_value = snapshot
        container.exec_command.return_value = 0

        enter(
            gui=kwargs.get("gui", False) or False,
            create_missing=kwargs.get("create_missing", False) or False,
            converge_changed=kwargs.get("converge_changed"),
        )
    return container, input_mock, converge_mock


def test_enter_does_not_converge_an_unchanged_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a project whose container was converged with its current configuration
    project_dir, config_path = _project(tmp_path)
    snapshot = _converged_snapshot(project_dir)

    # when entering the container from a terminal
    container, input_mock, converge_mock = _enter_with(
        project_dir, config_path, snapshot, tty=True
    )

    # then nothing is asked or converged, and the shell is run
    input_mock.assert_not_called()
    converge_mock.assert_not_called()
    assert capsys.readouterr().err == ""
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def test_enter_asks_to_converge_after_the_mise_config_changed(
    tmp_path: Path,
) -> None:
    # given a project opting into mise with a mise.toml, whose container was
    # converged with it
    project_dir, config_path = _project(tmp_path)
    (project_dir / "ask.toml").write_text('tool_managers = ["mise"]\n')
    (project_dir / "mise.toml").write_text('[tools]\nerlang = "29.1.1"\n')
    snapshot = _converged_snapshot(project_dir, Manifest(tool_managers=["mise"]))

    # and a mise.toml that has changed since
    (project_dir / "mise.toml").write_text('[tools]\nerlang = "29.2.0"\n')

    # when entering the container from a terminal
    _, input_mock, _ = _enter_with(project_dir, config_path, snapshot, tty=True)

    # then the user is asked to converge
    input_mock.assert_called_once_with(_CHANGED_PROMPT)


def test_enter_converges_a_changed_configuration_when_the_user_accepts(
    tmp_path: Path,
) -> None:
    # given a project whose container was converged with another configuration
    project_dir, config_path = _project(tmp_path)

    # when entering the container from a terminal and accepting to converge
    container, input_mock, converge_mock = _enter_with(
        project_dir, config_path, _STALE_SNAPSHOT, tty=True, answer="y"
    )

    # then the user is asked, the container is converged, and the shell is run
    input_mock.assert_called_once_with(_CHANGED_PROMPT)
    converge_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def test_enter_asks_to_converge_a_container_that_was_never_converged(
    tmp_path: Path,
) -> None:
    # given a project whose container has no recorded convergence
    project_dir, config_path = _project(tmp_path)
    snapshot = InstanceSnapshot(status="Running", config={})

    # when entering the container from a terminal and accepting the default
    _, input_mock, converge_mock = _enter_with(
        project_dir, config_path, snapshot, tty=True
    )

    # then the user is asked and the container is converged
    input_mock.assert_called_once_with(_CHANGED_PROMPT)
    converge_mock.assert_called_once_with()


def test_enter_does_not_converge_a_changed_configuration_when_the_user_declines(
    tmp_path: Path,
) -> None:
    # given a project whose container was converged with another configuration
    project_dir, config_path = _project(tmp_path)

    # when entering the container from a terminal and declining to converge
    container, _, converge_mock = _enter_with(
        project_dir, config_path, _STALE_SNAPSHOT, tty=True, answer="n"
    )

    # then nothing is converged, and the shell is still run
    converge_mock.assert_not_called()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def test_enter_warns_about_a_changed_configuration_without_a_terminal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a project whose container was converged with another configuration
    project_dir, config_path = _project(tmp_path)

    # when entering the container without a terminal
    container, input_mock, converge_mock = _enter_with(
        project_dir, config_path, _STALE_SNAPSHOT, tty=False
    )

    # then nothing is asked or converged, a warning is printed, and the shell
    # is still run
    input_mock.assert_not_called()
    converge_mock.assert_not_called()
    assert capsys.readouterr().err == _CHANGED_WARNING
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["bash"], env=_HOME_ENV | FAKE_SSH_ENV
    )


def test_enter_converges_a_changed_configuration_without_asking_when_requested(
    tmp_path: Path,
) -> None:
    # given a project whose container was converged with another configuration
    project_dir, config_path = _project(tmp_path)

    # when entering the container with changes to be converged
    _, input_mock, converge_mock = _enter_with(
        project_dir, config_path, _STALE_SNAPSHOT, tty=True, converge_changed=True
    )

    # then the container is converged without asking
    input_mock.assert_not_called()
    converge_mock.assert_called_once_with()


def test_enter_skips_converging_a_changed_configuration_when_requested(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a project whose container was converged with another configuration
    project_dir, config_path = _project(tmp_path)

    # when entering the container with changes not to be converged
    _, input_mock, converge_mock = _enter_with(
        project_dir, config_path, _STALE_SNAPSHOT, tty=True, converge_changed=False
    )

    # then nothing is asked, converged or warned about
    input_mock.assert_not_called()
    converge_mock.assert_not_called()
    assert capsys.readouterr().err == ""


def test_enter_does_not_ask_to_converge_a_container_it_just_created(
    tmp_path: Path,
) -> None:
    # given a project without a container
    project_dir, config_path = _project(tmp_path)

    # when entering the container, accepting to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input", return_value="y") as input_mock,
        patch("ask.cli.create"),
        patch("ask.cli.converge") as converge_mock,
        pytest.raises(SystemExit),
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
        container.exec_command.return_value = 0

        enter()

    # then the user is only asked about creating it, and it is not converged
    # again
    input_mock.assert_called_once_with(
        "No container named 'my-project' exists. Create it now? [Y/n] "
    )
    converge_mock.assert_not_called()


def test_exec_converges_a_changed_configuration_when_requested(
    tmp_path: Path,
) -> None:
    # given a project whose container was converged with another configuration
    project_dir, config_path = _project(tmp_path)

    # when executing a command with changes to be converged
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.converge") as converge_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.snapshot.return_value = _STALE_SNAPSHOT
        container.exec_command.return_value = 0

        exec("ls", converge_changed=True)

    # then the container is converged before the command is executed
    converge_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["ls"], env=_HOME_ENV
    )


def test_agent_converges_a_changed_configuration_when_requested(
    tmp_path: Path,
) -> None:
    # given a project whose container was converged with another configuration
    project_dir, config_path = _project(tmp_path)

    # when launching an agent with changes to be converged
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.converge") as converge_mock,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.snapshot.return_value = _STALE_SNAPSHOT
        container.exec_command.return_value = 0

        agent("claude", converge_changed=True)

    # then the container is converged before the agent is executed
    converge_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude"], env=_HOME_ENV
    )


def test_exec_starts_a_stopped_targeted_container(tmp_path: Path) -> None:
    # given a project directory with a stopped container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})
        container.exec_command.return_value = 0

        exec("ls", "-la")

    # then the container named after the project directory is targeted, and
    # started, since it was stopped
    container_cls.assert_called_once_with("my-project")
    container.start.assert_called_once_with()


def test_exec_creates_a_missing_container_when_the_user_accepts(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from a terminal and accepting the offer to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input", return_value="y"),
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
        container.exec_command.return_value = 0

        exec("ls", "-la")

    # then the container is created, and the command is run in it afterwards
    create_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["ls", "-la"], env=_HOME_ENV
    )


def test_exec_creates_a_missing_container_without_asking_when_requested(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from a terminal with missing containers to be created
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input") as input_mock,
        patch("ask.cli.create") as create_mock,
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
        container.exec_command.return_value = 0

        exec("ls", create_missing=True)

    # then the container is created without asking the user
    create_mock.assert_called_once_with()
    input_mock.assert_not_called()


def test_exec_runs_the_command_as_the_resolved_user(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
        1000, 1000, project_dir, ["ls", "-la"], env=_HOME_ENV
    )
    assert exc_info.value.code == 0


def test_exec_propagates_a_non_zero_exit_code(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when the executed command exits non-zero
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
        1000, 1000, project_dir, ["ls", "-la"], env=_HOME_ENV | _WAYLAND_ENV
    )
    assert exc_info.value.code == 0


def test_exec_passes_only_home_when_gui_requested_without_a_session(
    tmp_path: Path,
) -> None:
    # given a project directory, a config declaring a user, and no live
    # wayland session on the host
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when executing a command with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    # only HOME set, exactly as without --gui
    acquire_mock.assert_not_called()
    release_mock.assert_not_called()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["ls", "-la"], env=_HOME_ENV
    )


def test_agent_rejects_projects_no_flavor_applies_to_before_touching_the_container(
    tmp_path: Path,
) -> None:
    # given a project directory, and a flavours directory without any flavours
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)

    # when launching an agent without naming one
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(FlavorError) as error,
    ):
        agent()

    # then the missing flavour is reported and the container is never targeted
    assert str(error.value) == (
        f"No flavour applies to {project_dir}. Add a flavour whose when.path "
        "matches it, or mark one with default = true."
    )
    container_cls.assert_not_called()


def test_agent_launches_the_first_configured_agent_when_none_given(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares two agents, and a
    # resolved user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + "[layers.base]\nagents = { claude = true, codex = true }\n"
        '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when launching an agent without naming one
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent()

    # then the first configured agent is executed in the container as the
    # resolved user, in the project directory, and ask exits with its exit
    # code
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude"], env=_HOME_ENV
    )
    assert exc_info.value.code == 0


def test_agent_launches_the_default_agent_when_none_given(tmp_path: Path) -> None:
    # given a project directory using a layer that enables two agents and names
    # the second one its default, and a resolved user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR + "[layers.base]\n"
        'agents = { default = "codex", claude = true, codex = true }\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when launching an agent without naming one
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent()

    # then the default agent is executed in the container
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["codex"], env=_HOME_ENV
    )


def test_agent_launches_the_named_agent_when_given(tmp_path: Path) -> None:
    # given a project directory with no agents configured, and a resolved user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent by name
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit) as exc_info,
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent("claude")

    # then the named agent is executed, regardless of what is configured
    container_cls.assert_called_once_with("my-project")
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude"], env=_HOME_ENV
    )
    assert exc_info.value.code == 0


def test_agent_starts_a_stopped_targeted_container(tmp_path: Path) -> None:
    # given a project directory with a stopped container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})
        container.exec_command.return_value = 0

        agent("claude")

    # then the container named after the project directory is targeted, and
    # started, since it was stopped
    container_cls.assert_called_once_with("my-project")
    container.start.assert_called_once_with()


def test_agent_creates_a_missing_container_when_the_user_accepts(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent from a terminal and accepting the offer to create it
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input", return_value="y"),
        patch("ask.cli.create") as create_mock,
        pytest.raises(SystemExit),
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
        container.exec_command.return_value = 0

        agent("claude")

    # then the container is created, and the agent is run in it afterwards
    create_mock.assert_called_once_with()
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude"], env=_HOME_ENV
    )


def test_agent_creates_a_missing_container_without_asking_when_requested(
    tmp_path: Path,
) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent from a terminal with missing containers to be created
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("builtins.input") as input_mock,
        patch("ask.cli.create") as create_mock,
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.snapshot.return_value = None
        container.exec_command.return_value = 0

        agent("claude", create_missing=True)

    # then the container is created without asking the user
    create_mock.assert_called_once_with()
    input_mock.assert_not_called()


def test_agent_propagates_a_non_zero_exit_code(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when the launched agent exits non-zero
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent without naming one
    # then a clear error is raised, rather than starting the container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        pytest.raises(AgentError) as error,
    ):
        agent()

    assert str(error.value) == (
        "No agents configured in the flavour layers that apply to this project."
    )


def test_agent_raises_for_an_unknown_agent_name(tmp_path: Path) -> None:
    # given a project directory, and a name with no known agent
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when launching it by name
    # then a clear error is raised
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        pytest.raises(AgentError) as error,
    ):
        agent("copilot")

    assert str(error.value) == (
        "Unknown agent 'copilot' (known: claude, codex, opencode, pi)."
    )


def test_agent_forwards_extra_arguments_to_the_agent(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent by name with extra arguments
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent("claude", "--resume")

    # then the agent is executed with those arguments appended
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude", "--resume"], env=_HOME_ENV
    )


def test_agent_forwards_wayland_display_when_gui_is_requested(
    tmp_path: Path,
) -> None:
    # given a project directory, a config declaring a user, and a live
    # wayland session
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when launching an agent with --gui
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
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
        1000, 1000, project_dir, ["claude"], env=_HOME_ENV | _WAYLAND_ENV
    )


def test_agent_treats_a_dash_prefixed_name_as_an_argument_to_the_default_agent(
    tmp_path: Path,
) -> None:
    # given a project directory using a layer that declares the claude agent,
    # and a resolved user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + '[layers.base]\nagents = { claude = true }\n[user]\nname = "raniz"\nuid = 1000\n'
    )

    # when launching an agent with arguments but without naming one
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(SystemExit),
    ):
        container = container_cls.return_value
        container.exec_command.return_value = 0

        agent("--resume", "--verbose")

    # then the default agent is executed with all arguments, in order
    container.exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["claude", "--resume", "--verbose"], env=_HOME_ENV
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
    (project_dir / "ask.toml").write_text("flayers = []\n")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when running the command from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ConfigError) as error,
    ):
        command()

    # then the problem is reported and the container is never targeted
    assert error.value.problems == ["flayers: unknown key"]
    container_cls.assert_not_called()


def test_restart_restarts_a_running_container(tmp_path: Path) -> None:
    # given a project directory with a running container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    # when restarting from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Running", config={})

        restart()

    # then the container named after the project directory is restarted
    container_cls.assert_called_once_with("my-project")
    assert container.method_calls == [call.snapshot(), call.restart()]


def test_restart_starts_a_stopped_container(tmp_path: Path) -> None:
    # given a project directory with a stopped container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    # when restarting from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})

        restart()

    # then the container is started, since a stopped container cannot be restarted
    assert container.method_calls == [call.snapshot(), call.start()]


def test_restart_rejects_a_missing_container(tmp_path: Path) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = None

        # when restarting from within that project directory
        restart()

    # then the error says how to create the container, and nothing is started
    assert str(error.value) == (
        "No container named 'my-project'. Run `ask create` first."
    )
    assert container.method_calls == [call.snapshot()]


def test_stop_stops_a_running_container(tmp_path: Path) -> None:
    # given a project directory with a running container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    # when stopping from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Running", config={})

        stop()

    # then the container named after the project directory is stopped
    container_cls.assert_called_once_with("my-project")
    assert container.method_calls == [call.snapshot(), call.stop()]


def test_stop_does_nothing_to_an_already_stopped_container(tmp_path: Path) -> None:
    # given a project directory with a stopped container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    # when stopping from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})

        stop()

    # then the container is left alone
    assert container.method_calls == [call.snapshot()]


def test_stop_rejects_a_missing_container(tmp_path: Path) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = None

        # when stopping from within that project directory
        stop()

    # then the error says how to create the container, and nothing is stopped
    assert str(error.value) == (
        "No container named 'my-project'. Run `ask create` first."
    )
    assert container.method_calls == [call.snapshot()]


def test_destroy_deletes_a_stopped_container(tmp_path: Path) -> None:
    # given a project directory with a stopped container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    # when destroying from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})

        destroy()

    # then the container named after the project directory is deleted
    container_cls.assert_called_once_with("my-project")
    assert container.method_calls == [call.snapshot(), call.delete()]


def test_destroy_stops_a_running_container_before_deleting_it(tmp_path: Path) -> None:
    # given a project directory with a running container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    # when destroying from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Running", config={})

        destroy()

    # then the container is stopped first, since a running container cannot be deleted
    assert container.method_calls == [call.snapshot(), call.stop(), call.delete()]


def test_destroy_rejects_a_missing_container(tmp_path: Path) -> None:
    # given a project directory without a container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = None

        # when destroying from within that project directory
        destroy()

    # then the error says the container does not exist, and nothing is deleted
    assert str(error.value) == "No container named 'my-project'."
    assert container.method_calls == [call.snapshot()]


def test_converge_normalizes_short_service_names_in_manifest(tmp_path: Path) -> None:
    # given a project with short service names in the manifest
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text(
        'services.short = "enabled"\nservices.another = "disabled"\nservices."full.socket" = "masked"\n'
    )
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + '[layers.base]\nservices."existing.service" = "masked"\nservices."layer.socket" = "enabled"\n'
    )

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the services are normalized (short names get .service suffix)
    provisioner_cls.return_value.provision_services.assert_called_once_with(
        {
            "existing.service": "masked",
            "layer.socket": "enabled",  # Preserved from layer
            "short.service": "enabled",  # Normalized from manifest
            "another.service": "disabled",  # Normalized from manifest
            "full.socket": "masked",  # Preserved from manifest
        }
    )


def test_converge_provisions_the_idle_shutdown_watch(tmp_path: Path) -> None:
    # given a project directory, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the idle shutdown watch is provisioned for the resolved user, so
    # the instance shuts itself down once it has been idle for a while
    provisioner_cls.return_value.provision_idle_shutdown.assert_called_once_with(
        "arch",
        ResolvedUser(
            name="raniz",
            uid=1000,
            shell="bash",
            group_name="raniz",
            gid=1000,
            extra_groups=[],
        ),
    )


def test_converge_records_an_invocation_on_the_container(tmp_path: Path) -> None:
    # given a project directory with a container, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')
    at = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
        patch("ask.cli.datetime") as datetime_mock,
    ):
        datetime_mock.now.return_value = at
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        converge()

    # then the invocation is recorded on the container's metadata, so the
    # idle watch inside the instance does not shut it down mid-convergence
    container.set_invocation_at.assert_called_once_with(at)


@pytest.mark.parametrize(
    ("command", "expected_command"),
    [
        (lambda: exec("erl"), ["erl"]),
        (lambda: agent(), ["claude"]),
    ],
    ids=["exec", "agent"],
)
def test_commands_record_the_invocation_before_and_after_running(
    tmp_path: Path, command: Callable[[], None], expected_command: list[str]
) -> None:
    # given a project directory and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(
        _FLAVOR
        + "[layers.base]\nagents = { claude = true }\n"
        + '[user]\nname = "raniz"\nuid = 1000\n'
    )
    at = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

    # when running a command in the project's container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.converge"),
        patch("ask.cli.datetime") as datetime_mock,
        pytest.raises(SystemExit),
    ):
        datetime_mock.now.return_value = at
        container = container_cls.return_value
        container.exec_command.return_value = 0
        command()

    # then the invocation is recorded on the container when it is ensured
    # running, both before the command starts and after it ends, so the idle
    # window starts when the command ends
    assert container.set_invocation_at.call_args_list == [call(at), call(at), call(at)]


def test_enter_records_the_invocation_before_and_after_the_session(
    tmp_path: Path,
) -> None:
    # given a project directory and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')
    at = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

    # when entering the project's container
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.converge"),
        patch("ask.cli.datetime") as datetime_mock,
        pytest.raises(SystemExit),
    ):
        datetime_mock.now.return_value = at
        container = container_cls.return_value
        container.exec_command.return_value = 0
        enter()

    # then the invocation is recorded when the container is ensured running,
    # both before the shell starts and after the session ends, so the idle
    # window starts when the session ends
    assert container.set_invocation_at.call_args_list == [call(at), call(at), call(at)]


def test_refresh_invocations_records_repeatedly_until_stopped() -> None:
    # given a container and a stop event
    container = Mock()
    stop = threading.Event()
    records: list[Mock] = []

    # when the refresher loop runs with a zero interval, stopping after three
    # records
    def record(recorded: Mock) -> None:
        records.append(recorded)
        if len(records) == 3:
            stop.set()

    with (
        patch("ask.cli._INVOCATION_REFRESH_INTERVAL", 0),
        patch("ask.cli._record_invocation", side_effect=record),
    ):
        _refresh_invocations(container, stop)

    # then the invocation was recorded over and over until the stop event
    assert records == [container, container, container]


def test_converge_keeps_refreshing_the_invocation_while_it_runs(
    tmp_path: Path,
) -> None:
    # given a project directory with a container, and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')
    refreshed = threading.Event()

    # when converging, with one provisioning step blocking until the invocation
    # has been recorded again by the background refresher
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner") as provisioner_cls,
        patch("ask.cli.provision.AurBuilder"),
        patch("ask.cli._INVOCATION_REFRESH_INTERVAL", 0.05),
    ):
        container = container_cls.return_value
        container.get_managed_packages.return_value = []

        def record(at: datetime) -> None:
            if container.set_invocation_at.call_count >= 2:
                refreshed.set()

        container.set_invocation_at.side_effect = record
        provisioner_cls.return_value.provision_user.side_effect = (
            lambda *args, **kwargs: refreshed.wait(timeout=10)
        )

        converge()

    # then the invocation was refreshed while convergence was still running,
    # so the idle watch inside the instance cannot shut it down mid-converge
    assert refreshed.is_set()
    assert container.set_invocation_at.call_count >= 2


def test_enter_keeps_refreshing_the_invocation_while_waiting_at_a_prompt(
    tmp_path: Path,
) -> None:
    # given a project directory whose container's configuration has changed,
    # and a config declaring a user
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR + '[user]\nname = "raniz"\nuid = 1000\n')

    # when entering the container, and the converge prompt blocks until the
    # invocation has been recorded again by the background refresher
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.converge"),
        patch("ask.cli.sys.stdin") as stdin_mock,
        patch("ask.cli._confirm") as confirm_mock,
        patch("ask.cli._INVOCATION_REFRESH_INTERVAL", 0.05),
        pytest.raises(SystemExit),
    ):
        stdin_mock.isatty.return_value = True
        container = container_cls.return_value
        container.exec_command.return_value = 0

        def wait_for_refresh(prompt: str) -> bool:
            deadline = time.monotonic() + 10
            while container.set_invocation_at.call_count < 2:
                assert time.monotonic() < deadline, "invocation was not refreshed"
                time.sleep(0.01)
            return False

        confirm_mock.side_effect = wait_for_refresh

        enter()

    # then the invocation was refreshed while ask was waiting at the prompt,
    # so the idle watch cannot shut the instance down while ask is using it
    assert container.set_invocation_at.call_count >= 2


def test_init_creates_a_documented_ask_toml(tmp_path: Path) -> None:
    # given an empty project directory
    # when running init from within it
    with patch("ask.cli.Path.cwd", return_value=tmp_path):
        init()

    # then ask.toml is created, documenting every possible manifest field
    path = tmp_path / "ask.toml"
    assert path.exists()
    content = path.read_text()
    for field_name in (
        "packages",
        "bind_mounts",
        "services",
        "tool_managers",
        "scripts",
    ):
        assert field_name in content

    # and the generated file is a valid, empty manifest
    assert load_manifest(path) == Manifest()


def test_init_refuses_to_overwrite_an_existing_ask_toml(tmp_path: Path) -> None:
    # given a project directory that already has an ask.toml
    path = tmp_path / "ask.toml"
    path.write_text('packages = ["uv"]\n')

    # when running init from within it
    with (
        patch("ask.cli.Path.cwd", return_value=tmp_path),
        pytest.raises(AskError, match="already exists"),
    ):
        init()

    # then the existing file is left untouched
    assert path.read_text() == 'packages = ["uv"]\n'


def test_enter_logs_that_the_configuration_changed_and_converges(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # given a project whose container was converged with a stale configuration
    project_dir, config_path = _project(tmp_path)

    # when entering the container and accepting to converge
    with caplog.at_level(logging.DEBUG, logger="ask.cli"):
        _enter_with(project_dir, config_path, _STALE_SNAPSHOT, tty=True, answer="y")

    # then the changed configuration and the convergence are logged at debug level
    assert "configuration changed" in caplog.text
    assert "converging container" in caplog.text


def test_enter_logs_that_the_configuration_is_unchanged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # given a project whose container was converged with its current configuration
    project_dir, config_path = _project(tmp_path)
    snapshot = _converged_snapshot(project_dir)

    # when entering the container
    with caplog.at_level(logging.DEBUG, logger="ask.cli"):
        _enter_with(project_dir, config_path, snapshot, tty=True)

    # then the unchanged configuration is logged at debug level
    assert "configuration unchanged" in caplog.text


def test_converge_logs_starting_a_stopped_container(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # given a project directory with a stopped container
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("")
    config_path = _flavor_path(tmp_path)
    config_path.write_text(_FLAVOR)

    # when converging from within that project directory
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=config_path.parent),
        patch("ask.cli.incus.Container") as container_cls,
        patch("ask.cli.provision.Provisioner"),
        patch("ask.cli.provision.AurBuilder"),
        caplog.at_level(logging.DEBUG, logger="ask.cli"),
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})
        container.get_managed_packages.return_value = []

        converge()

    # then starting the stopped container is logged at debug level
    assert "starting stopped container 'my-project'" in caplog.text


def test_rename_renames_the_directory_and_the_container(tmp_path: Path) -> None:
    # given a project directory "old-project" with a running container, and no
    # "new-project" directory
    old_dir = tmp_path / "old-project"
    old_dir.mkdir()
    new_dir = tmp_path / "new-project"

    # when renaming the project
    with (
        patch("ask.cli.Path.cwd", return_value=tmp_path),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Running", config={})

        rename("old-project", "new-project")

    # then the directory is renamed, the container is stopped, renamed and its
    # bind mount is moved to the new directory
    assert not old_dir.exists()
    assert new_dir.is_dir()
    assert container.method_calls == [
        call.snapshot(),
        call.stop(),
        call.rename("new-project"),
        call.move_bind_mount(old_dir, new_dir),
    ]


def test_rename_leaves_a_stopped_container_running_state_alone(
    tmp_path: Path,
) -> None:
    # given a project directory "old-project" with a stopped container
    old_dir = tmp_path / "old-project"
    old_dir.mkdir()

    # when renaming the project
    with (
        patch("ask.cli.Path.cwd", return_value=tmp_path),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})

        rename("old-project", "new-project")

    # then the container is renamed without being stopped first
    assert container.method_calls == [
        call.snapshot(),
        call.rename("new-project"),
        call.move_bind_mount(old_dir, tmp_path / "new-project"),
    ]


def test_rename_only_fixes_the_container_when_the_directory_is_already_renamed(
    tmp_path: Path,
) -> None:
    # given no "old-project" directory, but a "new-project" directory, and a
    # running container for the old name
    old_dir = tmp_path / "old-project"
    new_dir = tmp_path / "new-project"
    new_dir.mkdir()

    # when renaming the project
    with (
        patch("ask.cli.Path.cwd", return_value=tmp_path),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Running", config={})

        rename("old-project", "new-project")

    # then only the container is stopped, renamed and its bind mount moved
    assert new_dir.is_dir()
    assert container.method_calls == [
        call.snapshot(),
        call.stop(),
        call.rename("new-project"),
        call.move_bind_mount(old_dir, new_dir),
    ]


def test_rename_rejects_when_neither_directory_exists(tmp_path: Path) -> None:
    # given neither an "old-project" nor a "new-project" directory
    # when renaming the project
    with (
        patch("ask.cli.Path.cwd", return_value=tmp_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(AskError) as error,
    ):
        rename("old-project", "new-project")

    # then the error names both missing directories, and no container is touched
    assert str(error.value) == (
        f"Neither {tmp_path / 'old-project'} nor {tmp_path / 'new-project'} exists."
    )
    container_cls.assert_not_called()


def test_rename_rejects_when_both_directories_exist(tmp_path: Path) -> None:
    # given both an "old-project" and a "new-project" directory
    (tmp_path / "old-project").mkdir()
    (tmp_path / "new-project").mkdir()

    # when renaming the project
    with (
        patch("ask.cli.Path.cwd", return_value=tmp_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(AskError) as error,
    ):
        rename("old-project", "new-project")

    # then the error says the target already exists, and no container is touched
    assert "already exists" in str(error.value)
    container_cls.assert_not_called()


def test_rename_rejects_a_missing_container(tmp_path: Path) -> None:
    # given a project directory "old-project" without a container
    old_dir = tmp_path / "old-project"
    old_dir.mkdir()

    with (
        patch("ask.cli.Path.cwd", return_value=tmp_path),
        patch("ask.cli.incus.Container") as container_cls,
        pytest.raises(ContainerNotFoundError) as error,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = None

        # when renaming the project
        rename("old-project", "new-project")

    # then the error says the container does not exist, and nothing is renamed
    assert str(error.value) == "No container named 'old-project'."
    assert container.method_calls == [call.snapshot()]


def _dump_in_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    manifest: str = "",
    layer: str = "",
) -> dict:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir(exist_ok=True)
    (project_dir / "ask.toml").write_text(manifest)
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir(exist_ok=True)
    (flavors_dir / "arch.toml").write_text(
        'distribution = "arch"\ndefault = true\n'
        '[user]\nname = "raniz"\nuid = 1000\n'
        "[layers.base]\n" + layer
    )
    with (
        patch("ask.cli.Path.cwd", return_value=project_dir),
        patch("ask.cli.config.default_dir", return_value=flavors_dir),
    ):
        dump()
    return json.loads(capsys.readouterr().out)


def test_dump_prints_the_full_resolved_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a flavour layer and a project manifest with packages, mounts,
    # services, env, an agent, a tool manager and a script
    cache = tmp_path / "cache"
    cache.mkdir()
    config = _dump_in_project(
        tmp_path,
        capsys,
        manifest=(
            f'packages = ["uv", "aur:hello"]\n'
            f'bind_mounts = ["{cache}"]\n'
            'tool_managers = ["mise"]\n'
            '[env]\nEDITOR = "nvim"\n'
            '[scripts]\ntest = "uv run pytest"\n'
        ),
        layer=(
            'packages = ["git"]\n'
            'services = { sshd = "enabled" }\n'
            "agents = { claude = true }\n"
            'env = { EDITOR = "vim", REMOVED = "x" }\n'
        ),
    )

    # then the dump shows the project, distribution and applied layers
    assert config["project_dir"] == str(tmp_path / "my-project")
    assert config["distribution"] == "arch"
    assert config["layers"] == ["base"]

    # and the resolved shell and user, including groups
    assert config["shell"] == {"name": "bash", "options": {}}
    assert config["user"] == {
        "name": "raniz",
        "uid": 1000,
        "gid": 1000,
        "group": "raniz",
        "shell": "bash",
        "extra_groups": [],
    }

    # and all packages to install, split by kind, including the ones the
    # shell and the agent add
    # mise has no config files in the project, so it adds no packages
    assert config["packages"] == {
        "official": ["git", "uv", "bash"],
        "aur": ["hello", "claude-code"],
        "npm": [],
    }

    # and all bind mounts, starting with the project directory
    mounts = config["bind_mounts"]
    assert mounts[0] == {
        "host": str(tmp_path / "my-project"),
        "container": str(tmp_path / "my-project"),
        "readonly": False,
    }
    assert mounts[1] == {
        "host": str(cache),
        "container": str(cache),
        "readonly": False,
    }

    # and the resolved services, merged environment and scripts
    assert config["services"] == {"sshd.service": "enabled"}
    assert config["env"] == {"EDITOR": "nvim", "REMOVED": "x"}
    assert config["scripts"] == {"test": "uv run pytest"}

    # and the tool managers with their config files
    assert config["tool_managers"] == [{"name": "mise", "config_files": []}]

    # and each agent with its options, extensions, env and mounted files
    assert len(config["agents"]) == 1
    claude = config["agents"][0]
    assert claude["name"] == "claude"
    assert claude["options"] == {}
    assert claude["extensions"] == []
    assert claude["env"] == {"EDITOR": "nvim", "REMOVED": "x"}
    assert isinstance(claude["mounts"], list)


def test_dump_resolves_removals_and_merged_agent_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a layer that installs git and enables an agent with options and
    # env, and a manifest that removes git and overrides the agent env
    config = _dump_in_project(
        tmp_path,
        capsys,
        manifest=('packages = ["-git"]\n[env]\nEDITOR = "emacs"\n'),
        layer=(
            'packages = ["git", "htop"]\n'
            'agents = { claude = { auth = false, env = { EDITOR = "vim" } } }\n'
        ),
    )

    # then the removed package is gone and the agent's own env wins over
    # the manifest env
    assert config["packages"]["official"] == ["htop", "bash"]
    claude = config["agents"][0]
    assert claude["options"] == {"auth": False}
    assert claude["env"] == {"EDITOR": "vim"}
