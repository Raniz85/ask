import sys
from pathlib import Path

from ask import config, manifest
from ask.config import Config, ConfigError, Layer
from ask.incus import known_distributions
from ask.manifest import Manifest
from ask.problems import known
from ask.removal import REMOVAL_PREFIX


def _layer_warnings(location: str, layer: Layer) -> list[str]:
    return [
        f"{location}agents.{index}: options have no effect when removing agent "
        f"{option.name.removeprefix(REMOVAL_PREFIX)!r}"
        for index, option in enumerate(layer.agents)
        if option.name.startswith(REMOVAL_PREFIX) and option.options
    ]


def _print_warnings(path: Path, warnings: list[str]) -> None:
    if warnings:
        lines = [f"ask: warning in {path}"]
        lines += [f"  {warning}" for warning in warnings]
        print("\n".join(lines), file=sys.stderr)


def config_warnings(cfg: Config) -> list[str]:
    warnings: list[str] = []
    for layer_name, layer in cfg.layers.items():
        warnings += _layer_warnings(f"layers.{layer_name}.", layer)
    return warnings


def load_config(path: Path) -> Config:
    cfg = config.load(path)
    _print_warnings(path, config_warnings(cfg))
    return cfg


def check_manifest(m: Manifest, cfg: Config) -> list[str]:
    problems: list[str] = []
    if m.distribution not in known_distributions():
        problems.append(
            f"distribution: unknown distribution {m.distribution!r} "
            f"{known(known_distributions())}"
        )
    for index, layer_name in enumerate(m.layers):
        if layer_name not in cfg.layers:
            problems.append(
                f"layers.{index}: layer {layer_name!r} is not defined in the "
                f"global config {known(set(cfg.layers))}"
            )
    return problems


def manifest_warnings(m: Manifest) -> list[str]:
    return _layer_warnings("", m)


def load_manifest(path: Path, cfg: Config) -> Manifest:
    m = manifest.load(path)
    problems = check_manifest(m, cfg)
    if problems:
        raise ConfigError(path, problems)
    _print_warnings(path, manifest_warnings(m))
    return m
