from unittest.mock import ANY, patch

from pyinfra.operations import server

from ask.config import ResolvedUser
from ask.provision import provision_user


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
