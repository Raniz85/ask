import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_core import PydanticCustomError

from ask.module import resolve_packages
from ask.problems import unknown_name
from ask.removal import is_removal
from ask.user import ResolvedUser

_MISE_CONFIG_PATTERNS = [
    "mise.toml",
    "mise.*.toml",
    ".mise.toml",
    ".mise.*.toml",
    ".config/mise.toml",
    ".config/mise.*.toml",
    ".config/mise/mise.toml",
    ".config/mise/mise.*.toml",
    *(
        f"{directory}/{pattern}"
        for directory in ("mise", ".mise", ".config/mise")
        for pattern in (
            "config.toml",
            "config.*.toml",
            "conf.d/*.toml",
            "conf.d/*/mise.toml",
            "conf.d/*/mise.*.toml",
        )
    ),
]


@dataclass(frozen=True)
class Mise:
    name: str = "mise"
    packages: dict[str, list[str]] = field(default_factory=lambda: {"arch": ["mise"]})

    def packages_for(self, distribution: str) -> list[str]:
        return resolve_packages(self.packages, distribution)

    def config_files(self, project_dir: Path) -> list[Path]:
        found = {
            path.relative_to(project_dir)
            for pattern in _MISE_CONFIG_PATTERNS
            for path in project_dir.glob(pattern)
            if path.is_file()
        }
        return sorted(found)

    def path_entries(self, user: ResolvedUser) -> list[Path]:
        return [Path(f"/home/{user.name}/.local/share/mise/shims")]


def config_digest(project_dir: Path, config_files: list[Path]) -> str:
    digest = hashlib.sha256()
    for config_file in config_files:
        digest.update(str(config_file).encode() + b"\0")
        digest.update((project_dir / config_file).read_bytes() + b"\0")
    return digest.hexdigest()


_TOOL_MANAGERS: dict[str, Mise] = {
    "mise": Mise(),
}


def known_names() -> list[str]:
    return sorted(_TOOL_MANAGERS)


def resolve(name: str) -> Mise:
    try:
        return _TOOL_MANAGERS[name]
    except KeyError:
        raise ValueError(f"no known tool manager named {name!r}") from None


def check_name(name: str) -> str:
    if is_removal(name):
        raise PydanticCustomError(
            "tool_manager_removal",
            "tool managers are only enabled by ask.toml and cannot be removed with '-'",
        )
    if name not in _TOOL_MANAGERS:
        raise unknown_name("tool manager", name, known_names())
    return name
