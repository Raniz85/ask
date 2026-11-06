import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pyinfra.api import Config as PyinfraConfig
from pyinfra.api import Inventory, State
from pyinfra.api.connect import connect_all
from pyinfra.api.operation import add_op
from pyinfra.api.operations import run_ops
from pyinfra.api.output import set_echo
from pyinfra.operations import files, pacman, server

from ask.config import ResolvedUser


def _echo(message: object = "", *, err: bool = False, **_kwargs: Any) -> None:
    print(message, file=sys.stderr if err else sys.stdout)


set_echo(_echo)

_PACKAGE_OPERATIONS = {
    "arch": pacman.packages,
}


def _package_operation_for(distribution: str) -> Callable[..., Any]:
    try:
        return _PACKAGE_OPERATIONS[distribution]
    except KeyError:
        raise ValueError(
            f"no known package operation for distribution {distribution!r}"
        ) from None


def _build_state(container_name: str) -> State:
    inventory = Inventory(([f"@incus/{container_name}"], {}))
    state = State(inventory, PyinfraConfig())
    state.print_output = True
    state.print_input = True
    return state


def provision_user(container_name: str, user: ResolvedUser) -> None:
    state = _build_state(container_name)
    connect_all(state)

    add_op(state, server.group, group=user.group_name, gid=user.gid)
    add_op(
        state,
        server.user,
        user=user.name,
        uid=user.uid,
        group=user.group_name,
        groups=user.extra_groups,
        shell=f"/bin/{user.shell}",
        create_home=True,
    )

    run_ops(state)


def provision_packages(
    container_name: str, distribution: str, packages: list[str]
) -> None:
    operation = _package_operation_for(distribution)
    state = _build_state(container_name)
    connect_all(state)

    add_op(state, operation, packages=packages, update=True)

    run_ops(state)


def ancestors_under_home(path: Path, home: Path) -> list[Path]:
    if path == home or home not in path.parents:
        return []
    ancestors = []
    current = path.parent
    while current != home:
        ancestors.append(current)
        current = current.parent
    return ancestors


def fix_bind_mount_ownership(
    container_name: str, bind_mounts: list[Path], user: ResolvedUser
) -> None:
    home = Path(f"/home/{user.name}")
    ancestors: set[Path] = set()
    for mount in bind_mounts:
        ancestors.update(ancestors_under_home(mount, home))

    if not ancestors:
        return

    state = _build_state(container_name)
    connect_all(state)

    for ancestor in sorted(ancestors):
        add_op(
            state,
            files.directory,
            path=str(ancestor),
            user=user.name,
            group=user.group_name,
        )

    run_ops(state)
