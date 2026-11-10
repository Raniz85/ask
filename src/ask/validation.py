import sys
from pathlib import Path

from ask import config, manifest
from ask.config import Config, ConfigError, Layer
from ask.errors import AskError
from ask.manifest import Manifest, ResolvedManifest
from ask.removal import REMOVAL_PREFIX


class ManifestNotFoundError(AskError):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.path = path

    def __str__(self) -> str:
        return (
            f"No {self.path.name} found in {self.path.parent}. "
            f"Run ask from a project directory containing {self.path.name}."
        )


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
    for flavor_name, flavor in cfg.flavors.items():
        for layer_name, layer in flavor.layers.items():
            warnings += _layer_warnings(
                f"flavors.{flavor_name}.layers.{layer_name}.", layer
            )
    return warnings


def load_config(path: Path) -> Config:
    cfg = config.load(path)
    _print_warnings(path, config_warnings(cfg))
    return cfg


def _missing_bind_mounts(location: str, bind_mounts: list[Path]) -> list[str]:
    return [
        f"{location}bind_mounts.{index}: path {path} does not exist"
        for index, path in enumerate(bind_mounts)
        if not path.exists()
    ]


def check_manifest(m: Manifest) -> list[str]:
    return _missing_bind_mounts("", m.bind_mounts)


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise ManifestNotFoundError(path)
    m = manifest.load(path)
    problems = check_manifest(m)
    if problems:
        raise ConfigError(path, problems)
    return m


def resolve_project(
    config_path: Path, cfg: Config, m: Manifest, project_dir: Path
) -> ResolvedManifest:
    flavor_name, flavor = config.select_flavor(cfg, project_dir)
    resolved = ResolvedManifest(m, flavor, project_dir)
    problems: list[str] = []
    for layer_name in resolved.layer_names:
        problems += _missing_bind_mounts(
            f"flavors.{flavor_name}.layers.{layer_name}.",
            flavor.layers[layer_name].bind_mounts,
        )
    if problems:
        raise ConfigError(config_path, problems)
    return resolved
