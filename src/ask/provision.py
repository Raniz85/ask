import io
import logging
import shlex
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyinfra.api import Config as PyinfraConfig
from pyinfra.api import Inventory, State
from pyinfra.api.connect import connect_all
from pyinfra.api.exceptions import PyinfraError
from pyinfra.api.operation import add_op
from pyinfra.api.operations import run_ops
from pyinfra.api.output import set_echo
from pyinfra.operations import apt, files, pacman, server, systemd

from ask import env, idle, incus
from ask.errors import AskError
from ask.tool_manager import config_digest
from ask.user import ResolvedUser, home_env

logger = logging.getLogger(__name__)


class ProvisioningError(AskError):
    pass


def _echo(message: object = "", *, err: bool = False, **_kwargs: Any) -> None:
    print(message, file=sys.stderr if err else sys.stdout)


set_echo(_echo)

_PACKAGE_OPERATIONS: dict[str, Callable[..., Any]] = {
    "arch": pacman.packages,
    "debian": apt.packages,
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
        logger.debug(
            "opening provisioning session for container %r", self.container.name
        )
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
                f"Provisioning container {self.container.name!r} failed: {error}"
            ) from error

    def provision_user(self, user: ResolvedUser) -> None:
        logger.debug("provisioning user %r (uid %s)", user.name, user.uid)
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
        logger.debug("installing packages on %s: %s", distribution, ", ".join(packages))
        operation = _package_operation_for(distribution)
        with self.session() as state:
            add_op(state, operation, packages=packages, update=True, upgrade=True)

    def remove_packages(self, distribution: str, packages: list[str]) -> None:
        logger.debug("removing packages from %s: %s", distribution, ", ".join(packages))
        operation = _package_operation_for(distribution)
        with self.session() as state:
            add_op(state, operation, packages=packages, present=False)

    def provision_pi_extensions(
        self, user: ResolvedUser, extensions: list[str]
    ) -> None:
        if not extensions:
            return
        home = Path(f"/home/{user.name}")
        for extension in extensions:
            _run_checked(
                self.container,
                user.uid,
                user.gid,
                home,
                ["pi", "install", extension],
                env=home_env(user),
            )

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

    def provision_services(self, services: dict[str, str]) -> None:
        logger.debug("provisioning services: %s", services)
        with self.session() as state:
            for service, state_desired in services.items():
                if state_desired == "enabled":
                    add_op(
                        state,
                        systemd.service,
                        service=service,
                        enabled=True,
                        running=True,
                    )
                elif state_desired == "disabled":
                    add_op(
                        state,
                        systemd.service,
                        service=service,
                        enabled=False,
                        running=False,
                    )
                elif state_desired == "masked":
                    add_op(
                        state,
                        systemd.service,
                        service=service,
                        masked=True,
                        running=False,
                    )

    def provision_instance_env(self, variables: dict[str, str]) -> None:
        logger.debug(
            "provisioning instance environment variables: %s", sorted(variables)
        )
        with self.session() as state:
            add_op(
                state,
                files.put,
                src=io.StringIO(env.profile_script(variables)),
                dest=str(env.PROFILE_PATH),
                user="root",
                group="root",
                mode="644",
            )

    def provision_idle_shutdown(self, distribution: str, user: ResolvedUser) -> None:
        logger.debug("provisioning idle shutdown for user %r", user.name)
        operation = _package_operation_for(distribution)
        with self.session() as state:
            add_op(state, operation, packages=idle.WATCH_PACKAGES)
            add_op(
                state,
                files.put,
                src=io.StringIO(idle.shutdown_script(user)),
                dest=str(idle.SCRIPT_PATH),
                user="root",
                group="root",
                mode="755",
            )
            add_op(
                state,
                files.put,
                src=io.StringIO(idle.service_unit()),
                dest=str(idle.SERVICE_UNIT_PATH),
                user="root",
                group="root",
                mode="644",
            )
            add_op(
                state,
                files.put,
                src=io.StringIO(idle.timer_unit()),
                dest=str(idle.TIMER_UNIT_PATH),
                user="root",
                group="root",
                mode="644",
            )
            add_op(state, systemd.daemon_reload)
            add_op(
                state,
                systemd.service,
                service=idle.TIMER_NAME,
                enabled=True,
                running=True,
            )


def _run_checked(
    container: incus.Container,
    uid: int,
    gid: int,
    cwd: Path,
    command: list[str],
    env: dict[str, str] | None = None,
) -> None:
    if env:
        returncode = container.exec_command(uid, gid, cwd, command, env=env)
    else:
        returncode = container.exec_command(uid, gid, cwd, command)
    if returncode != 0:
        raise ProvisioningError(
            f"`{shlex.join(command)}` failed in container "
            f"{container.name!r} with exit status {returncode}."
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
        _run_checked(self.container, uid, gid, cwd, command)

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
                "The paru build was declined. Cannot install AUR packages."
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
        logger.debug("installing AUR packages: %s", ", ".join(packages))

        self.provision_builder()
        self.share_paru_cache()
        self.ensure_paru()

        uid, gid = self._builder_ids()
        self._run_as_builder(
            uid, gid, _AUR_BUILD_HOME, ["paru", "-S", "--needed", *packages]
        )


_MISE = "mise"


@dataclass(frozen=True)
class MiseProvisioner:
    container: incus.Container

    def trust(
        self, project_dir: Path, user: ResolvedUser, config_files: list[Path]
    ) -> None:
        digest = config_digest(project_dir, config_files)
        if self.container.get_trusted_config_digest(_MISE) == digest:
            return
        if not sys.stdin.isatty():
            raise ProvisioningError(
                "The mise config has not been reviewed. "
                "Run `ask converge` from a terminal to review it."
            )

        for config_file in config_files:
            print(f"==> {config_file} <==")
            print((project_dir / config_file).read_text())
        answer = input("Trust the mise config above and install its tools? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            raise ProvisioningError(
                "The mise config was declined. Cannot install its tools."
            )

        for config_file in config_files:
            _run_checked(
                self.container,
                user.uid,
                user.gid,
                project_dir,
                ["mise", "trust", str(project_dir / config_file)],
                env=home_env(user),
            )
        self.container.set_trusted_config_digest(_MISE, digest)

    def install(self, project_dir: Path, user: ResolvedUser) -> None:
        _run_checked(
            self.container,
            user.uid,
            user.gid,
            project_dir,
            ["mise", "install"],
            env=home_env(user),
        )
