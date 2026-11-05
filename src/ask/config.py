import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    distribution: str
    bind_mounts: list[Path] = field(default_factory=list)


def load(path: Path) -> Config:
    with path.open("rb") as f:
        data = tomllib.load(f)
    bind_mounts = [Path(p).expanduser() for p in data.get("bind_mounts", [])]
    return Config(distribution=data["distribution"], bind_mounts=bind_mounts)
