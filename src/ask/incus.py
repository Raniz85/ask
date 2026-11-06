import re
import subprocess
from pathlib import Path

_IMAGE_ALIASES = {
    "arch": "images:archlinux/current",
}

_COMMON_CONFIG = {
    "security.nesting": "true",
    "security.privileged": "false",
}


def image_for(distribution: str) -> str:
    try:
        return _IMAGE_ALIASES[distribution]
    except KeyError:
        raise ValueError(
            f"no known Incus image for distribution {distribution!r}"
        ) from None


def create_container(name: str, distribution: str) -> None:
    command = ["incus", "launch", image_for(distribution), name]
    for key, value in _COMMON_CONFIG.items():
        command += ["--config", f"{key}={value}"]
    subprocess.run(command, check=True)


def exec_command(name: str, uid: int, gid: int, cwd: Path, command: list[str]) -> int:
    result = subprocess.run(
        [
            "incus",
            "exec",
            name,
            "--user",
            str(uid),
            "--group",
            str(gid),
            "--cwd",
            str(cwd),
            "--",
            *command,
        ]
    )
    return result.returncode


def device_name_for(path: Path) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", str(path))
    return f"bind-{slug}"


def _device_names(name: str) -> set[str]:
    result = subprocess.run(
        ["incus", "config", "device", "list", name],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def _bind_devices(name: str) -> set[str]:
    return {d for d in _device_names(name) if d.startswith("bind-")}


_SHELL_RC_DEVICE = "shellrc"


def converge_shell_rc(name: str, host_path: Path, container_path: Path) -> None:
    if _SHELL_RC_DEVICE in _device_names(name):
        subprocess.run(
            ["incus", "config", "device", "remove", name, _SHELL_RC_DEVICE],
            check=True,
        )

    subprocess.run(
        [
            "incus",
            "config",
            "device",
            "add",
            name,
            _SHELL_RC_DEVICE,
            "disk",
            f"source={host_path}",
            f"path={container_path}",
            "readonly=true",
        ],
        check=True,
    )


_MANAGED_PACKAGES_CONFIG_KEY = "user.ask.packages"


def get_managed_packages(name: str) -> list[str]:
    result = subprocess.run(
        ["incus", "config", "get", name, _MANAGED_PACKAGES_CONFIG_KEY],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    return value.split(",") if value else []


def set_managed_packages(name: str, packages: list[str]) -> None:
    subprocess.run(
        [
            "incus",
            "config",
            "set",
            name,
            _MANAGED_PACKAGES_CONFIG_KEY,
            ",".join(packages),
        ],
        check=True,
    )


def converge(name: str, bind_mounts: list[Path]) -> None:
    desired = {device_name_for(path): path for path in bind_mounts}
    existing = _bind_devices(name)

    for device_name in existing - desired.keys():
        subprocess.run(
            ["incus", "config", "device", "remove", name, device_name], check=True
        )

    for device_name, path in desired.items():
        if device_name not in existing:
            subprocess.run(
                [
                    "incus",
                    "config",
                    "device",
                    "add",
                    name,
                    device_name,
                    "disk",
                    f"source={path}",
                    f"path={path}",
                    "shift=true",
                ],
                check=True,
            )
