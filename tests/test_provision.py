import io
import logging
import subprocess
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

import pytest
from pyinfra.api.exceptions import PyinfraError
from pyinfra.api.output import echo
from pyinfra.operations import apt, files, pacman, server, systemd

from ask import idle
from ask.env import profile_script
from ask.incus import Container
from ask.provision import (
    AurBuilder,
    MiseProvisioner,
    Provisioner,
    ProvisioningError,
    _ancestors_under_home,
    split_aur_packages,
)
from ask.tool_manager import config_digest
from ask.user import ResolvedUser


def test_provision_user_targets_the_container_via_the_incus_connector() -> None:
    # given a resolved user, and a provisioner targeting a named container
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )
    provisioner = Provisioner(Container("my-project"))

    # when provisioning that user
    with (
        patch("ask.provision.Inventory") as inventory_cls,
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_user(user)

    # then the inventory targets that container through the incus connector,
    # and a pyinfra state is built from it
    inventory_cls.assert_called_once_with((["@incus/my-project"], {}))
    state_cls.assert_called_once_with(inventory_cls.return_value, ANY)


def test_provision_user_connects_before_running_operations() -> None:
    # given a resolved user, and a provisioner
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )
    provisioner = Provisioner(Container("my-project"))

    # when provisioning that user
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all") as connect_all,
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops") as run_ops,
    ):
        provisioner.provision_user(user)

    # then the state is connected before operations are run
    connect_all.assert_called_once_with(state_cls.return_value)
    run_ops.assert_called_once_with(state_cls.return_value)


def test_provision_services_enabled(tmp_path: Path) -> None:
    # given a provisioner and services to enable
    provisioner = Provisioner(Container("my-project"))
    services = {"sshd.service": "enabled"}

    # when provisioning those services
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_services(services)

    # then the systemd operation is called with enabled=True and running=True
    state_cls.return_value.print_output = True
    state_cls.return_value.print_input = True
    add_op.assert_called_once_with(
        state_cls.return_value,
        systemd.service,
        service="sshd.service",
        enabled=True,
        running=True,
    )


def test_provision_services_disabled(tmp_path: Path) -> None:
    # given a provisioner and services to disable
    provisioner = Provisioner(Container("my-project"))
    services = {"sshd.service": "disabled"}

    # when provisioning those services
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_services(services)

    # then the systemd operation is called with enabled=False and running=False
    state_cls.return_value.print_output = True
    state_cls.return_value.print_input = True
    add_op.assert_called_once_with(
        state_cls.return_value,
        systemd.service,
        service="sshd.service",
        enabled=False,
        running=False,
    )


def test_provision_services_masked(tmp_path: Path) -> None:
    # given a provisioner and services to mask
    provisioner = Provisioner(Container("my-project"))
    services = {"sshd.service": "masked"}

    # when provisioning those services
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_services(services)

    # then the systemd operation is called with masked=True and running=False
    state_cls.return_value.print_output = True
    state_cls.return_value.print_input = True
    add_op.assert_called_once_with(
        state_cls.return_value,
        systemd.service,
        service="sshd.service",
        masked=True,
        running=False,
    )


def test_provision_services_multiple(tmp_path: Path) -> None:
    # given a provisioner and multiple services
    provisioner = Provisioner(Container("my-project"))
    services = {
        "sshd.service": "enabled",
        "man-db.timer": "disabled",
        "cronie.service": "masked",
    }

    # when provisioning those services
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_services(services)

    # then the systemd operations are called with the correct parameters
    state_cls.return_value.print_output = True
    state_cls.return_value.print_input = True
    calls = [
        call(
            state_cls.return_value,
            systemd.service,
            service="sshd.service",
            enabled=True,
            running=True,
        ),
        call(
            state_cls.return_value,
            systemd.service,
            service="man-db.timer",
            enabled=False,
            running=False,
        ),
        call(
            state_cls.return_value,
            systemd.service,
            service="cronie.service",
            masked=True,
            running=False,
        ),
    ]
    add_op.assert_has_calls(calls, any_order=True)


def test_provision_user_enables_output_printing() -> None:
    # given a resolved user, and a provisioner
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )
    provisioner = Provisioner(Container("my-project"))
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_user(user)

    # then the state is configured to print command output and input as it runs
    state = state_cls.return_value
    assert state.print_output is True
    assert state.print_input is True


def test_provision_user_ensures_the_users_group() -> None:
    # given a resolved user with its own group, and a provisioner
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )
    provisioner = Provisioner(Container("my-project"))

    # when provisioning that user
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_user(user)

    # then the group is ensured with the resolved name and gid
    add_op.assert_any_call(
        state_cls.return_value, server.group, group="raniz", gid=1000
    )


def test_provision_user_ensures_the_user() -> None:
    # given a fully resolved user, including extra groups, and a provisioner
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=["wheel"],
    )
    provisioner = Provisioner(Container("my-project"))

    # when provisioning that user
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_user(user)

    # then the user is ensured with the resolved name, uid, primary group,
    # extra groups and a home directory, with the shell resolved to a full path
    add_op.assert_any_call(
        state_cls.return_value,
        server.user,
        user="raniz",
        uid=1000,
        group="raniz",
        groups=["wheel"],
        shell="/bin/zsh",
        create_home=True,
    )


def test_provision_packages_installs_packages_via_the_distribution_operation() -> None:
    # given a provisioner, and a list of packages to install on arch
    provisioner = Provisioner(Container("my-project"))

    # when provisioning packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_packages("arch", ["zsh", "python"])

    # then the arch package operation is used to ensure the packages are
    # present, syncing the package database and upgrading all packages first
    add_op.assert_any_call(
        state_cls.return_value,
        pacman.packages,
        packages=["zsh", "python"],
        update=True,
        upgrade=True,
    )


