from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, StrictStr
from pydantic_core import PydanticCustomError

from ask import agent, env, tool_manager
from ask.agent import Agent
from ask.config import (
    BASE_LAYER,
    Flavor,
    HomePath,
    Layer,
    _normalize_service_dict,
    _validate,
    read_toml,
)
from ask.env import Env
from ask.incus import Mount
from ask.removal import is_removal, removals
from ask.schema import FORBID_UNKNOWN_KEYS
from ask.tool_manager import Mise
from ask.user import ResolvedUser


def _validate_scripts(
    scripts: dict[StrictStr, StrictStr],
) -> dict[StrictStr, StrictStr]:
    for name, command in scripts.items():
        if not name.strip():
            raise PydanticCustomError(
                "empty_script_name",
                "script name cannot be empty",
            )
        if not command.strip():
            raise PydanticCustomError(
                "empty_script_command",
                "script command cannot be empty for script '{name}'",
                {"name": name},
            )
    return scripts


@dataclass
class Manifest:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    packages: list[StrictStr] = field(default_factory=list)
    bind_mounts: list[HomePath] = field(default_factory=list)
    services: dict[StrictStr, StrictStr] = field(default_factory=dict)
    tool_managers: list[
        Annotated[StrictStr, AfterValidator(tool_manager.check_name)]
    ] = field(default_factory=list)
    scripts: Annotated[
        dict[StrictStr, StrictStr], AfterValidator(_validate_scripts)
    ] = field(default_factory=dict)
    env: Env = field(default_factory=dict)


def load(path: Path) -> Manifest:
    data = read_toml(path)
    if "services" in data:
        data["services"] = _normalize_service_dict(data["services"])
    return _validate(path, data, Manifest)


@dataclass
class _MergedAgent:
    name: str
    options: dict[str, bool] = field(default_factory=dict)
    extensions: list[str] = field(default_factory=list)
    envs: list[Env] = field(default_factory=list)


@dataclass
class ResolvedManifest:
    manifest: Manifest
    flavor: Flavor
    project_dir: Path

    def _applies(self, layer: Layer) -> bool:
        return layer.when is None or any(
            (self.project_dir / file_name).exists() for file_name in layer.when.files
        )

    @property
    def layer_names(self) -> list[str]:
        base = [name for name in self.flavor.layers if name == BASE_LAYER]
        others = sorted(
            (
                name
                for name, layer in self.flavor.layers.items()
                if name != BASE_LAYER and self._applies(layer)
            ),
            key=lambda name: self.flavor.layers[name].order,
        )
        return base + others

    def _flavor_layers(self) -> list[Layer]:
        return [self.flavor.layers[name] for name in self.layer_names]

    def _configured_layers(self) -> list[Layer | Manifest]:
        return [*self._flavor_layers(), self.manifest]

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
            removed = removals(layer.packages)
            packages = [p for p in packages if p not in removed]
            packages += [p for p in layer.packages if not is_removal(p)]
        return list(dict.fromkeys(packages))

    def _merged_agents(self) -> list[_MergedAgent]:
        merged: dict[str, _MergedAgent] = {}
        for layer in self._flavor_layers():
            for name, settings in layer.agents.entries.items():
                if not settings.enabled:
                    merged.pop(name, None)
                    continue
                entry = merged.setdefault(name, _MergedAgent(name))
                entry.options.update(settings.options)
                entry.extensions = list(
                    dict.fromkeys([*entry.extensions, *settings.extensions])
                )
                entry.envs.append(settings.env)
        return list(merged.values())

    @property
    def agent_names(self) -> list[str]:
        return [entry.name for entry in self._merged_agents()]

    @property
    def default_agent(self) -> str | None:
        defaults = [
            layer.agents.default
            for layer in self._flavor_layers()
            if layer.agents.default is not None
        ]
        if not defaults:
            return next(iter(self.agent_names), None)
        if defaults[-1] not in self.agent_names:
            raise agent.AgentError(
                f"The default agent {defaults[-1]!r} is not enabled in the flavour "
                "layers that apply to this project."
            )
        return defaults[-1]

    @property
    def instance_env(self) -> dict[str, str]:
        return env.merge(layer.env for layer in self._configured_layers())

    def agent_env(self, name: str) -> dict[str, str]:
        own_envs = next(
            (entry.envs for entry in self._merged_agents() if entry.name == name), []
        )
        return env.merge(
            [
                *(layer.env for layer in self._configured_layers()),
                *(layer.agents.env for layer in self._flavor_layers()),
                *own_envs,
            ]
        )

    @property
    def agents(self) -> list[Agent]:
        return [agent.resolve(name) for name in self.agent_names]

    @property
    def pi_extensions(self) -> list[str]:
        for entry in self._merged_agents():
            if entry.name == agent.EXTENSIONS_AGENT:
                return entry.extensions
        return []

    @property
    def tool_managers(self) -> list[Mise]:
        names = dict.fromkeys(self.manifest.tool_managers)
        return [tool_manager.resolve(name) for name in names]

    @property
    def services(self) -> dict[str, str]:
        services: dict[str, str] = {}
        for layer in self._flavor_layers():
            services.update(layer.services)
        # Manifest services take precedence over layer services
        services.update(_normalize_service_dict(self.manifest.services))
        return services

    @property
    def scripts(self) -> dict[str, str]:
        return self.manifest.scripts

    def agent_mounts(self, user: ResolvedUser) -> list[Mount]:
        mounts: list[Mount] = []
        for entry in self._merged_agents():
            resolved_agent = agent.resolve(entry.name)
            mounts += resolved_agent.mounts_for(user, entry.options)
        return mounts
