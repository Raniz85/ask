from pathlib import Path

from ask import config, manifest
from ask.agent import known_names as known_agents
from ask.agent import resolve as resolve_agent
from ask.config import AgentOption, Config, ConfigError, Layer, ShellOption
from ask.incus import known_distributions
from ask.manifest import Manifest
from ask.shell import known_names as known_shells
from ask.shell import resolve as resolve_shell


def _known(names: list[str] | set[str]) -> str:
    return f"(known: {', '.join(sorted(names)) or 'none'})"


def _unknown_options(
    location: str, owner: str, options: dict[str, bool], known: set[str]
) -> list[str]:
    return [
        f"{location}.{key}: unknown option for {owner} {_known(known)}"
        for key in options
        if key not in known
    ]


def _check_shell(option: ShellOption) -> list[str]:
    if option.name not in known_shells():
        return [f"shell.name: unknown shell {option.name!r} {_known(known_shells())}"]
    known_options = resolve_shell(option.name).option_keys()
    return _unknown_options("shell", option.name, option.options, known_options)


def _check_agent(location: str, option: AgentOption) -> list[str]:
    if option.name not in known_agents():
        return [
            f"{location}.name: unknown agent {option.name!r} {_known(known_agents())}"
        ]
    known_options = resolve_agent(option.name).option_keys()
    return _unknown_options(location, option.name, option.options, known_options)


def _check_layer(location: str, layer: Layer) -> list[str]:
    problems: list[str] = []
    for index, option in enumerate(layer.agents):
        problems += _check_agent(f"{location}agents.{index}", option)
    return problems


def check_config(cfg: Config) -> list[str]:
    problems = _check_shell(cfg.shell)
    for layer_name, layer in cfg.layers.items():
        problems += _check_layer(f"layers.{layer_name}.", layer)
    return problems


def load_config(path: Path) -> Config:
    cfg = config.load(path)
    problems = check_config(cfg)
    if problems:
        raise ConfigError(path, problems)
    return cfg


def check_manifest(m: Manifest, cfg: Config) -> list[str]:
    problems: list[str] = []
    if m.distribution not in known_distributions():
        problems.append(
            f"distribution: unknown distribution {m.distribution!r} "
            f"{_known(known_distributions())}"
        )
    for index, layer_name in enumerate(m.layers):
        if layer_name not in cfg.layers:
            problems.append(
                f"layers.{index}: layer {layer_name!r} is not defined in the "
                f"global config {_known(set(cfg.layers))}"
            )
    problems += _check_layer("", m)
    return problems


def load_manifest(path: Path, cfg: Config) -> Manifest:
    m = manifest.load(path)
    problems = check_manifest(m, cfg)
    if problems:
        raise ConfigError(path, problems)
    return m
