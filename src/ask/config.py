import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    distribution: str


def load(path: Path) -> Config:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Config(distribution=data["distribution"])
