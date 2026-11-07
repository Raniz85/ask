import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ask.agent import Agent
from ask.config import Layer


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


def resolve_bind_mounts(manifest: Manifest, layers: dict[str, Layer]) -> list[Path]:
    mounts = list(manifest.bind_mounts)
    for layer_name in manifest.layers:
        try:
            layer = layers[layer_name]
        except KeyError:
            raise ValueError(f"no known layer named {layer_name!r}") from None
        mounts += layer.bind_mounts
    return mounts


def _packages_for_distribution(
    packages: dict[str, list[str]], distribution: str
) -> list[str]:
    return packages.get("common", []) + packages.get(distribution, [])


def resolve_packages(manifest: Manifest, layers: dict[str, Layer]) -> list[str]:
    packages = _packages_for_distribution(manifest.packages, manifest.distribution)
    for layer_name in manifest.layers:
        try:
            layer = layers[layer_name]
        except KeyError:
            raise ValueError(f"no known layer named {layer_name!r}") from None
        packages += _packages_for_distribution(layer.packages, manifest.distribution)
    return packages


def resolve_agents(manifest: Manifest, layers: dict[str, Layer]) -> list[str]:
    agents: list[str] = []
    for layer_name in manifest.layers:
        try:
            layer = layers[layer_name]
        except KeyError:
            raise ValueError(f"no known layer named {layer_name!r}") from None
        agents += layer.agents
    return agents


def resolve_shared_state_agents(
    manifest: Manifest, layers: dict[str, Layer]
) -> list[str]:
    agents: list[str] = []
    for layer_name in manifest.layers:
        try:
            layer = layers[layer_name]
        except KeyError:
            raise ValueError(f"no known layer named {layer_name!r}") from None
        if layer.shared_state:
            agents += layer.agents
    return agents


def resolve_agent_packages(agents: list[Agent], distribution: str) -> list[str]:
    packages: list[str] = []
    for a in agents:
        packages += _packages_for_distribution(a.packages, distribution)
    return packages
