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


def create_container(
    name: str, distribution: str, project_dir: Path, bind_mounts: list[Path] | None = None
) -> None:
    command = ["incus", "launch", image_for(distribution), name]
    for key, value in _COMMON_CONFIG.items():
        command += ["--config", f"{key}={value}"]
    subprocess.run(command, check=True)

    subprocess.run(
        [
            "incus",
            "config",
            "device",
            "add",
            name,
            "project",
            "disk",
            f"source={project_dir}",
            f"path={project_dir}",
            "shift=true",
        ],
        check=True,
    )

    for i, mount in enumerate(bind_mounts or []):
        subprocess.run(
            [
                "incus",
                "config",
                "device",
                "add",
                name,
                f"bind-{i}",
                "disk",
                f"source={mount}",
                f"path={mount}",
                "shift=true",
            ],
            check=True,
        )
