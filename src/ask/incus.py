import json
import logging
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ask.errors import AskError

logger = logging.getLogger(__name__)

_IMAGE_ALIASES = {
    "arch": "images:archlinux/current",
}

_DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

_COMMON_CONFIG = {
    "security.nesting": "true",
    "security.privileged": "false",
}

_MANAGED_PACKAGES_CONFIG_KEY = "user.ask.packages"
_GUI_SESSIONS_CONFIG_KEY = "user.ask.gui_sessions"
_CONVERGED_VERSION_CONFIG_KEY = "user.ask.converged.version"
_CONVERGED_HASH_CONFIG_KEY = "user.ask.converged.hash"
_CONVERGED_CONFIGURATION_CONFIG_KEY = "user.ask.converged.configuration"
_CONVERGED_AT_CONFIG_KEY = "user.ask.converged.at"
# Public because the in-instance idle watcher reads the same key through the
# in-instance Incus socket; see ask.idle.
INVOCATION_AT_CONFIG_KEY = "user.ask.invocation.at"


def _trusted_config_key(tool_manager: str) -> str:
    return f"user.ask.{tool_manager}.trusted"


class IncusError(AskError):
    pass


class ContainerNotFoundError(AskError):
    pass


class ContainerExistsError(AskError):
    pass


def _failure_message(error: subprocess.CalledProcessError) -> str:
    message = f"`{shlex.join(error.cmd)}` failed with exit status {error.returncode}"
    if error.stderr:
        return f"{message}: {error.stderr.strip()}"
    return f"{message}."


def _incus(
    command: list[str], capture: bool = False
) -> subprocess.CompletedProcess[str]:
    logger.debug("executing %s", shlex.join(command))
    try:
        if capture:
            return subprocess.run(command, check=True, capture_output=True, text=True)
        subprocess.run(command, check=True)
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")
    except FileNotFoundError as error:
        raise IncusError(
            "The incus command was not found. Is Incus installed and on PATH?"
        ) from error
    except subprocess.CalledProcessError as error:
        raise IncusError(_failure_message(error)) from error


def known_distributions() -> list[str]:
    return sorted(_IMAGE_ALIASES)


def image_for(distribution: str) -> str:
    try:
        return _IMAGE_ALIASES[distribution]
    except KeyError:
        raise ValueError(
            f"no known Incus image for distribution {distribution!r}"
        ) from None


def device_name_for(path: Path, prefix: str = "bind") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", str(path))
    return f"{prefix}-{slug}"


@dataclass(frozen=True)
class Mount:
    host_path: Path
    container_path: Path
    readonly: bool = False


@dataclass(frozen=True)
class Fingerprint:
    version: str
    config_hash: str


@dataclass(frozen=True)
class ConvergedState:
    fingerprint: Fingerprint
    configuration: str
    at: datetime


@dataclass(frozen=True)
class InstanceSnapshot:
    status: str
    config: dict[str, str]

    def is_running(self) -> bool:
        return self.status == "Running"

    def converged_fingerprint(self) -> Fingerprint | None:
        version = self.config.get(_CONVERGED_VERSION_CONFIG_KEY)
        config_hash = self.config.get(_CONVERGED_HASH_CONFIG_KEY)
        if not version or not config_hash:
            return None
        return Fingerprint(version=version, config_hash=config_hash)


def _diff_devices(
    existing: set[str], desired: dict[str, Mount]
) -> tuple[set[str], dict[str, Mount]]:
    to_remove = existing - desired.keys()
    to_add = {
        device_name: mount
        for device_name, mount in desired.items()
        if device_name not in existing
    }
    return to_remove, to_add


def stale_packages(managed: list[str], desired: list[str]) -> list[str]:
    return sorted(set(managed) - set(desired))


def _add_disk_device(container_name: str, device_name: str, mount: Mount) -> None:
    command = [
        "incus",
        "config",
        "device",
        "add",
        container_name,
        device_name,
        "disk",
        f"source={mount.host_path}",
        f"path={mount.container_path}",
        "shift=true",
    ]
    if mount.readonly:
        command.append("readonly=true")
    _incus(command)


def ensure_storage_volume(pool: str, volume: str) -> None:
    result = _incus(
        [
            "incus",
            "storage",
            "volume",
            "list",
            pool,
            "type=custom",
            "--format",
            "csv",
            "--columns",
            "n",
        ],
        capture=True,
    )
    if volume not in result.stdout.splitlines():
        _incus(["incus", "storage", "volume", "create", pool, volume])


def _remove_device(container_name: str, device_name: str) -> None:
    _incus(
        ["incus", "config", "device", "remove", container_name, device_name],
    )


