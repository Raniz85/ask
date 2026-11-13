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


def _dump[T](schema: type[T], value: T) -> object:
    return TypeAdapter(schema).dump_python(value, mode="json")


def _layer(name: str, layer: Layer) -> dict[str, object]:
    dumped = _dump(Layer, layer)
    assert isinstance(dumped, dict)
    # the default agent and agent variables only matter when an agent is
    # launched, they do not affect the provisioned state of the container
    agents = dumped["agents"]
    agents.pop("default")
    agents.pop("env")
    for settings in agents["entries"].values():
        settings.pop("env")
    return {"name": name, **dumped}


def effective_configuration(resolved: ResolvedManifest) -> str:
    flavor = resolved.flavor
    manifest = _dump(Manifest, resolved.manifest)
    assert isinstance(manifest, dict)
    # scripts only run inside the container on demand, they do not affect its
    # provisioned state, so they are not part of the converged configuration
    manifest.pop("scripts", None)
    configuration = {
        "flavor": {
            "distribution": flavor.distribution,
            "shell": _dump(ShellOption, flavor.shell),
            "user": _dump(User, flavor.user),
        },
        "layers": [_layer(name, flavor.layers[name]) for name in resolved.layer_names],
        "manifest": manifest,
        "tool_manager_configs": _tool_manager_configs(resolved),
    }
    return json.dumps(configuration, sort_keys=True, separators=(",", ":"))


def fingerprint(configuration: str) -> Fingerprint:
    return Fingerprint(
        version=version("ask"),
        config_hash=hashlib.sha256(configuration.encode()).hexdigest(),
    )
