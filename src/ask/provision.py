import io
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

from ask import incus
from ask.config import ResolvedUser, ancestors_under_home


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

    add_op(state, operation, packages=packages, update=True, upgrade=True)

    run_ops(state)


def remove_packages(
    container_name: str, distribution: str, packages: list[str]
) -> None:
    operation = _package_operation_for(distribution)
    state = _build_state(container_name)
    connect_all(state)

    add_op(state, operation, packages=packages, present=False)

    run_ops(state)


_AUR_PREFIX = "aur:"


def split_aur_packages(packages: list[str]) -> tuple[list[str], list[str]]:
    official = [p for p in packages if not p.startswith(_AUR_PREFIX)]
    aur = [p.removeprefix(_AUR_PREFIX) for p in packages if p.startswith(_AUR_PREFIX)]
    return official, aur


_AUR_BUILD_USER = "aur"
_AUR_SUDOERS_PATH = "/etc/sudoers.d/ask-aur"


def provision_aur_builder(container_name: str) -> None:
    state = _build_state(container_name)
    connect_all(state)

    add_op(state, server.group, group=_AUR_BUILD_USER, system=True)
    add_op(
        state,
        server.user,
        user=_AUR_BUILD_USER,
        group=_AUR_BUILD_USER,
        system=True,
        shell="/usr/bin/nologin",
        create_home=True,
    )
    add_op(state, pacman.packages, packages=["base-devel", "git"], update=True)
    add_op(
        state,
        files.put,
        src=io.StringIO(f"{_AUR_BUILD_USER} ALL=(root) NOPASSWD: /usr/bin/pacman *\n"),
        dest=_AUR_SUDOERS_PATH,
        user="root",
        group="root",
        mode="440",
    )

    run_ops(state)


_AUR_BUILD_HOME = Path(f"/home/{_AUR_BUILD_USER}")
_PARU_BIN_REPO = "https://aur.archlinux.org/paru-bin.git"
_PARU_BIN_DIR = "paru-bin"


def _aur_builder_ids(container_name: str) -> tuple[int, int]:
    uid = int(incus.run_command(container_name, ["id", "-u", _AUR_BUILD_USER]).stdout)
    gid = int(incus.run_command(container_name, ["id", "-g", _AUR_BUILD_USER]).stdout)
    return uid, gid


def ensure_paru(container_name: str) -> None:
    already_installed = incus.run_command(
        container_name, ["pacman", "-Qq", "paru"]
    ).returncode
    if already_installed == 0:
        return

    uid, gid = _aur_builder_ids(container_name)
    build_dir = _AUR_BUILD_HOME / _PARU_BIN_DIR

    incus.exec_command(
        container_name,
        uid,
        gid,
        _AUR_BUILD_HOME,
        ["git", "clone", _PARU_BIN_REPO, _PARU_BIN_DIR],
    )
    incus.exec_command(container_name, uid, gid, build_dir, ["cat", "PKGBUILD"])

    answer = input("Proceed with building paru-bin from the PKGBUILD above? [y/N] ")
    if answer.strip().lower() not in ("y", "yes"):
        raise RuntimeError("paru build was declined; cannot install AUR packages")

    incus.exec_command(
        container_name, uid, gid, build_dir, ["makepkg", "-si", "--noconfirm"]
    )


def provision_aur_packages(
    container_name: str, distribution: str, packages: list[str]
) -> None:
    if not packages:
        return
    if distribution != "arch":
        raise ValueError(f"AUR packages are not supported on {distribution!r}")

    provision_aur_builder(container_name)
    ensure_paru(container_name)

    uid, gid = _aur_builder_ids(container_name)
    incus.exec_command(
        container_name, uid, gid, _AUR_BUILD_HOME, ["paru", "-S", "--needed", *packages]
    )


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
