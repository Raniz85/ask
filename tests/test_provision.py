import subprocess
from pathlib import Path
from unittest.mock import ANY, patch

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest
from pyinfra.api.output import echo
from pyinfra.operations import files, pacman, server

from ask.config import ResolvedUser
from ask.provision import (
    ensure_paru,
    fix_bind_mount_ownership,
    provision_aur_builder,
    provision_aur_packages,
    provision_packages,
    provision_user,
    remove_packages,
    split_aur_packages,
)


def test_provision_user_targets_the_container_via_the_incus_connector() -> None:
    # given a resolved user to provision
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when provisioning that user into a named container
    with (
        patch("ask.provision.Inventory") as inventory_cls,
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        provision_user("my-project", user)

    # then the inventory targets that container through the incus connector,
    # and a pyinfra state is built from it
    inventory_cls.assert_called_once_with((["@incus/my-project"], {}))
    state_cls.assert_called_once_with(inventory_cls.return_value, ANY)


def test_provision_user_connects_before_running_operations() -> None:
    # given a resolved user to provision
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when provisioning that user
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all") as connect_all,
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops") as run_ops,
    ):
        provision_user("my-project", user)

    # then the state is connected before operations are run
    connect_all.assert_called_once_with(state_cls.return_value)
    run_ops.assert_called_once_with(state_cls.return_value)


def test_provision_user_enables_output_printing() -> None:
    # given a resolved user to provision
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when provisioning that user
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        provision_user("my-project", user)

    # then the state is configured to print command output and input as it runs
    state = state_cls.return_value
    assert state.print_output is True
    assert state.print_input is True


def test_provision_user_ensures_the_users_group() -> None:
    # given a resolved user with its own group
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when provisioning that user
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provision_user("my-project", user)

    # then the group is ensured with the resolved name and gid
    add_op.assert_any_call(
        state_cls.return_value, server.group, group="raniz", gid=1000
    )


def test_provision_user_ensures_the_user() -> None:
    # given a fully resolved user, including extra groups
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=["wheel"],
    )

    # when provisioning that user
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provision_user("my-project", user)

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
    # given a list of packages to install on arch
    # when provisioning packages into a named container
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provision_packages("my-project", "arch", ["zsh", "python"])

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
    # given a list of packages to install on arch
    # when provisioning packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all") as connect_all,
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops") as run_ops,
    ):
        provision_packages("my-project", "arch", ["zsh"])

    # then the state is connected before operations are run
    connect_all.assert_called_once_with(state_cls.return_value)
    run_ops.assert_called_once_with(state_cls.return_value)


def test_provision_packages_enables_output_printing() -> None:
    # given a list of packages to install on arch
    # when provisioning packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        provision_packages("my-project", "arch", ["zsh"])

    # then the state is configured to print command output and input as it runs
    state = state_cls.return_value
    assert state.print_output is True
    assert state.print_input is True


def test_provision_packages_raises_for_an_unsupported_distribution() -> None:
    # given a distribution with no known package operation
    # when provisioning packages
    # then a clear error is raised
    with pytest.raises(ValueError, match="debian"):
        provision_packages("my-project", "debian", ["zsh"])


def test_remove_packages_removes_packages_via_the_distribution_operation() -> None:
    # given a list of packages no longer declared, to remove on arch
    # when removing packages from a named container
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        remove_packages("my-project", "arch", ["old-pkg"])

    # then the arch package operation is used to ensure the packages are absent
    add_op.assert_any_call(
        state_cls.return_value,
        pacman.packages,
        packages=["old-pkg"],
        present=False,
    )


def test_remove_packages_connects_before_running_operations() -> None:
    # given a list of packages to remove on arch
    # when removing packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all") as connect_all,
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops") as run_ops,
    ):
        remove_packages("my-project", "arch", ["old-pkg"])

    # then the state is connected before operations are run
    connect_all.assert_called_once_with(state_cls.return_value)
    run_ops.assert_called_once_with(state_cls.return_value)


def test_remove_packages_enables_output_printing() -> None:
    # given a list of packages to remove on arch
    # when removing packages
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops"),
    ):
        remove_packages("my-project", "arch", ["old-pkg"])

    # then the state is configured to print command output and input as it runs
    state = state_cls.return_value
    assert state.print_output is True
    assert state.print_input is True


def test_remove_packages_raises_for_an_unsupported_distribution() -> None:
    # given a distribution with no known package operation
    # when removing packages
    # then a clear error is raised
    with pytest.raises(ValueError, match="debian"):
        remove_packages("my-project", "debian", ["old-pkg"])


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


def test_provision_aur_builder_ensures_a_system_group_and_user() -> None:
    # given no existing aur builder provisioning
    # when provisioning the aur builder into a named container
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provision_aur_builder("my-project")

    # then a system group and user named "aur" are ensured, with a home
    # directory to build in and no login shell
    add_op.assert_any_call(
        state_cls.return_value, server.group, group="aur", system=True
    )
    add_op.assert_any_call(
        state_cls.return_value,
        server.user,
        user="aur",
        group="aur",
        system=True,
        shell="/usr/bin/nologin",
        create_home=True,
    )


def test_provision_aur_builder_installs_build_dependencies() -> None:
    # given no existing aur builder provisioning
    # when provisioning the aur builder
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provision_aur_builder("my-project")

    # then the packages needed to build from a PKGBUILD are ensured present
    add_op.assert_any_call(
        state_cls.return_value,
        pacman.packages,
        packages=["base-devel", "git"],
        update=True,
    )