def test_provision_packages_connects_before_running_operations() -> None:
    # given a provisioner, and a list of packages to install on arch
    provisioner = Provisioner(Container("my-project"))

    # when provisioning packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all") as connect_all,
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops") as run_ops,
    ):
        provisioner.provision_packages("arch", ["zsh"])

    # then the state is connected before operations are run
    connect_all.assert_called_once_with(state_cls.return_value)
    run_ops.assert_called_once_with(state_cls.return_value)


def test_provision_packages_enables_output_printing() -> None:
    # given a provisioner, and a list of packages to install on arch
    provisioner = Provisioner(Container("my-project"))

    # when provisioning packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_packages("arch", ["zsh"])

    # then the state is configured to print command output and input as it runs
    state = state_cls.return_value
    assert state.print_output is True
    assert state.print_input is True


def test_provision_packages_installs_packages_on_debian_via_apt() -> None:
    # given a provisioner, and a list of packages to install on debian
    provisioner = Provisioner(Container("my-project"))

    # when provisioning packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_packages("debian", ["zsh", "python"])

    # then the debian package operation is used to ensure the packages are
    # present, syncing the package database and upgrading all packages first
    add_op.assert_any_call(
        state_cls.return_value,
        apt.packages,
        packages=["zsh", "python"],
        update=True,
        upgrade=True,
    )


def test_provision_packages_raises_for_an_unsupported_distribution() -> None:
    # given a provisioner, and a distribution with no known package operation
    provisioner = Provisioner(Container("my-project"))

    # when provisioning packages
    # then a clear error is raised
    with pytest.raises(ValueError, match="gentoo"):
        provisioner.provision_packages("gentoo", ["zsh"])


def test_remove_packages_removes_packages_via_the_distribution_operation() -> None:
    # given a provisioner, and a list of packages no longer declared, to
    # remove on arch
    provisioner = Provisioner(Container("my-project"))

    # when removing packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.remove_packages("arch", ["old-pkg"])

    # then the arch package operation is used to ensure the packages are absent
    add_op.assert_any_call(
        state_cls.return_value,
        pacman.packages,
        packages=["old-pkg"],
        present=False,
    )


def test_remove_packages_connects_before_running_operations() -> None:
    # given a provisioner, and a list of packages to remove on arch
    provisioner = Provisioner(Container("my-project"))

    # when removing packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all") as connect_all,
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops") as run_ops,
    ):
        provisioner.remove_packages("arch", ["old-pkg"])

    # then the state is connected before operations are run
    connect_all.assert_called_once_with(state_cls.return_value)
    run_ops.assert_called_once_with(state_cls.return_value)


def test_remove_packages_enables_output_printing() -> None:
    # given a provisioner, and a list of packages to remove on arch
    provisioner = Provisioner(Container("my-project"))

    # when removing packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        provisioner.remove_packages("arch", ["old-pkg"])

    # then the state is configured to print command output and input as it runs
    state = state_cls.return_value
    assert state.print_output is True
    assert state.print_input is True


def test_remove_packages_removes_packages_on_debian_via_apt() -> None:
    # given a provisioner, and a list of packages no longer declared, to
    # remove on debian
    provisioner = Provisioner(Container("my-project"))

    # when removing packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.remove_packages("debian", ["old-pkg"])

    # then the debian package operation is used to ensure the packages are absent
    add_op.assert_any_call(
        state_cls.return_value,
        apt.packages,
        packages=["old-pkg"],
        present=False,
    )


def test_remove_packages_raises_for_an_unsupported_distribution() -> None:
    # given a provisioner, and a distribution with no known package operation
    provisioner = Provisioner(Container("my-project"))

    # when removing packages
    # then a clear error is raised
    with pytest.raises(ValueError, match="gentoo"):
        provisioner.remove_packages("gentoo", ["old-pkg"])


def test_split_aur_packages_separates_aur_prefixed_packages() -> None:
    # given a mix of official and aur-prefixed packages
    # when splitting them
    official, aur = split_aur_packages(["git", "aur:yay-bin", "python"])

    # then the official packages are returned as-is, and the aur packages
    # have their prefix stripped
    assert official == ["git", "python"]
    assert aur == ["yay-bin"]


def test_split_aur_packages_returns_empty_aur_list_when_none_declared() -> None:
    # given only official packages
    # when splitting them
    official, aur = split_aur_packages(["git", "python"])

    # then all of them are official, and none are aur
    assert official == ["git", "python"]
    assert aur == []


def test_split_aur_packages_returns_empty_official_list_when_all_are_aur() -> None:
    # given only aur-prefixed packages
    # when splitting them
    official, aur = split_aur_packages(["aur:yay-bin", "aur:paru"])

    # then none of them are official, and both are aur, prefix stripped
    assert official == []
    assert aur == ["yay-bin", "paru"]


def test_split_aur_packages_returns_empty_lists_for_no_packages() -> None:
    # given no packages at all
    # when splitting them
    official, aur = split_aur_packages([])

    # then both lists are empty
    assert official == []
    assert aur == []


def test_aur_builder_provision_builder_ensures_a_system_group_and_user() -> None:
    # given no existing aur builder provisioning
    aur_builder = AurBuilder(Container("my-project"))

    # when provisioning the aur builder
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        aur_builder.provision_builder()

    # then a system group and user named "aur" are ensured with fixed ids, so
    # that files they own on the shared paru volume line up across containers,
    # with a home directory to build in and no login shell
    add_op.assert_any_call(
        state_cls.return_value, server.group, group="aur", gid=900, system=True
    )
    add_op.assert_any_call(
        state_cls.return_value,
        server.user,
        user="aur",
        uid=900,
        group="aur",
        system=True,
        shell="/usr/bin/nologin",
        create_home=True,
    )


