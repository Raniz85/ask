from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, StrictStr

from ask.errors import AskError
from ask.incus import Mount
from ask.module import resolve_packages
from ask.problems import unknown_name
from ask.user import ResolvedUser


class IdeError(AskError):
    pass


@dataclass(frozen=True)
class Ide:
    name: str
    packages: dict[str, list[str]] = field(default_factory=dict)
    config_paths: list[str] = field(default_factory=list)
    aliases: tuple[str, ...] = ()

    @property
    def binary(self) -> str:
        return self.name

    def packages_for(self, distribution: str) -> list[str]:
        return resolve_packages(self.packages, distribution)

    def mounts_for(self, user: ResolvedUser) -> list[Mount]:
        mounts = [
            Mount(
                host_path=Path.home() / state_path,
                container_path=Path(f"/home/{user.name}") / state_path,
            )
            for state_path in self.config_paths
        ]
        return [mount for mount in mounts if mount.host_path.exists()]


@dataclass(frozen=True)
class Pycharm(Ide):
    name: str = "pycharm"
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {
            # the extra repo package ships the unified build, which a
            # JetBrains license unlocks to Pro; its launcher is /usr/bin/pycharm.
            # PyCharm is an X11 application, bridged onto Wayland by
            # xwayland-satellite
            "arch": ["pycharm-community-edition", "xwayland-satellite"],
            # Debian ships no pycharm package; the tarball is fetched and
            # installed by provision_pycharm instead
            "debian": ["curl", "tar", "gzip"],
        }
    )
    config_paths: list[str] = field(
        default_factory=lambda: [
            ".config/JetBrains",
            ".local/share/JetBrains",
            ".cache/JetBrains",
        ]
    )


_IDES: dict[str, Ide] = {
    "pycharm": Pycharm(),
}


def known_names() -> list[str]:
    return sorted(_IDES)


def resolve(name: str) -> Ide:
    try:
        return _IDES[name]
    except KeyError:
        raise ValueError(f"no known ide named {name!r}") from None


# Aliases resolve on the command line only; configuration uses canonical names
_ALIASES: dict[str, str] = {
    alias: name for name, ide in _IDES.items() for alias in ide.aliases
}


def resolve_name(name: str) -> Ide | None:
    return _IDES.get(_ALIASES.get(name, name))


def known_with_aliases() -> list[str]:
    return [
        f"{name} (aliases: {', '.join(ide.aliases)})" if ide.aliases else name
        for name, ide in sorted(_IDES.items())
    ]


def _check_name(name: str) -> str:
    if name not in _IDES:
        raise unknown_name("ide", name, known_names())
    return name


IdeName = Annotated[StrictStr, AfterValidator(_check_name)]
