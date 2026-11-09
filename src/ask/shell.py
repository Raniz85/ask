from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, StrictBool, StrictStr, ValidationInfo

from ask.incus import Mount
from ask.problems import unknown_name, unknown_options
from ask.schema import FORBID_UNKNOWN_KEYS
from ask.user import ResolvedUser


@dataclass(frozen=True)
class ShellFile:
    key: str
    path: str
    enabled_by_default: bool = False


@dataclass(frozen=True)
class Shell:
    name: str
    files: list[ShellFile] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)

    def packages_for(self, distribution: str) -> list[str]:
        return list(self.packages)

    def option_keys(self) -> set[str]:
        return {shell_file.key for shell_file in self.files}

    def mounts_for(
        self, user: ResolvedUser, options: dict[str, bool] | None = None
    ) -> list[Mount]:
        options = options or {}
        return [
            Mount(
                host_path=Path.home() / shell_file.path,
                container_path=Path(f"/home/{user.name}") / shell_file.path,
                readonly=True,
            )
            for shell_file in self.files
            if options.get(shell_file.key, shell_file.enabled_by_default)
        ]


@dataclass(frozen=True)
class Bash(Shell):
    name: str = "bash"
    files: list[ShellFile] = field(
        default_factory=lambda: [
            ShellFile("bashrc", ".bashrc", enabled_by_default=True),
            ShellFile("bash_profile", ".bash_profile"),
            ShellFile("profile", ".profile"),
        ]
    )
    packages: list[str] = field(default_factory=lambda: ["bash"])


@dataclass(frozen=True)
class Zsh(Shell):
    name: str = "zsh"
    files: list[ShellFile] = field(
        default_factory=lambda: [
            ShellFile("zshrc", ".zshrc", enabled_by_default=True),
            ShellFile("zprofile", ".zprofile"),
            ShellFile("zshenv", ".zshenv"),
        ]
    )
    packages: list[str] = field(default_factory=lambda: ["zsh"])


@dataclass(frozen=True)
class Fish(Shell):
    name: str = "fish"
    files: list[ShellFile] = field(
        default_factory=lambda: [
            ShellFile("config", ".config/fish/config.fish", enabled_by_default=True),
            ShellFile("functions", ".config/fish/functions"),
            ShellFile("conf_d", ".config/fish/conf.d"),
        ]
    )
    packages: list[str] = field(default_factory=lambda: ["fish"])


@dataclass(frozen=True)
class Ksh(Shell):
    name: str = "ksh"
    files: list[ShellFile] = field(
        default_factory=lambda: [
            ShellFile("kshrc", ".kshrc", enabled_by_default=True),
            ShellFile("profile", ".profile"),
        ]
    )
    packages: list[str] = field(default_factory=lambda: ["ksh"])


@dataclass(frozen=True)
class Elvish(Shell):
    name: str = "elvish"
    files: list[ShellFile] = field(
        default_factory=lambda: [
            ShellFile("rc", ".config/elvish/rc.elv", enabled_by_default=True),
            ShellFile("lib", ".config/elvish/lib"),
        ]
    )
    packages: list[str] = field(default_factory=lambda: ["elvish"])


@dataclass(frozen=True)
class Tcsh(Shell):
    name: str = "tcsh"
    files: list[ShellFile] = field(
        default_factory=lambda: [
            ShellFile("tcshrc", ".tcshrc", enabled_by_default=True),
            ShellFile("login", ".login"),
        ]
    )
    packages: list[str] = field(default_factory=lambda: ["tcsh"])


_SHELLS: dict[str, Shell] = {
    "bash": Bash(),
    "zsh": Zsh(),
    "fish": Fish(),
    "ksh": Ksh(),
    "elvish": Elvish(),
    "tcsh": Tcsh(),
}


def known_names() -> list[str]:
    return sorted(_SHELLS)


def resolve(name: str) -> Shell:
    try:
        return _SHELLS[name]
    except KeyError:
        raise ValueError(f"no known shell named {name!r}") from None


def _check_name(name: str) -> str:
    if name not in _SHELLS:
        raise unknown_name("shell", name, known_names())
    return name


def _check_options(options: dict[str, bool], info: ValidationInfo) -> dict[str, bool]:
    name = info.data.get("name")
    if name not in _SHELLS:
        return options
    option_keys = _SHELLS[name].option_keys()
    unknown = sorted(key for key in options if key not in option_keys)
    if unknown:
        raise unknown_options("shell", name, unknown, option_keys)
    return options


@dataclass
class ShellOption:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    name: Annotated[StrictStr, AfterValidator(_check_name)]
    options: Annotated[dict[str, StrictBool], AfterValidator(_check_options)] = field(
        default_factory=dict
    )
