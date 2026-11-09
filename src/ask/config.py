import os
import pwd
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
)
from pydantic_core import ErrorDetails, PydanticCustomError


class ConfigError(Exception):
    def __init__(self, path: Path, problems: list[str]) -> None:
        super().__init__(path, problems)
        self.path = path
        self.problems = problems

    def __str__(self) -> str:
        lines = [f"invalid configuration in {self.path}"]
        lines += [f"  {problem}" for problem in self.problems]
        return "\n".join(lines)


_POSITION = re.compile(
    r"^(?P<message>.*) \(at line (?P<line>\d+), column (?P<column>\d+)\)$"
)


class TomlSyntaxError(ConfigError):
    def __init__(self, path: Path, error: tomllib.TOMLDecodeError) -> None:
        super().__init__(path, [str(error)])
        self.error = error

    def __str__(self) -> str:
        match = _POSITION.match(str(self.error))
        if match is None:
            return f"invalid TOML in {self.path}: {self.error}"
        line = int(match["line"])
        column = int(match["column"])
        source_line = self.path.read_text().splitlines()[line - 1]
        gutter = f"{line:>4}"
        return (
            f"invalid TOML in {self.path} at line {line}, column {column}: "
            f"{match['message']}\n"
            f"{gutter} | {source_line}\n"
            f"{' ' * len(gutter)} | {' ' * (column - 1)}^"
        )


def read_toml(path: Path) -> dict:
    with path.open("rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as error:
            raise TomlSyntaxError(path, error) from None


FORBID_UNKNOWN_KEYS = ConfigDict(extra="forbid")
_OPTIONS = "options"


def _flatten_options(value: object) -> object:
    if isinstance(value, str):
        return {"name": value}
    if isinstance(value, dict):
        flattened = {key: option for key, option in value.items() if key == "name"}
        flattened[_OPTIONS] = {
            key: option for key, option in value.items() if key != "name"
        }
        return flattened
    raise PydanticCustomError(
        "string_or_table", "Input should be a valid string or table"
    )


HomePath = Annotated[Path, AfterValidator(Path.expanduser)]


@dataclass
class AgentOption:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    name: StrictStr
    options: dict[str, StrictBool] = field(default_factory=dict)


@dataclass
class ShellOption:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    name: StrictStr
    options: dict[str, StrictBool] = field(default_factory=dict)


@dataclass
class Layer:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    bind_mounts: list[HomePath] = field(default_factory=list)
    packages: dict[str, list[StrictStr]] = field(default_factory=dict)
    agents: list[Annotated[AgentOption, BeforeValidator(_flatten_options)]] = field(
        default_factory=list
    )
    shared_state: StrictBool = False


@dataclass
class Group:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    name: StrictStr | None = None
    gid: StrictInt | None = None


@dataclass
class User:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    name: StrictStr | None = None
    uid: StrictInt | None = None
    extra_groups: list[StrictStr] = field(default_factory=list)
    group: Group = field(default_factory=Group)


@dataclass
class Config:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    shell: Annotated[ShellOption, BeforeValidator(_flatten_options)] = field(
        default_factory=lambda: ShellOption(name="bash")
    )
    user: User = field(default_factory=User)
    layers: dict[str, Layer] = field(default_factory=dict)


@dataclass
class ResolvedUser:
    name: str
    uid: int
    shell: str
    group_name: str
    gid: int
    extra_groups: list[str]


def resolve_user(cfg: Config) -> ResolvedUser:
    calling_user = pwd.getpwuid(os.getuid())
    name = cfg.user.name or calling_user.pw_name
    uid = cfg.user.uid if cfg.user.uid is not None else calling_user.pw_uid
    group_name = cfg.user.group.name or name
    gid = cfg.user.group.gid if cfg.user.group.gid is not None else uid
    return ResolvedUser(
        name=name,
        uid=uid,
        shell=cfg.shell.name,
        group_name=group_name,
        gid=gid,
        extra_groups=cfg.user.extra_groups,
    )


def default_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_PATH", str(Path.home() / ".config"))
    return Path(config_home) / "ask" / "config.toml"


def _is_flattened_options(location: tuple[str | int, ...], index: int) -> bool:
    # Shell and agent options are written next to "name" in TOML, so the
    # "options" level that _flatten_options adds is hidden from the user.
    return (
        location[index] == _OPTIONS
        and index > 0
        and (location[index - 1] == "shell" or isinstance(location[index - 1], int))
    )


def _problem(details: ErrorDetails) -> str:
    location = details["loc"]
    path = ".".join(
        str(part)
        for index, part in enumerate(location)
        if not _is_flattened_options(location, index)
    )
    if details["type"] == "unexpected_keyword_argument":
        return f"{path}: unknown key"
    return f"{path}: {details['msg']}"


def _validation_problems(error: ValidationError) -> list[str]:
    return [_problem(details) for details in error.errors()]


def load_as[T](path: Path, schema: type[T]) -> T:
    data = read_toml(path)
    try:
        return TypeAdapter(schema).validate_python(data)
    except ValidationError as error:
        raise ConfigError(path, _validation_problems(error)) from None


def load(path: Path) -> Config:
    if not path.exists():
        return Config(layers={})
    return load_as(path, Config)
