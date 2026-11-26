from pathlib import Path

from ask import config, manifest
from ask.config import Config, ConfigError
from ask.errors import AskError
from ask.manifest import Manifest, ResolvedManifest


class ManifestNotFoundError(AskError):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.path = path

    def __str__(self) -> str:
        return (
            f"No {self.path.name} found in {self.path.parent}. "
            f"Run `ask init` to create one, or run ask from a project directory "
            f"containing {self.path.name}."
        )


def load_config(directory: Path) -> Config:
    return config.load(directory)


def find_project_dir(start: Path) -> Path:
    current = start
    while not (current / "ask.toml").exists():
        if current.parent == current:
            return start
        current = current.parent
    return current


def _missing_bind_mounts(location: str, bind_mounts: list[Path]) -> list[str]:
    return [
        f"{location}bind_mounts.{index}: path {path} does not exist"
        for index, path in enumerate(bind_mounts)
        if not path.exists()
    ]


def _missing_taskfiles(location: str, taskfiles: list[Path]) -> list[str]:
    return [
        f"{location}taskfiles.{index}: path {path} does not exist"
        for index, path in enumerate(taskfiles)
        if not path.exists()
    ]


def check_manifest(m: Manifest) -> list[str]:
    return [
        *_missing_bind_mounts("", m.bind_mounts),
        *_missing_taskfiles("", m.taskfiles),
    ]


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise ManifestNotFoundError(path)
    m = manifest.load(path)
    problems = check_manifest(m)
    if problems:
        raise ConfigError(path, problems)
    return m


def resolve_project(
    flavors_dir: Path, cfg: Config, m: Manifest, project_dir: Path
) -> ResolvedManifest:
    flavor_name, flavor = config.select_flavor(cfg, project_dir)
    resolved = ResolvedManifest(m, flavor, flavor_name, project_dir)
    problems: list[str] = []
    for layer_name in resolved.layer_names:
        problems += _missing_bind_mounts(
            f"layers.{layer_name}.",
            flavor.layers[layer_name].bind_mounts,
        )
        problems += _missing_taskfiles(
            f"layers.{layer_name}.",
            flavor.layers[layer_name].taskfiles,
        )
    if problems:
        raise ConfigError(config.flavor_path(flavors_dir, flavor_name), problems)
    return resolved
