from pyinfra.api import Config as PyinfraConfig
from pyinfra.api import Inventory, State
from pyinfra.api.connect import connect_all
from pyinfra.api.operation import add_op
from pyinfra.api.operations import run_ops
from pyinfra.operations import server

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
