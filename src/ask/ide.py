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


_JETBRAINS_STATE_PATHS = [
    ".config/JetBrains",
    ".local/share/JetBrains",
    ".cache/JetBrains",
]


@dataclass(frozen=True)
class Ide:
    name: str
    packages: dict[str, list[str]] = field(default_factory=dict)
    config_paths: list[str] = field(default_factory=list)
    aliases: tuple[str, ...] = ()
    # JetBrains releases API product code, used to fetch the Debian tarball
    code: str = ""

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
class JetbrainsIde(Ide):
    # AUR packages are the official JetBrains binaries (extra/*-community-edition
    # packages are built from intellij-community and have no license manager).
    # The IDEs are X11 applications, bridged onto Wayland by xwayland-satellite.
    # Debian ships no JetBrains packages; the tarball is fetched and installed by
    # provision_ide instead.
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {
            "arch": ["xwayland-satellite"],
            "debian": ["curl", "tar", "gzip"],
        }
    )
    config_paths: list[str] = field(
        default_factory=lambda: list(_JETBRAINS_STATE_PATHS)
    )

    def packages_for(self, distribution: str) -> list[str]:
        packages = resolve_packages(self.packages, distribution)
        if distribution == "arch":
            return [f"aur:{self.name}", *packages]
        return packages


@dataclass(frozen=True)
class Pycharm(JetbrainsIde):
    name: str = "pycharm"
    code: str = "PCP"


@dataclass(frozen=True)
class IntellijIdea(JetbrainsIde):
    name: str = "idea"
    aliases: tuple[str, ...] = ("intellij-idea",)
    # the AUR package name differs from the binary name
    code: str = "IIU"

    def packages_for(self, distribution: str) -> list[str]:
        packages = super().packages_for(distribution)
        return [
            "aur:intellij-idea-ultimate-edition" if p == "aur:idea" else p
            for p in packages
        ]


@dataclass(frozen=True)
class Webstorm(JetbrainsIde):
    name: str = "webstorm"
    code: str = "WS"


@dataclass(frozen=True)
class Phpstorm(JetbrainsIde):
    name: str = "phpstorm"
    code: str = "PS"


@dataclass(frozen=True)
class Rubymine(JetbrainsIde):
    name: str = "rubymine"
    code: str = "RM"


@dataclass(frozen=True)
class Goland(JetbrainsIde):
    name: str = "goland"
    code: str = "GO"


@dataclass(frozen=True)
class Clion(JetbrainsIde):
    name: str = "clion"
    code: str = "CL"


@dataclass(frozen=True)
class Rider(JetbrainsIde):
    name: str = "rider"
    code: str = "RD"


@dataclass(frozen=True)
class Datagrip(JetbrainsIde):
    name: str = "datagrip"
    code: str = "DG"


@dataclass(frozen=True)
class Rustrover(JetbrainsIde):
    name: str = "rustrover"
    code: str = "RR"


@dataclass(frozen=True)
class Vscode(Ide):
    name: str = "code"
    aliases: tuple[str, ...] = ("vscode",)
    # AUR visual-studio-code-bin is Microsoft's official binary; Debian ships
    # no code package, the tarball is fetched and installed by provision_ide
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {
            "arch": ["aur:visual-studio-code-bin"],
            "debian": ["curl", "tar", "gzip", "libsecret-1-0"],
        }
    )
    config_paths: list[str] = field(
        default_factory=lambda: [
            ".config/Code",
            ".vscode",
        ]
    )


@dataclass(frozen=True)
class Zed(Ide):
    name: str = "zed"
    # AUR zed-bin is the official release tarball repackaged; Debian ships no
    # zed package, the tarball is fetched and installed by provision_ide
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {
            "arch": ["aur:zed-bin"],
            "debian": ["curl", "tar", "gzip"],
        }
    )
    config_paths: list[str] = field(
        default_factory=lambda: [
            ".config/zed",
            ".local/share/zed",
        ]
    )


_IDES: dict[str, Ide] = {
    "pycharm": Pycharm(),
    "idea": IntellijIdea(),
    "webstorm": Webstorm(),
    "phpstorm": Phpstorm(),
    "rubymine": Rubymine(),
    "goland": Goland(),
    "clion": Clion(),
    "rider": Rider(),
    "datagrip": Datagrip(),
    "rustrover": Rustrover(),
    "code": Vscode(),
    "zed": Zed(),
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