def test_aur_builder_provision_builder_installs_build_dependencies() -> None:
    # given no existing aur builder provisioning
    aur_builder = AurBuilder(Container("my-project"))

    # when provisioning the aur builder
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        aur_builder.provision_builder()

    # then the packages needed to build from a PKGBUILD are ensured present
    add_op.assert_any_call(
        state_cls.return_value,
        pacman.packages,
        packages=["base-devel", "git"],
        update=True,
    )


def test_aur_builder_provision_builder_writes_a_pacman_scoped_sudoers_dropin() -> None:
    # given no existing aur builder provisioning
    aur_builder = AurBuilder(Container("my-project"))

    # when provisioning the aur builder
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State"),
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        aur_builder.provision_builder()

    # then a sudoers.d drop-in is written, granting passwordless sudo scoped
    # to pacman itself (needed for both dependency resolution and installing
    # the locally built package, whatever flag order makepkg/paru use), but
    # nothing broader than that
    put_call = next(c for c in add_op.call_args_list if c.args[1] is files.put)
    kwargs = put_call.kwargs
    assert kwargs["src"].read() == "aur ALL=(root) NOPASSWD: /usr/bin/pacman *\n"
    assert kwargs["dest"] == "/etc/sudoers.d/ask-aur"
    assert kwargs["user"] == "root"
    assert kwargs["group"] == "root"
    assert kwargs["mode"] == "440"


def test_aur_builder_provision_builder_connects_before_running_operations() -> None:
    # given no existing aur builder provisioning
    aur_builder = AurBuilder(Container("my-project"))

    # when provisioning the aur builder
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all") as connect_all,
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops") as run_ops,
    ):
        aur_builder.provision_builder()

    # then the state is connected before operations are run
    connect_all.assert_called_once_with(state_cls.return_value)
    run_ops.assert_called_once_with(state_cls.return_value)


