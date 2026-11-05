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
        raise ValueError(f"no known Incus image for distribution {distribution!r}") from None


def create_container(name: str, distribution: str, project_dir: Path) -> None:
    command = ["incus", "launch", image_for(distribution), name]
    for key, value in _COMMON_CONFIG.items():
        command += ["--config", f"{key}={value}"]
    command += [
        "--device",
        f"project,type=disk,source={project_dir},path={project_dir},shift=true",
    ]
    subprocess.run(command, check=True)
