from dataclasses import dataclass, field
from pathlib import Path

from ask.config import ResolvedUser
from ask.incus import Mount


@dataclass(frozen=True)
class Shell:
    name: str
    rc_filename: str
    packages: list[str] = field(default_factory=list)

    def packages_for(self, distribution: str) -> list[str]:
        return list(self.packages)

    def mounts_for(self, user: ResolvedUser) -> list[Mount]:
        return [
            Mount(
                host_path=Path.home() / self.rc_filename,
                container_path=Path(f"/home/{user.name}") / self.rc_filename,
                readonly=True,
            )
        ]


@dataclass(frozen=True)
class Bash(Shell):
    name: str = "bash"
    rc_filename: str = ".bashrc"
    packages: list[str] = field(default_factory=lambda: ["bash"])


@dataclass(frozen=True)
class Zsh(Shell):
    name: str = "zsh"
    rc_filename: str = ".zshrc"
    packages: list[str] = field(default_factory=lambda: ["zsh"])


@dataclass(frozen=True)
class Fish(Shell):
    name: str = "fish"
    rc_filename: str = ".config/fish/config.fish"
    packages: list[str] = field(default_factory=lambda: ["fish"])


@dataclass(frozen=True)
class Ksh(Shell):
    name: str = "ksh"
    rc_filename: str = ".kshrc"
    packages: list[str] = field(default_factory=lambda: ["ksh"])


@dataclass(frozen=True)
class Elvish(Shell):
    name: str = "elvish"
    rc_filename: str = ".config/elvish/rc.elv"
    packages: list[str] = field(default_factory=lambda: ["elvish"])


_SHELLS: dict[str, Shell] = {
    "bash": Bash(),
    "zsh": Zsh(),
    "fish": Fish(),
    "ksh": Ksh(),
    "elvish": Elvish(),
}


def resolve(name: str) -> Shell:
    try:
        return _SHELLS[name]
    except KeyError:
        raise ValueError(f"no known shell named {name!r}") from None
