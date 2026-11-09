import io
import shlex
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from pyinfra.api import Config as PyinfraConfig
from pyinfra.api import Inventory, State
from pyinfra.api.connect import connect_all
from pyinfra.api.exceptions import PyinfraError
from pyinfra.api.operation import add_op
from pyinfra.api.operations import run_ops
from pyinfra.api.output import set_echo
from pyinfra.operations import files, pacman, server

from ask import incus
from ask.errors import AskError
from ask.user import ResolvedUser


class ProvisioningError(AskError):
    pass


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


_AUR_PREFIX = "aur:"


def split_aur_packages(packages: list[str]) -> tuple[list[str], list[str]]:
    official = [p for p in packages if not p.startswith(_AUR_PREFIX)]
    aur = [p.removeprefix(_AUR_PREFIX) for p in packages if p.startswith(_AUR_PREFIX)]
    return official, aur


def _ancestors_under_home(path: Path, home: Path) -> list[Path]:
    if path == home or home not in path.parents:
        return []
    ancestors = []
    current = path.parent
    while current != home:
        ancestors.append(current)
        current = current.parent
    return ancestors


@dataclass(frozen=True)
class Provisioner:
    container: incus.Container

    @contextmanager
    def session(self) -> Iterator[State]:
        inventory = Inventory(([f"@incus/{self.container.name}"], {}))
        state = State(inventory, PyinfraConfig())
        state.print_output = True
        state.print_input = True
        try:
            connect_all(state)
            yield state
            run_ops(state)
        except PyinfraError as error:
            raise ProvisioningError(
                f"provisioning container {self.container.name!r} failed: {error}"
            ) from error

    def provision_user(self, user: ResolvedUser) -> None:
        with self.session() as state:
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

    def provision_packages(self, distribution: str, packages: list[str]) -> None:
        operation = _package_operation_for(distribution)
        with self.session() as state:
            add_op(state, operation, packages=packages, update=True, upgrade=True)

    def remove_packages(self, distribution: str, packages: list[str]) -> None:
        operation = _package_operation_for(distribution)
        with self.session() as state:
            add_op(state, operation, packages=packages, present=False)

    def fix_bind_mount_ownership(
        self, bind_mounts: list[Path], user: ResolvedUser
    ) -> None:
        home = Path(f"/home/{user.name}")
        ancestors: set[Path] = set()
        for mount in bind_mounts:
            ancestors.update(_ancestors_under_home(mount, home))

        if not ancestors:
            return

        with self.session() as state:
            for ancestor in sorted(ancestors):
                add_op(
                    state,
                    files.directory,
                    path=str(ancestor),
                    user=user.name,
                    group=user.group_name,
                )


_AUR_BUILD_USER = "aur"
_AUR_BUILD_ID = 900
_AUR_SUDOERS_PATH = "/etc/sudoers.d/ask-aur"
_AUR_BUILD_HOME = Path(f"/home/{_AUR_BUILD_USER}")
_PARU_CACHE_DIR = _AUR_BUILD_HOME / ".cache" / "paru"
_PARU_CACHE_POOL = "default"
_PARU_CACHE_VOLUME = "ask-paru"
_PARU_CACHE_DEVICE = "paru-cache"
_PARU_BIN_REPO = "https://aur.archlinux.org/paru-bin.git"
_PARU_BIN_CLONE = _PARU_CACHE_DIR / "clone" / "paru-bin"
_AUR_SEEN_REF = "AUR_SEEN"


