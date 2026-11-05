import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Layer:
    bind_mounts: list[Path] = field(default_factory=list)


@dataclass
class Config:
    layers: dict[str, Layer] = field(default_factory=dict)


def default_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_PATH", str(Path.home() / ".config"))
    return Path(config_home) / "ask" / "config.toml"


def load(path: Path) -> Config:
    if not path.exists():
        return Config(layers={})
    with path.open("rb") as f:
        data = tomllib.load(f)
    layers = {
        name: Layer(bind_mounts=[Path(p).expanduser() for p in layer_data.get("bind_mounts", [])])
        for name, layer_data in data.get("layers", {}).items()
    }
    return Config(layers=layers)