@dataclass(frozen=True)
class Container:
    name: str

    @staticmethod
    def create(name: str, distribution: str) -> "Container":
        command = ["incus", "launch", image_for(distribution), name]
        for key, value in _COMMON_CONFIG.items():
            command += ["--config", f"{key}={value}"]
        _incus(command)
        return Container(name)

    def snapshot(self) -> InstanceSnapshot | None:
        result = _incus(["incus", "list", self.name, "--format", "json"], capture=True)
        for instance in json.loads(result.stdout):
            if instance["name"] == self.name:
                return InstanceSnapshot(
                    status=instance["status"], config=instance["config"]
                )
        return None

    def start(self) -> None:
        _incus(["incus", "start", self.name])

    def restart(self) -> None:
        _incus(["incus", "restart", self.name])

    def stop(self) -> None:
        _incus(["incus", "stop", self.name])

    def delete(self) -> None:
        _incus(["incus", "delete", self.name])

    def rename(self, new_name: str) -> None:
        _incus(["incus", "rename", self.name, new_name])

    def move_bind_mount(self, old_path: Path, new_path: Path) -> None:
        old_device = device_name_for(old_path)
        if old_device in self._device_names():
            _remove_device(self.name, old_device)
        _add_disk_device(
            self.name,
            device_name_for(new_path),
            Mount(host_path=new_path, container_path=new_path),
        )

    def run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        full_command = ["incus", "exec", self.name, "--", *command]
        logger.debug("executing %s", shlex.join(full_command))
        return subprocess.run(
            full_command,
            check=False,
            capture_output=True,
            text=True,
        )

    def exec_command(
        self,
        uid: int,
        gid: int,
        cwd: Path,
        command: list[str],
        env: dict[str, str] | None = None,
    ) -> int:
        env_args = [
            arg
            for key, value in (env or {}).items()
            for arg in ("--env", f"{key}={value}")
        ]
        full_command = [
            "incus",
            "exec",
            self.name,
            "--user",
            str(uid),
            "--group",
            str(gid),
            "--cwd",
            str(cwd),
            *env_args,
            "--",
            *command,
        ]
        logger.debug("executing %s", shlex.join(full_command))
        result = subprocess.run(
            full_command,
            check=False,
        )
        return result.returncode

    def _device_names(self) -> set[str]:
        result = _incus(
            ["incus", "config", "device", "list", self.name],
            capture=True,
        )
        return set(result.stdout.splitlines())

    def _bind_devices(self) -> set[str]:
        return {d for d in self._device_names() if d.startswith("bind-")}

    def get_managed_packages(self) -> list[str]:
        result = _incus(
            ["incus", "config", "get", self.name, _MANAGED_PACKAGES_CONFIG_KEY],
            capture=True,
        )
        value = result.stdout.strip()
        return value.split(",") if value else []

    def set_managed_packages(self, packages: list[str]) -> None:
        _incus(
            [
                "incus",
                "config",
                "set",
                self.name,
                f"{_MANAGED_PACKAGES_CONFIG_KEY}={','.join(packages)}",
            ],
        )

    def set_converged_state(self, state: ConvergedState) -> None:
        _incus(
            [
                "incus",
                "config",
                "set",
                self.name,
                f"{_CONVERGED_VERSION_CONFIG_KEY}={state.fingerprint.version}",
                f"{_CONVERGED_HASH_CONFIG_KEY}={state.fingerprint.config_hash}",
                f"{_CONVERGED_CONFIGURATION_CONFIG_KEY}={state.configuration}",
                f"{_CONVERGED_AT_CONFIG_KEY}={state.at.isoformat()}",
            ],
        )

    def set_invocation_at(self, at: datetime) -> None:
        _incus(
            [
                "incus",
                "config",
                "set",
                self.name,
                f"{INVOCATION_AT_CONFIG_KEY}={at.isoformat()}",
            ],
        )

    def get_trusted_config_digest(self, tool_manager: str) -> str | None:
        result = _incus(
            ["incus", "config", "get", self.name, _trusted_config_key(tool_manager)],
            capture=True,
        )
        return result.stdout.strip() or None

    def set_trusted_config_digest(self, tool_manager: str, digest: str) -> None:
        _incus(
            [
                "incus",
                "config",
                "set",
                self.name,
                f"{_trusted_config_key(tool_manager)}={digest}",
            ],
        )

    def set_path_prefix(self, entries: list[Path]) -> None:
        path = ":".join([*map(str, entries), _DEFAULT_PATH])
        _incus(["incus", "config", "set", self.name, f"environment.PATH={path}"])

    def get_gui_session_count(self) -> int:
        result = _incus(
            ["incus", "config", "get", self.name, _GUI_SESSIONS_CONFIG_KEY],
            capture=True,
        )
        value = result.stdout.strip()
        return int(value) if value else 0

    def set_gui_session_count(self, count: int) -> None:
        _incus(
            [
                "incus",
                "config",
                "set",
                self.name,
                f"{_GUI_SESSIONS_CONFIG_KEY}={count}",
            ],
        )

    def add_gui_device(self, mount: Mount) -> None:
        device_name = device_name_for(mount.container_path, prefix="gui")
        _add_disk_device(self.name, device_name, mount)

    def remove_gui_device(self, mount: Mount) -> None:
        device_name = device_name_for(mount.container_path, prefix="gui")
        _remove_device(self.name, device_name)

    def attach_volume(
        self, pool: str, volume: str, device_name: str, path: Path
    ) -> None:
        if device_name in self._device_names():
            return
        _incus(
            [
                "incus",
                "storage",
                "volume",
                "attach",
                pool,
                volume,
                self.name,
                device_name,
                str(path),
            ]
        )

    def converge(self, mounts: list[Mount]) -> None:
        desired = {device_name_for(mount.container_path): mount for mount in mounts}
        existing = self._bind_devices()
        to_remove, to_add = _diff_devices(existing, desired)

        for device_name in to_remove:
            _remove_device(self.name, device_name)

        for device_name, mount in to_add.items():
            _add_disk_device(self.name, device_name, mount)