def test_share_paru_cache_attaches_the_shared_volume_at_parus_cache() -> None:
    # given a container whose aur builder should share paru's state with
    # other containers
    aur_builder = AurBuilder(Container("my-project"))

    # when sharing paru's cache
    with (
        patch("ask.provision.incus.ensure_storage_volume") as ensure_volume,
        patch.object(Container, "attach_volume") as attach_volume,
        patch("ask.provision.Inventory"),
        patch("ask.provision.State"),
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        aur_builder.share_paru_cache()

    # then the shared custom volume is ensured, and attached at the aur
    # builder's paru cache directory
    ensure_volume.assert_called_once_with("default", "ask-paru")
    attach_volume.assert_called_once_with(
        "default", "ask-paru", "paru-cache", Path("/home/aur/.cache/paru")
    )


def test_share_paru_cache_makes_the_aur_builder_own_the_cache_directories() -> None:
    # given a container whose shared paru volume is mounted by incus as root
    aur_builder = AurBuilder(Container("my-project"))

    # when sharing paru's cache
    with (
        patch("ask.provision.incus.ensure_storage_volume"),
        patch.object(Container, "attach_volume"),
        patch("ask.provision.Inventory"),
        patch("ask.provision.State"),
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        aur_builder.share_paru_cache()

    # then the cache directory and the mounted volume are owned by the aur
    # builder, so paru can write to them
    directory_calls = [
        c.kwargs for c in add_op.call_args_list if c.args[1] is files.directory
    ]
    assert directory_calls == [
        {"path": "/home/aur/.cache", "user": "aur", "group": "aur"},
        {"path": "/home/aur/.cache/paru", "user": "aur", "group": "aur"},
    ]


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


def test_ensure_paru_does_nothing_when_already_installed() -> None:
    # given a container that already has paru installed
    aur_builder = AurBuilder(Container("my-project"))
    with (
        patch.object(
            Container, "run_command", return_value=_completed(0)
        ) as run_command,
        patch.object(Container, "exec_command") as exec_command,
    ):
        # when ensuring paru is present
        aur_builder.ensure_paru()

    # then only the presence check is made, and nothing is built
    run_command.assert_called_once_with(["pacman", "-Qq", "paru"])
    exec_command.assert_not_called()


_CLONE_PARENT = Path("/home/aur/.cache/paru/clone")
_CLONE = _CLONE_PARENT / "paru-bin"


def _runuser_git(*args: str) -> list[str]:
    return ["runuser", "-u", "aur", "--", "git", "-C", str(_CLONE), *args]


def _container_without_paru(
    *, clone_exists: bool = False, seen: str | None = None, head: str = "abc123"
) -> Callable[[list[str]], subprocess.CompletedProcess]:
    def run_command(command: list[str]) -> subprocess.CompletedProcess:
        if command == ["pacman", "-Qq", "paru"]:
            return _completed(1)
        if command in (["id", "-u", "aur"], ["id", "-g", "aur"]):
            return _completed(0, "1001\n")
        if command == ["test", "-d", str(_CLONE / ".git")]:
            return _completed(0 if clone_exists else 1)
        if command == _runuser_git("rev-parse", "--verify", "--quiet", "AUR_SEEN"):
            return _completed(0, f"{seen}\n") if seen else _completed(1)
        if command == _runuser_git("rev-parse", "--verify", "--quiet", "HEAD"):
            return _completed(0, f"{head}\n")
        return _completed(127)

    return run_command


def _exec_commands(exec_command: MagicMock) -> list[list[str]]:
    return [c.args[3] for c in exec_command.call_args_list]


def _provisioner_user() -> ResolvedUser:
    return ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )


def test_provision_pi_extensions_installs_each_extension_as_the_user() -> None:
    # given a provisioner, a resolved user, and pi extensions
    provisioner = Provisioner(Container("my-project"))
    user = _provisioner_user()

    # when provisioning the extensions
    with patch.object(Container, "exec_command", return_value=0) as exec_command:
        provisioner.provision_pi_extensions(
            user, ["@foo/bar", "https://example.com/ext.git"]
        )

    # then `pi install` runs for each extension, as the user, in their home
    # directory, with HOME set
    assert _exec_commands(exec_command) == [
        ["pi", "install", "@foo/bar"],
        ["pi", "install", "https://example.com/ext.git"],
    ]
    for c in exec_command.call_args_list:
        assert c.args[:3] == (1000, 1000, Path("/home/raniz"))
        assert c.kwargs["env"] == {"HOME": "/home/raniz"}


def test_provision_pi_extensions_does_nothing_without_extensions() -> None:
    # given a provisioner, a resolved user, and no extensions
    provisioner = Provisioner(Container("my-project"))

    # when provisioning them
    with patch.object(Container, "exec_command") as exec_command:
        provisioner.provision_pi_extensions(_provisioner_user(), [])

    # then no command runs in the container
    exec_command.assert_not_called()


def test_provision_pi_extensions_raises_when_an_install_fails() -> None:
    # given a provisioner, a resolved user, an extension, and a failing install
    provisioner = Provisioner(Container("my-project"))

    # when provisioning the extension
    with (
        patch.object(Container, "exec_command", return_value=1),
        pytest.raises(ProvisioningError, match=r"`pi install @foo/bar`"),
    ):
        provisioner.provision_pi_extensions(_provisioner_user(), ["@foo/bar"])


def test_provision_pi_installs_the_standalone_binary_as_root() -> None:
    # given a provisioner
    provisioner = Provisioner(Container("my-project"))

    # when provisioning pi
    with patch.object(Container, "exec_command", return_value=0) as exec_command:
        provisioner.provision_pi()

    # then a shell script runs as root in the container, downloading the
    # release tarball, verifying its checksum, and installing pi on the
    # default PATH
    assert exec_command.call_count == 1
    args = exec_command.call_args.args
    assert args[:3] == (0, 0, Path("/tmp"))
    assert args[3][:2] == ["sh", "-c"]
    script = args[3][2]
    assert "earendil-works/pi/releases" in script
    assert "sha256sum -c" in script
    assert "/usr/local/bin/pi" in script


def test_provision_pi_raises_when_the_install_fails() -> None:
    # given a provisioner and a failing install
    provisioner = Provisioner(Container("my-project"))

    # when provisioning pi
    with (
        patch.object(Container, "exec_command", return_value=1),
        pytest.raises(ProvisioningError, match="sh -c"),
    ):
        provisioner.provision_pi()


def test_provision_mise_adds_the_signed_apt_repo_and_installs_mise() -> None:
    # given a provisioner on a debian container, which has no mise package
    provisioner = Provisioner(Container("my-project"))

    # when provisioning mise
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_mise()

    # then mise's signing key is installed, the repository is added with
    # signed-by pointing at it, and mise is installed from it with apt
    assert add_op.call_args_list == [
        call(
            state_cls.return_value,
            files.directory,
            path="/etc/apt/keyrings",
            user="root",
            group="root",
            mode="755",
        ),
        call(
            state_cls.return_value,
            files.download,
            src="https://mise.jdx.dev/gpg-key.pub",
            dest="/etc/apt/keyrings/mise-archive-keyring.asc",
            user="root",
            group="root",
            mode="644",
        ),
        call(
            state_cls.return_value,
            apt.repo,
            src="deb [signed-by=/etc/apt/keyrings/mise-archive-keyring.asc] "
            "https://mise.jdx.dev/deb stable main",
            filename="mise",
        ),
        call(state_cls.return_value, apt.packages, packages=["mise"], update=True),
    ]


def test_provision_mise_raises_when_the_repository_setup_fails() -> None:
    # given a provisioner and a failing provisioning session
    provisioner = Provisioner(Container("my-project"))

    # when provisioning mise
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State"),
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops", side_effect=PyinfraError("boom")),
        pytest.raises(ProvisioningError, match="boom"),
    ):
        provisioner.provision_mise()


def test_ensure_paru_clones_reviews_and_builds_paru_bin_when_approved() -> None:
    # given a container without paru that has never cloned paru-bin, and a
    # user who approves the build after reviewing the PKGBUILD
    aur_builder = AurBuilder(Container("my-project"))
    with (
        patch.object(Container, "run_command", side_effect=_container_without_paru()),
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("builtins.input", return_value="y"),
    ):
        # when ensuring paru is present
        aur_builder.ensure_paru()

    # then paru-bin is cloned into paru's shared clone directory, its PKGBUILD
    # is shown, the reviewed commit is marked as seen the way paru does, and
    # it is built, all as the aur builder user
    exec_command.assert_has_calls(
        [
            call(
                1001,
                1001,
                Path("/home/aur"),
                [
                    "git",
                    "clone",
                    "https://aur.archlinux.org/paru-bin.git",
                    str(_CLONE),
                ],
            ),
            call(1001, 1001, _CLONE, ["cat", "PKGBUILD"]),
            call(1001, 1001, _CLONE, ["git", "update-ref", "AUR_SEEN", "HEAD"]),
            call(1001, 1001, _CLONE, ["makepkg", "-si", "--noconfirm"]),
        ]
    )


