from dataclasses import dataclass, field
from pathlib import Path

from pydantic import StrictStr

from ask import agent
from ask.agent import Agent
from ask.config import Layer, load_as
from ask.incus import Mount
from ask.module import resolve_packages
from ask.removal import is_removal, removals
from ask.user import ResolvedUser


@dataclass(kw_only=True)
class Manifest(Layer):
    distribution: StrictStr
    layers: list[StrictStr] = field(default_factory=list)


def load(path: Path) -> Manifest:
    return load_as(path, Manifest)


@dataclass
class _MergedAgent:
    name: str
    options: dict[str, bool] = field(default_factory=dict)


@dataclass
class ResolvedManifest:
    manifest: Manifest
    layers: dict[str, Layer]

    def _configured_layers(self) -> list[Layer]:
        result: list[Layer] = []
        for layer_name in self.manifest.layers:
            try:
                result.append(self.layers[layer_name])
            except KeyError:
                raise ValueError(f"no known layer named {layer_name!r}") from None
        return result + [self.manifest]

    @property
    def bind_mounts(self) -> list[Path]:
        mounts: list[Path] = []
        for layer in self._configured_layers():
            mounts += layer.bind_mounts
        return list(dict.fromkeys(mounts))

    @property
    def packages(self) -> list[str]:
        packages: list[str] = []
        for layer in self._configured_layers():
            layer_packages = resolve_packages(
                layer.packages, self.manifest.distribution
            )
            removed = removals(layer_packages)
            packages = [p for p in packages if p not in removed]
            packages += [p for p in layer_packages if not is_removal(p)]
        return list(dict.fromkeys(packages))

    def _merged_agents(self) -> list[_MergedAgent]:
        merged: dict[str, _MergedAgent] = {}
        for layer in self._configured_layers():
            for name in removals([option.name for option in layer.agents]):
                merged.pop(name, None)
            for option in layer.agents:
                if is_removal(option.name):
                    continue
                entry = merged.setdefault(option.name, _MergedAgent(option.name))
                entry.options.update(option.options)
        return list(merged.values())

    @property
    def agent_names(self) -> list[str]:
        return [entry.name for entry in self._merged_agents()]

    @property
    def agents(self) -> list[Agent]:
        return [agent.resolve(name) for name in self.agent_names]

    def agent_mounts(self, user: ResolvedUser) -> list[Mount]:
        mounts: list[Mount] = []
        for entry in self._merged_agents():
            resolved_agent = agent.resolve(entry.name)
            mounts += resolved_agent.mounts_for(user, entry.options)
        return mounts
