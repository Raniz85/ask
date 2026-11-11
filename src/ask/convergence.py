import hashlib
import json
from importlib.metadata import version

from pydantic import TypeAdapter

from ask.config import Layer, User
from ask.incus import Fingerprint
from ask.manifest import Manifest, ResolvedManifest
from ask.shell import ShellOption


def _tool_manager_configs(resolved: ResolvedManifest) -> dict[str, dict[str, str]]:
    configs: dict[str, dict[str, str]] = {}
    for tool_manager in resolved.tool_managers:
        config_files = tool_manager.config_files(resolved.project_dir)
        if config_files:
            configs[tool_manager.name] = {
                str(config_file): (resolved.project_dir / config_file).read_text()
                for config_file in config_files
            }
    return configs


def _dump[T](schema: type[T], value: T) -> dict[str, str] | object:
    dumped = TypeAdapter(schema).dump_python(value, mode="json")
    if schema is Layer:
        assert isinstance(dumped, dict)
        return dumped
    return dumped


def effective_configuration(resolved: ResolvedManifest) -> str:
    flavor = resolved.flavor
    configuration = {
        "flavor": {
            "distribution": flavor.distribution,
            "shell": _dump(ShellOption, flavor.shell),
            "user": _dump(User, flavor.user),
        },
        "layers": [
            {"name": name, **layer_dump}
            for name in resolved.layer_names
            if (layer_dump := _dump(Layer, flavor.layers[name])) and isinstance(layer_dump, dict)
        ],
        "manifest": _dump(Manifest, resolved.manifest),
        "tool_manager_configs": _tool_manager_configs(resolved),
    }
    return json.dumps(configuration, sort_keys=True, separators=(",", ":"))


def fingerprint(configuration: str) -> Fingerprint:
    return Fingerprint(
        version=version("ask"),
        config_hash=hashlib.sha256(configuration.encode()).hexdigest(),
    )