def test_ensure_paru_updates_an_existing_clone_instead_of_recloning() -> None:
    # given a container without paru, whose shared paru cache already holds a
    # paru-bin clone, possibly reviewed from another container
    aur_builder = AurBuilder(Container("my-project"))
    with (
        patch.object(
            Container,
            "run_command",
            side_effect=_container_without_paru(clone_exists=True),
        ),
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("builtins.input", return_value="y"),
    ):
        # when ensuring paru is present
        aur_builder.ensure_paru()

    # then the existing clone is fast-forwarded, keeping its review marker,
    # rather than being removed and cloned afresh
    commands = _exec_commands(exec_command)
    assert commands[0] == ["git", "pull", "--ff-only"]
    assert [c for c in commands if c[:2] in (["rm", "-rf"], ["git", "clone"])] == []


def test_ensure_paru_builds_without_asking_when_head_was_already_reviewed() -> None:
    # given a container without paru, whose shared paru-bin clone was already
    # reviewed at its current commit
    aur_builder = AurBuilder(Container("my-project"))
    with (
        patch.object(
            Container,
            "run_command",
            side_effect=_container_without_paru(
                clone_exists=True, seen="abc123", head="abc123"
            ),
        ),
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("builtins.input") as input_,
    ):
        # when ensuring paru is present
        aur_builder.ensure_paru()

    # then the user is not asked again, nothing is shown for review, and
    # paru-bin is built
    input_.assert_not_called()
    assert _exec_commands(exec_command) == [
        ["git", "pull", "--ff-only"],
        ["makepkg", "-si", "--noconfirm"],
    ]


def test_ensure_paru_shows_only_the_changes_since_the_last_review() -> None:
    # given a container without paru, whose shared paru-bin clone was
    # reviewed at an earlier commit than its current one
    aur_builder = AurBuilder(Container("my-project"))
    with (
        patch.object(
            Container,
            "run_command",
            side_effect=_container_without_paru(
                clone_exists=True, seen="abc123", head="def456"
            ),
        ),
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("builtins.input", return_value="y"),
    ):
        # when ensuring paru is present
        aur_builder.ensure_paru()

    # then the diff since the reviewed commit is shown instead of the whole
    # PKGBUILD
    commands = _exec_commands(exec_command)
    assert ["git", "--no-pager", "diff", "AUR_SEEN", "HEAD"] in commands
    assert ["cat", "PKGBUILD"] not in commands


def test_ensure_paru_raises_without_building_when_the_user_declines() -> None:
    # given a container without paru, and a user who declines after
    # reviewing the PKGBUILD
    aur_builder = AurBuilder(Container("my-project"))
    with (
        patch.object(Container, "run_command", side_effect=_container_without_paru()),
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("builtins.input", return_value="n"),
        pytest.raises(ProvisioningError) as error,
    ):
        # when ensuring paru is present
        # then a clear error is raised
        aur_builder.ensure_paru()

    assert str(error.value) == (
        "The paru build was declined. Cannot install AUR packages."
    )

    # and the commit is neither marked as reviewed nor built
    commands = _exec_commands(exec_command)
    assert [c for c in commands if c[0] == "makepkg" or "update-ref" in c] == []


@pytest.mark.parametrize(
    ("failing_command", "expected_message"),
    [
        (
            "git",
            "`git clone https://aur.archlinux.org/paru-bin.git /home/aur/.cache/paru/clone/paru-bin` failed in container 'my-project' with exit status 128.",
        ),
        (
            "makepkg",
            "`makepkg -si --noconfirm` failed in container 'my-project' with exit status 128.",
        ),
    ],
)
def test_ensure_paru_reports_failing_build_steps(
    failing_command: str, expected_message: str
) -> None:
    # given a container without paru where one build step fails
    aur_builder = AurBuilder(Container("my-project"))

    def exec_command(uid: int, gid: int, cwd: Path, command: list[str]) -> int:
        return 128 if command[0] == failing_command else 0

    with (
        patch.object(Container, "run_command", side_effect=_container_without_paru()),
        patch.object(Container, "exec_command", side_effect=exec_command),
        patch("builtins.input", return_value="y"),
        pytest.raises(ProvisioningError) as error,
    ):
        # when ensuring paru is present
        aur_builder.ensure_paru()

    # then the error names the failing command and its exit status
    assert str(error.value) == expected_message


def test_install_packages_does_nothing_for_no_packages() -> None:
    # given no aur packages to install
    aur_builder = AurBuilder(Container("my-project"))
    with (
        patch.object(AurBuilder, "provision_builder") as builder,
        patch.object(AurBuilder, "share_paru_cache") as cache,
        patch.object(AurBuilder, "ensure_paru") as paru,
        patch.object(Container, "exec_command") as exec_command,
    ):
        # when installing aur packages
        aur_builder.install_packages("arch", [])

    # then nothing is provisioned at all
    builder.assert_not_called()
    cache.assert_not_called()
    paru.assert_not_called()
    exec_command.assert_not_called()


def test_install_packages_raises_for_an_unsupported_distribution() -> None:
    # given a distribution AUR is not meaningful for
    aur_builder = AurBuilder(Container("my-project"))

    # when installing aur packages
    # then a clear error is raised
    with pytest.raises(ValueError, match="debian"):
        aur_builder.install_packages("debian", ["yay-bin"])


