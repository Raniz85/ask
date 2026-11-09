import hashlib
import json
from pathlib import Path
from importlib.metadata import version

from pydantic import TypeAdapter

from ask.config import Config, Layer, User
from ask.incus import Fingerprint
from ask.manifest import Manifest, ResolvedManifest
from ask.shell import ShellOption


def _tool_manager_configs(
    m: Manifest, cfg: Config, project_dir: Path
) -> dict[str, dict[str, str]]:
    configs: dict[str, dict[str, str]] = {}
    for tool_manager in ResolvedManifest(m, cfg.layers).tool_managers:
        config_files = tool_manager.config_files(project_dir)
        if config_files:
            configs[tool_manager.name] = {
                str(config_file): (project_dir / config_file).read_text()
                for config_file in config_files
            }
    return configs


def effective_configuration(m: Manifest, cfg: Config, project_dir: Path) -> str:
    configuration = {
        "manifest": TypeAdapter(Manifest).dump_python(m, mode="json"),
        "layers": {
            name: TypeAdapter(Layer).dump_python(cfg.layers[name], mode="json")
            for name in m.layers
        },
        "user": TypeAdapter(User).dump_python(cfg.user, mode="json"),
        "shell": TypeAdapter(ShellOption).dump_python(cfg.shell, mode="json"),
        "tool_manager_configs": _tool_manager_configs(m, cfg, project_dir),
    }
    return json.dumps(configuration, sort_keys=True, separators=(",", ":"))


def fingerprint(configuration: str) -> Fingerprint:
    return Fingerprint(
        version=version("ask"),
        config_hash=hashlib.sha256(configuration.encode()).hexdigest(),
    )