@dataclass(frozen=True)
class AurBuilder:
    container: incus.Container

    def provision_builder(self) -> None:
        with Provisioner(self.container).session() as state:
            add_op(
                state,
                server.group,
                group=_AUR_BUILD_USER,
                gid=_AUR_BUILD_ID,
                system=True,
            )
            add_op(
                state,
                server.user,
                user=_AUR_BUILD_USER,
                uid=_AUR_BUILD_ID,
                group=_AUR_BUILD_USER,
                system=True,
                shell="/usr/bin/nologin",
                create_home=True,
            )
            add_op(state, pacman.packages, packages=["base-devel", "git"], update=True)
            add_op(
                state,
                files.put,
                src=io.StringIO(
                    f"{_AUR_BUILD_USER} ALL=(root) NOPASSWD: /usr/bin/pacman *\n"
                ),
                dest=_AUR_SUDOERS_PATH,
                user="root",
                group="root",
                mode="440",
            )

    def share_paru_cache(self) -> None:
        incus.ensure_storage_volume(_PARU_CACHE_POOL, _PARU_CACHE_VOLUME)
        self.container.attach_volume(
            _PARU_CACHE_POOL, _PARU_CACHE_VOLUME, _PARU_CACHE_DEVICE, _PARU_CACHE_DIR
        )
        with Provisioner(self.container).session() as state:
            for directory in (_PARU_CACHE_DIR.parent, _PARU_CACHE_DIR):
                add_op(
                    state,
                    files.directory,
                    path=str(directory),
                    user=_AUR_BUILD_USER,
                    group=_AUR_BUILD_USER,
                )

    def _builder_ids(self) -> tuple[int, int]:
        uid = int(self.container.run_command(["id", "-u", _AUR_BUILD_USER]).stdout)
        gid = int(self.container.run_command(["id", "-g", _AUR_BUILD_USER]).stdout)
        return uid, gid

    def _run_as_builder(
        self, uid: int, gid: int, cwd: Path, command: list[str]
    ) -> None:
        returncode = self.container.exec_command(uid, gid, cwd, command)
        if returncode != 0:
            raise ProvisioningError(
                f"`{shlex.join(command)}` failed in container "
                f"{self.container.name!r} with exit status {returncode}"
            )

    def _builder_git_ref(self, ref: str) -> str | None:
        result = self.container.run_command(
            [
                "runuser",
                "-u",
                _AUR_BUILD_USER,
                "--",
                "git",
                "-C",
                str(_PARU_BIN_CLONE),
                "rev-parse",
                "--verify",
                "--quiet",
                ref,
            ]
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _fetch_paru_bin(self, uid: int, gid: int) -> None:
        clone_exists = self.container.run_command(
            ["test", "-d", str(_PARU_BIN_CLONE / ".git")]
        ).returncode
        if clone_exists == 0:
            self._run_as_builder(
                uid, gid, _PARU_BIN_CLONE, ["git", "pull", "--ff-only"]
            )
        else:
            self._run_as_builder(
                uid,
                gid,
                _AUR_BUILD_HOME,
                ["git", "clone", _PARU_BIN_REPO, str(_PARU_BIN_CLONE)],
            )

    def _review_paru_bin(self, uid: int, gid: int) -> None:
        seen = self._builder_git_ref(_AUR_SEEN_REF)
        if seen is not None and seen == self._builder_git_ref("HEAD"):
            return

        if seen is None:
            review = ["cat", "PKGBUILD"]
        else:
            review = ["git", "--no-pager", "diff", _AUR_SEEN_REF, "HEAD"]
        self._run_as_builder(uid, gid, _PARU_BIN_CLONE, review)

        answer = input("Proceed with building paru-bin from the PKGBUILD above? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            raise ProvisioningError(
                "paru build was declined; cannot install AUR packages"
            )
        self._run_as_builder(
            uid, gid, _PARU_BIN_CLONE, ["git", "update-ref", _AUR_SEEN_REF, "HEAD"]
        )

    def ensure_paru(self) -> None:
        already_installed = self.container.run_command(
            ["pacman", "-Qq", "paru"]
        ).returncode
        if already_installed == 0:
            return

        uid, gid = self._builder_ids()
        self._fetch_paru_bin(uid, gid)
        self._review_paru_bin(uid, gid)
        self._run_as_builder(
            uid, gid, _PARU_BIN_CLONE, ["makepkg", "-si", "--noconfirm"]
        )

    def install_packages(self, distribution: str, packages: list[str]) -> None:
        if not packages:
            return
        if distribution != "arch":
            raise ValueError(f"AUR packages are not supported on {distribution!r}")

        self.provision_builder()
        self.share_paru_cache()
        self.ensure_paru()

        uid, gid = self._builder_ids()
        self._run_as_builder(
            uid, gid, _AUR_BUILD_HOME, ["paru", "-S", "--needed", *packages]
        )
