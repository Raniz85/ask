import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ask import agent
from ask.agent import Agent
from ask.config import Layer
from ask.module import resolve_packages


@dataclass
class Manifest:
    distribution: str
    bind_mounts: list[Path] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)
    packages: dict[str, list[str]] = field(default_factory=dict)


def load(path: Path) -> Manifest:
    with path.open("rb") as f:
        data = tomllib.load(f)
    bind_mounts = [Path(p).expanduser() for p in data.get("bind_mounts", [])]
    layers = list(data.get("layers", []))
    packages = {distro: list(pkgs) for distro, pkgs in data.get("packages", {}).items()}
    return Manifest(
        distribution=data["distribution"],
        bind_mounts=bind_mounts,
        layers=layers,
        packages=packages,
    )


@dataclass
class ResolvedManifest:
    manifest: Manifest
    layers: dict[str, Layer]

    def _configured_layers(self) -> list[Layer]:
        result = []
        for layer_name in self.manifest.layers:
            try:
                result.append(self.layers[layer_name])
            except KeyError:
                raise ValueError(f"no known layer named {layer_name!r}") from None
        return result

    @property
    def bind_mounts(self) -> list[Path]:
        mounts = list(self.manifest.bind_mounts)
        for layer in self._configured_layers():
            mounts += layer.bind_mounts
        return mounts

    @property
    def packages(self) -> list[str]:
        packages = resolve_packages(self.manifest.packages, self.manifest.distribution)
        for layer in self._configured_layers():
            packages += resolve_packages(layer.packages, self.manifest.distribution)
        return packages

    @property
    def agent_names(self) -> list[str]:
        names: list[str] = []
        for layer in self._configured_layers():
            names += layer.agents
        return names

    @property
    def agents(self) -> list[Agent]:
        return [agent.resolve(name) for name in self.agent_names]

    @property
    def shared_state_agents(self) -> list[Agent]:
        names: list[str] = []
        for layer in self._configured_layers():
            if layer.shared_state:
                names += layer.agents
        return [agent.resolve(name) for name in names]
