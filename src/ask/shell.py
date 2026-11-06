from dataclasses import dataclass, field


@dataclass(frozen=True)
class Shell:
    name: str
    rc_filename: str
    packages: list[str] = field(default_factory=list)


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


_SHELLS: dict[str, Shell] = {
    "bash": Bash(),
    "zsh": Zsh(),
}


def resolve(name: str) -> Shell:
    try:
        return _SHELLS[name]
    except KeyError:
        raise ValueError(f"no known shell named {name!r}") from None
