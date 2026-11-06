from pathlib import Path
from unittest.mock import ANY, patch

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest
from pyinfra.api.output import echo
from pyinfra.operations import files, pacman, server

from ask.config import ResolvedUser
from ask.provision import (
    ancestors_under_home,
    fix_bind_mount_ownership,
    provision_packages,
    provision_user,
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


def test_ancestors_under_home_returns_the_immediate_parent() -> None:
    # given a bind-mounted path one level under home
    # when finding its ancestors under home
    ancestors = ancestors_under_home(Path("/home/raniz/src/ask"), Path("/home/raniz"))

    # then only its immediate parent is returned
    assert ancestors == [Path("/home/raniz/src")]


def test_ancestors_under_home_returns_every_level_innermost_first() -> None:
    # given a bind-mounted path nested several levels under home
    # when finding its ancestors under home
    ancestors = ancestors_under_home(
        Path("/home/raniz/.local/share/foo"), Path("/home/raniz")
    )

    # then every intermediate directory is returned, innermost first, excluding
    # home itself
    assert ancestors == [Path("/home/raniz/.local/share"), Path("/home/raniz/.local")]


def test_ancestors_under_home_returns_none_when_path_is_home() -> None:
    # given a path that is the home directory itself
    # when finding its ancestors under home
    ancestors = ancestors_under_home(Path("/home/raniz"), Path("/home/raniz"))

    # then there are no ancestors to fix
    assert ancestors == []


def test_ancestors_under_home_returns_none_when_path_is_outside_home() -> None:
    # given a path that doesn't live under home at all
    # when finding its ancestors under home
    ancestors = ancestors_under_home(Path("/opt/foo"), Path("/home/raniz"))

    # then nothing is returned, since ownership outside home isn't ours to fix
    assert ancestors == []


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