def test_install_packages_builds_the_builder_and_paru_then_installs() -> None:
    # given aur packages to install on arch
    aur_builder = AurBuilder(Container("my-project"))
    calls: list[str] = []
    with (
        patch.object(
            AurBuilder,
            "provision_builder",
            side_effect=lambda: calls.append("provision_builder"),
        ),
        patch.object(
            AurBuilder,
            "share_paru_cache",
            side_effect=lambda: calls.append("share_paru_cache"),
        ),
        patch.object(
            AurBuilder, "ensure_paru", side_effect=lambda: calls.append("ensure_paru")
        ),
        patch.object(
            Container,
            "run_command",
            side_effect=[_completed(0, "1001\n"), _completed(0, "1001\n")],
        ),
        patch.object(Container, "exec_command", return_value=0) as exec_command,
    ):
        # when installing aur packages
        aur_builder.install_packages("arch", ["yay-bin", "some-other-pkg"])

    # then the builder user, the shared paru cache and paru are ensured, in
    # that order, before installing the declared packages as the aur builder
    # user, interactively
    assert calls == ["provision_builder", "share_paru_cache", "ensure_paru"]
    exec_command.assert_called_once_with(
        1001,
        1001,
        Path("/home/aur"),
        ["paru", "-S", "--needed", "yay-bin", "some-other-pkg"],
    )


def test_pyinfra_echo_actually_prints_to_stdout() -> None:
    # given pyinfra's echo defaults to a no-op until something installs a real
    # one, which importing ask.provision (already done for this test module)
    # is responsible for doing

    # when echoing a message through pyinfra's own output API
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        echo("hello from pyinfra")

    # then the message is actually printed, rather than swallowed
    assert "hello from pyinfra" in buffer.getvalue()


def test_pyinfra_echo_prints_to_stderr_when_requested() -> None:
    # given a message pyinfra's command-output reader marks for stderr
    # when echoing it with err=True
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        echo("stderr line", err=True)

    # then it is printed to stderr rather than stdout
    assert "stderr line" in buffer.getvalue()


def test_fix_bind_mount_ownership_chowns_ancestors_under_home() -> None:
    # given a provisioner, a resolved user, and bind mounts both under and
    # outside their home
    provisioner = Provisioner(Container("my-project"))
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )
    bind_mounts = [
        Path("/home/raniz/src/ask"),
        Path("/home/raniz/.cache/uv"),
        Path("/opt/foo"),
    ]

    # when fixing bind mount ownership
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops") as run_ops,
    ):
        provisioner.fix_bind_mount_ownership(bind_mounts, user)

    # then each ancestor under home is chowned to the resolved user, and the
    # mount outside home is left untouched
    add_op.assert_any_call(
        state_cls.return_value,
        files.directory,
        path="/home/raniz/src",
        user="raniz",
        group="raniz",
    )
    add_op.assert_any_call(
        state_cls.return_value,
        files.directory,
        path="/home/raniz/.cache",
        user="raniz",
        group="raniz",
    )
    run_ops.assert_called_once_with(state_cls.return_value)


def test_fix_bind_mount_ownership_enables_output_printing() -> None:
    # given a provisioner, a resolved user, and a bind mount under their home
    provisioner = Provisioner(Container("my-project"))
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )
    bind_mounts = [Path("/home/raniz/src/ask")]

    # when fixing bind mount ownership
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        provisioner.fix_bind_mount_ownership(bind_mounts, user)

    # then the state is configured to print command output and input as it runs
    state = state_cls.return_value
    assert state.print_output is True
    assert state.print_input is True


def test_fix_bind_mount_ownership_does_nothing_when_no_mounts_under_home() -> None:
    # given a provisioner, a resolved user, and bind mounts entirely outside
    # their home
    provisioner = Provisioner(Container("my-project"))
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )
    bind_mounts = [Path("/opt/foo")]

    # when fixing bind mount ownership
    with (
        patch("ask.provision.Inventory") as inventory_cls,
        patch("ask.provision.run_ops") as run_ops,
    ):
        provisioner.fix_bind_mount_ownership(bind_mounts, user)

    # then no inventory is even built, and no operations are run
    inventory_cls.assert_not_called()
    run_ops.assert_not_called()


def test_ancestors_under_home_returns_the_immediate_parent() -> None:
    # given a bind-mounted path one level under home
    # when finding its ancestors under home
    ancestors = _ancestors_under_home(Path("/home/raniz/src/ask"), Path("/home/raniz"))

    # then only its immediate parent is returned
    assert ancestors == [Path("/home/raniz/src")]


def test_ancestors_under_home_returns_every_level_innermost_first() -> None:
    # given a bind-mounted path nested several levels under home
    # when finding its ancestors under home
    ancestors = _ancestors_under_home(
        Path("/home/raniz/.local/share/foo"), Path("/home/raniz")
    )

    # then every intermediate directory is returned, innermost first, excluding
    # home itself
    assert ancestors == [Path("/home/raniz/.local/share"), Path("/home/raniz/.local")]


def test_ancestors_under_home_returns_none_when_path_is_home() -> None:
    # given a path that is the home directory itself
    # when finding its ancestors under home
    ancestors = _ancestors_under_home(Path("/home/raniz"), Path("/home/raniz"))

    # then there are no ancestors to fix
    assert ancestors == []


def test_ancestors_under_home_returns_none_when_path_is_outside_home() -> None:
    # given a path that doesn't live under home at all
    # when finding its ancestors under home
    ancestors = _ancestors_under_home(Path("/opt/foo"), Path("/home/raniz"))

    # then nothing is returned, since ownership outside home isn't ours to fix
    assert ancestors == []


_USER = ResolvedUser(
    name="raniz",
    uid=1000,
    shell="zsh",
    group_name="raniz",
    gid=1000,
    extra_groups=[],
)


@pytest.mark.parametrize("failing_step", ["connect_all", "run_ops"])
def test_provisioning_reports_pyinfra_failures(failing_step: str) -> None:
    # given a provisioner whose pyinfra step fails
    provisioner = Provisioner(Container("my-project"))
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State"),
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
        patch(
            f"ask.provision.{failing_step}",
            side_effect=PyinfraError("No hosts remaining!"),
        ),
        pytest.raises(ProvisioningError) as error,
    ):
        # when provisioning
        provisioner.provision_user(_USER)

    # then the error names the container and pyinfra's reason
    assert str(error.value) == (
        "Provisioning container 'my-project' failed: No hosts remaining!"
    )