def test_provision_aur_builder_writes_a_pacman_scoped_sudoers_dropin() -> None:
    # given no existing aur builder provisioning
    # when provisioning the aur builder
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all"),
        patch("ask.provision.add_op") as add_op,
        patch("ask.provision.run_ops"),
    ):
        provision_aur_builder("my-project")

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


def test_provision_aur_builder_connects_before_running_operations() -> None:
    # given no existing aur builder provisioning
    # when provisioning the aur builder
    with (
        patch("ask.provision.Inventory"),
        patch("ask.provision.State") as state_cls,
        patch("ask.provision.connect_all") as connect_all,
        patch("ask.provision.add_op"),
        patch("ask.provision.run_ops") as run_ops,
    ):
        provision_aur_builder("my-project")

    # then the state is connected before operations are run
    connect_all.assert_called_once_with(state_cls.return_value)
    run_ops.assert_called_once_with(state_cls.return_value)


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


def test_ensure_paru_does_nothing_when_already_installed() -> None:
    # given a container that already has paru installed
    with patch("ask.provision.incus.Container") as container_cls:
        container = container_cls.return_value
        container.run_command.return_value = _completed(0)

        # when ensuring paru is present
        ensure_paru("my-project")

    # then the container is targeted by name, only the presence check is
    # made, and nothing is built
    container_cls.assert_called_once_with("my-project")
    container.run_command.assert_called_once_with(["pacman", "-Qq", "paru"])
    container.exec_command.assert_not_called()


def test_ensure_paru_builds_it_when_missing_and_the_user_approves() -> None:
    # given a container without paru, and a user who approves the build after
    # reviewing the PKGBUILD
    with (
        patch("ask.provision.incus.Container") as container_cls,
        patch("builtins.input", return_value="y"),
    ):
        container = container_cls.return_value
        container.run_command.side_effect = [
            _completed(1),
            _completed(0, "1001\n"),
            _completed(0, "1001\n"),
        ]
        container.exec_command.return_value = 0

        # when ensuring paru is present
        ensure_paru("my-project")

    # then paru-bin is cloned, its PKGBUILD is shown, and it is built as the
    # aur builder user
    container.exec_command.assert_any_call(
        1001,
        1001,
        Path("/home/aur"),
        ["git", "clone", "https://aur.archlinux.org/paru-bin.git", "paru-bin"],
    )
    container.exec_command.assert_any_call(
        1001, 1001, Path("/home/aur/paru-bin"), ["cat", "PKGBUILD"]
    )
    container.exec_command.assert_any_call(
        1001,
        1001,
        Path("/home/aur/paru-bin"),
        ["makepkg", "-si", "--noconfirm"],
    )


def test_ensure_paru_raises_without_building_when_the_user_declines() -> None:
    # given a container without paru, and a user who declines after
    # reviewing the PKGBUILD
    with (
        patch("ask.provision.incus.Container") as container_cls,
        patch("builtins.input", return_value="n"),
    ):
        container = container_cls.return_value
        container.run_command.side_effect = [
            _completed(1),
            _completed(0, "1001\n"),
            _completed(0, "1001\n"),
        ]
        container.exec_command.return_value = 0

        # when ensuring paru is present
        # then a clear error is raised, and the package is never built
        with pytest.raises(RuntimeError, match="declined"):
            ensure_paru("my-project")

    build_calls = [
        c for c in container.exec_command.call_args_list if "makepkg" in c.args[3]
    ]
    assert build_calls == []


def test_provision_aur_packages_does_nothing_for_no_packages() -> None:
    # given no aur packages to install
    with (
        patch("ask.provision.provision_aur_builder") as builder,
        patch("ask.provision.ensure_paru") as paru,
        patch("ask.provision.incus.Container") as container_cls,
    ):
        # when provisioning aur packages
        provision_aur_packages("my-project", "arch", [])

    # then nothing is provisioned at all
    builder.assert_not_called()
    paru.assert_not_called()
    container_cls.assert_not_called()


def test_provision_aur_packages_raises_for_an_unsupported_distribution() -> None:
    # given a distribution AUR is not meaningful for
    # when provisioning aur packages
    # then a clear error is raised
    with pytest.raises(ValueError, match="debian"):
        provision_aur_packages("my-project", "debian", ["yay-bin"])


def test_provision_aur_packages_builds_the_builder_and_paru_then_installs() -> None:
    # given aur packages to install on arch
    with (
        patch("ask.provision.provision_aur_builder") as builder,
        patch("ask.provision.ensure_paru") as paru,
        patch("ask.provision.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.run_command.side_effect = [
            _completed(0, "1001\n"),
            _completed(0, "1001\n"),
        ]
        container.exec_command.return_value = 0

        # when provisioning aur packages
        provision_aur_packages("my-project", "arch", ["yay-bin", "some-other-pkg"])

    # then the builder user and paru are ensured, in that order, before
    # installing the declared packages as the aur builder user, interactively
    builder.assert_called_once_with("my-project")
    paru.assert_called_once_with("my-project")
    container_cls.assert_called_once_with("my-project")
    container.exec_command.assert_called_once_with(
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
    # given a resolved user and bind mounts both under and outside their home
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
        fix_bind_mount_ownership("my-project", bind_mounts, user)

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
    # given a resolved user and a bind mount under their home
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
        fix_bind_mount_ownership("my-project", bind_mounts, user)

    # then the state is configured to print command output and input as it runs
    state = state_cls.return_value
    assert state.print_output is True
    assert state.print_input is True


def test_fix_bind_mount_ownership_does_nothing_when_no_mounts_under_home() -> None:
    # given a resolved user and bind mounts entirely outside their home
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
        fix_bind_mount_ownership("my-project", bind_mounts, user)

    # then no inventory is even built, and no operations are run
    inventory_cls.assert_not_called()
    run_ops.assert_not_called()
