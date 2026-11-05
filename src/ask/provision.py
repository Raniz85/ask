from pathlib import Path

from pyinfra.api import Config as PyinfraConfig
from pyinfra.api import Inventory, State
from pyinfra.api.connect import connect_all
from pyinfra.api.operation import add_op
from pyinfra.api.operations import run_ops
from pyinfra.operations import files, server

from ask.config import ResolvedUser


def provision_user(container_name: str, user: ResolvedUser) -> None:
    inventory = Inventory(([f"@incus/{container_name}"], {}))
    state = State(inventory, PyinfraConfig())
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

    inventory = Inventory(([f"@incus/{container_name}"], {}))
    state = State(inventory, PyinfraConfig())
    connect_all(state)

    for ancestor in sorted(ancestors):
        add_op(state, files.directory, path=str(ancestor), user=user.name, group=user.group_name)

    run_ops(state)