def test_install_packages_reports_a_failing_paru_install() -> None:
    # given aur packages whose installation fails
    aur_builder = AurBuilder(Container("my-project"))
    with (
        patch.object(AurBuilder, "provision_builder"),
        patch.object(AurBuilder, "share_paru_cache"),
        patch.object(AurBuilder, "ensure_paru"),
        patch.object(
            Container,
            "run_command",
            side_effect=[_completed(0, "1001\n"), _completed(0, "1001\n")],
        ),
        patch.object(Container, "exec_command", return_value=1),
        pytest.raises(ProvisioningError) as error,
    ):
        # when installing them
        aur_builder.install_packages("arch", ["yay-bin"])

    # then the error names the failing command and its exit status
    assert str(error.value) == (
        "`paru -S --needed yay-bin` failed in container 'my-project' "
        "with exit status 1."
    )


_MISE_USER = ResolvedUser(
    name="raniz",
    uid=1000,
    shell="zsh",
    group_name="raniz",
    gid=1000,
    extra_groups=[],
)


def _mise_project(tmp_path: Path) -> tuple[Path, list[Path]]:
    project_dir = tmp_path / "my-project"
    (project_dir / ".config" / "mise").mkdir(parents=True)
    (project_dir / "mise.toml").write_text('[tools]\nerlang = "29.1.1"\n')
    (project_dir / ".config" / "mise" / "config.toml").write_text(
        '[env]\n_.file = ".env"\n'
    )
    return project_dir, [Path(".config/mise/config.toml"), Path("mise.toml")]


def test_mise_trust_shows_the_config_and_trusts_it_when_approved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a project with two mise config files that were never trusted
    project_dir, config_files = _mise_project(tmp_path)

    # and a user on a terminal who approves them
    with (
        patch.object(Container, "get_trusted_config_digest", return_value=None),
        patch.object(Container, "set_trusted_config_digest") as set_digest,
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("ask.provision.sys.stdin.isatty", return_value=True),
        patch("builtins.input", return_value="y"),
    ):
        # when trusting the project's mise config
        MiseProvisioner(Container("my-project")).trust(
            project_dir, _MISE_USER, config_files
        )

    # then each file is shown for review
    assert capsys.readouterr().out == (
        "==> .config/mise/config.toml <==\n"
        '[env]\n_.file = ".env"\n'
        "\n"
        "==> mise.toml <==\n"
        '[tools]\nerlang = "29.1.1"\n'
        "\n"
    )

    # and each file is trusted by mise, as the user with their home directory,
    # from the project directory
    assert exec_command.call_args_list == [
        call(
            1000,
            1000,
            project_dir,
            ["mise", "trust", str(project_dir / ".config/mise/config.toml")],
            env={"HOME": "/home/raniz"},
        ),
        call(
            1000,
            1000,
            project_dir,
            ["mise", "trust", str(project_dir / "mise.toml")],
            env={"HOME": "/home/raniz"},
        ),
    ]

    # and the reviewed files are recorded as trusted on the container
    set_digest.assert_called_once_with("mise", config_digest(project_dir, config_files))


def test_mise_trust_does_nothing_when_the_config_was_already_trusted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a project whose mise config was trusted as it is now
    project_dir, config_files = _mise_project(tmp_path)
    digest = config_digest(project_dir, config_files)

    with (
        patch.object(Container, "get_trusted_config_digest", return_value=digest),
        patch.object(Container, "set_trusted_config_digest") as set_digest,
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("builtins.input") as input_,
    ):
        # when trusting the project's mise config
        MiseProvisioner(Container("my-project")).trust(
            project_dir, _MISE_USER, config_files
        )

    # then nothing is shown, asked, trusted or recorded
    assert capsys.readouterr().out == ""
    input_.assert_not_called()
    exec_command.assert_not_called()
    set_digest.assert_not_called()


def test_mise_trust_raises_without_trusting_when_the_user_declines(
    tmp_path: Path,
) -> None:
    # given a project with mise config that changed since it was last trusted
    project_dir, config_files = _mise_project(tmp_path)

    # and a user on a terminal who declines it
    with (
        patch.object(Container, "get_trusted_config_digest", return_value="old"),
        patch.object(Container, "set_trusted_config_digest") as set_digest,
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("ask.provision.sys.stdin.isatty", return_value=True),
        patch("builtins.input", return_value="n"),
        pytest.raises(ProvisioningError) as error,
    ):
        # when trusting the project's mise config
        MiseProvisioner(Container("my-project")).trust(
            project_dir, _MISE_USER, config_files
        )

    # then a clear error is raised, and nothing is trusted or recorded
    assert str(error.value) == (
        "The mise config was declined. Cannot install its tools."
    )
    exec_command.assert_not_called()
    set_digest.assert_not_called()


def test_mise_trust_raises_without_asking_when_not_on_a_terminal(
    tmp_path: Path,
) -> None:
    # given a project with mise config that was never trusted
    project_dir, config_files = _mise_project(tmp_path)

    # and no terminal to ask on
    with (
        patch.object(Container, "get_trusted_config_digest", return_value=None),
        patch.object(Container, "set_trusted_config_digest") as set_digest,
        patch.object(Container, "exec_command", return_value=0) as exec_command,
        patch("ask.provision.sys.stdin.isatty", return_value=False),
        patch("builtins.input") as input_,
        pytest.raises(ProvisioningError) as error,
    ):
        # when trusting the project's mise config
        MiseProvisioner(Container("my-project")).trust(
            project_dir, _MISE_USER, config_files
        )

    # then the error says how to review it, and nothing is asked, trusted or
    # recorded
    assert str(error.value) == (
        "The mise config has not been reviewed. "
        "Run `ask converge` from a terminal to review it."
    )
    input_.assert_not_called()
    exec_command.assert_not_called()
    set_digest.assert_not_called()


