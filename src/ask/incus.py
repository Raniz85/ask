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


def device_name_for(path: Path) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", str(path))
    return f"bind-{slug}"


def _bind_devices(name: str) -> set[str]:
    result = subprocess.run(
        ["incus", "config", "device", "list", name],
        check=True,
        capture_output=True,
        text=True,
    )
    return {d for d in result.stdout.splitlines() if d.startswith("bind-")}


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
