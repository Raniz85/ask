import hashlib
import json
from importlib.metadata import version

from pydantic import TypeAdapter

from ask.config import Config, Layer, User
from ask.incus import Fingerprint
from ask.manifest import Manifest
from ask.shell import ShellOption


def effective_configuration(m: Manifest, cfg: Config) -> str:
    configuration = {
        "manifest": TypeAdapter(Manifest).dump_python(m, mode="json"),
        "layers": {
            name: TypeAdapter(Layer).dump_python(cfg.layers[name], mode="json")
            for name in m.layers
        },
        "user": TypeAdapter(User).dump_python(cfg.user, mode="json"),
        "shell": TypeAdapter(ShellOption).dump_python(cfg.shell, mode="json"),
    }
    return json.dumps(configuration, sort_keys=True, separators=(",", ":"))


def fingerprint(configuration: str) -> Fingerprint:
    return Fingerprint(
        version=version("ask"),
        config_hash=hashlib.sha256(configuration.encode()).hexdigest(),
    )
