from dataclasses import dataclass, field
from pathlib import Path

from pydantic import StrictStr

from ask import agent
from ask.agent import Agent
from ask.config import Layer, ResolvedUser, load_as
from ask.incus import Mount
from ask.module import resolve_packages


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
    shared_state: bool = False


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
            packages += resolve_packages(layer.packages, self.manifest.distribution)
        return list(dict.fromkeys(packages))

    def _merged_agents(self) -> list[_MergedAgent]:
        merged: dict[str, _MergedAgent] = {}
        for layer in self._configured_layers():
            for option in layer.agents:
                entry = merged.setdefault(option.name, _MergedAgent(option.name))
                entry.options.update(option.options)
                if layer.shared_state is not None:
                    entry.shared_state = layer.shared_state
        return list(merged.values())

    @property
    def agent_names(self) -> list[str]:
        return [entry.name for entry in self._merged_agents()]

    @property
    def agents(self) -> list[Agent]:
        return [agent.resolve(name) for name in self.agent_names]

    def shared_state_mounts(self, user: ResolvedUser) -> list[Mount]:
        mounts: list[Mount] = []
        for entry in self._merged_agents():
            if entry.shared_state:
                resolved_agent = agent.resolve(entry.name)
                mounts += resolved_agent.mounts_for(user, entry.options)
        return mounts