def test_mise_trust_reports_a_failing_mise_trust(tmp_path: Path) -> None:
    # given a project with mise config, approved by the user, that mise fails
    # to trust
    project_dir, config_files = _mise_project(tmp_path)
    with (
        patch.object(Container, "get_trusted_config_digest", return_value=None),
        patch.object(Container, "set_trusted_config_digest") as set_digest,
        patch.object(Container, "exec_command", return_value=1),
        patch("ask.provision.sys.stdin.isatty", return_value=True),
        patch("builtins.input", return_value="y"),
        pytest.raises(ProvisioningError) as error,
    ):
        # when trusting the project's mise config
        MiseProvisioner(Container("my-project")).trust(
            project_dir, _MISE_USER, config_files
        )

    # then the error names the failing command, and nothing is recorded
    assert str(error.value) == (
        f"`mise trust {project_dir}/.config/mise/config.toml` failed in "
        "container 'my-project' with exit status 1."
    )
    set_digest.assert_not_called()


def test_mise_install_installs_the_tools_as_the_user_in_the_project(
    tmp_path: Path,
) -> None:
    # given a project directory
    project_dir = tmp_path / "my-project"

    with patch.object(Container, "exec_command", return_value=0) as exec_command:
        # when installing the project's mise tools
        MiseProvisioner(Container("my-project")).install(project_dir, _MISE_USER)

    # then mise installs them as the user with their home directory, from the
    # project directory
    exec_command.assert_called_once_with(
        1000, 1000, project_dir, ["mise", "install"], env={"HOME": "/home/raniz"}
    )


def test_mise_install_reports_a_failing_mise_install(tmp_path: Path) -> None:
    # given a project whose tools mise fails to install
    project_dir = tmp_path / "my-project"
    with (
        patch.object(Container, "exec_command", return_value=1),
        pytest.raises(ProvisioningError) as error,
    ):
        # when installing the project's mise tools
        MiseProvisioner(Container("my-project")).install(project_dir, _MISE_USER)

    # then the error names the failing command
    assert str(error.value) == (
        "`mise install` failed in container 'my-project' with exit status 1."
    )


def test_provision_idle_shutdown_installs_the_watch_and_enables_the_timer() -> None:
    # given a provisioner and the resolved user that commands run as
    provisioner = Provisioner(Container("my-project"))
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when provisioning the idle shutdown watch
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_idle_shutdown("arch", user)

    # then curl is installed for the watchdog script, the script and
    # the systemd units are put in place, systemd is reloaded, and the timer
    # is enabled and started
    state = state_cls.return_value
    calls = add_op.call_args_list
    assert calls[0] == call(state, pacman.packages, packages=["curl"])
    put_calls = [c for c in calls if c.args[1] == files.put]
    assert [(c.kwargs["dest"], c.kwargs["mode"]) for c in put_calls] == [
        ("/usr/local/bin/ask-idle-shutdown", "755"),
        ("/etc/systemd/system/ask-idle-shutdown.service", "644"),
        ("/etc/systemd/system/ask-idle-shutdown.timer", "644"),
    ]
    assert [c.kwargs["src"].getvalue() for c in put_calls] == [
        idle.shutdown_script(user),
        idle.service_unit(),
        idle.timer_unit(),
    ]
    assert calls[-2] == call(state, systemd.daemon_reload)
    assert calls[-1] == call(
        state,
        systemd.service,
        service="ask-idle-shutdown.timer",
        enabled=True,
        running=True,
    )


def test_provision_instance_env_puts_the_profile_script_in_place() -> None:
    # given a provisioner
    provisioner = Provisioner(Container("my-project"))

    # when provisioning the instance's environment variables
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provisioner.provision_instance_env({"EDITOR": "nvim"})

    # then the profile script exporting them is put in place for every login
    # shell
    add_op.assert_called_once_with(
        state_cls.return_value,
        files.put,
        src=ANY,
        dest="/etc/profile.d/ask.sh",
        user="root",
        group="root",
        mode="644",
    )
    assert add_op.call_args.kwargs["src"].getvalue() == profile_script(
        {"EDITOR": "nvim"}
    )


def test_provision_packages_logs_the_packages_being_installed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a provisioner targeting a named container
    provisioner = Provisioner(Container("my-project"))

    # when provisioning packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State"),
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
        caplog.at_level(logging.DEBUG, logger="ask.provision"),
    ):
        provisioner.provision_packages("arch", ["uv", "python"])

    # then the package list is logged at debug level
    assert "uv" in caplog.text
    assert "python" in caplog.text


def test_remove_packages_logs_the_packages_being_removed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a provisioner targeting a named container
    provisioner = Provisioner(Container("my-project"))

    # when removing stale packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State"),
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
        caplog.at_level(logging.DEBUG, logger="ask.provision"),
    ):
        provisioner.remove_packages("arch", ["old-package"])

    # then the removed packages are logged at debug level
    assert "removing packages" in caplog.text
    assert "old-package" in caplog.text


def test_provision_session_logs_the_target_container(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a provisioner targeting a named container
    provisioner = Provisioner(Container("my-project"))

    # when opening a provisioning session
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State"),
        patch("ask.provision.connect_all"),
        patch("ask.provision.run_ops"),
        caplog.at_level(logging.DEBUG, logger="ask.provision"),
        provisioner.session(),
    ):
        pass

    # then the target container is logged at debug level
    assert "my-project" in caplog.text
