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
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
)
from pydantic_core import ErrorDetails, PydanticCustomError

from ask import agent
from ask.agent import AgentTable
from ask.env import Env
from ask.errors import AskError
from ask.ide import IdeName
from ask.incus import known_distributions
from ask.problems import unknown_name
from ask.schema import FORBID_UNKNOWN_KEYS
from ask.shell import ShellOption
from ask.user import ResolvedUser

# Allowed systemd service states (persistent configuration states only)
ALLOWED_SERVICE_STATES = {"enabled", "disabled", "masked"}


def normalize_service_name(service: str) -> str:
    """
    Normalize a service name by adding .service suffix if no other unit type suffix is present.

    Examples:
        sshd -> sshd.service
        docker.socket -> docker.socket
        man-db.timer -> man-db.timer
    """
    # If the service already has a unit type suffix, return as-is
    if any(
        service.endswith(suffix)
        for suffix in [
            ".service",
            ".socket",
            ".timer",
            ".path",
            ".mount",
            ".automount",
            ".target",
            ".slice",
            ".scope",
        ]
    ):
        return service
    # Otherwise, add .service suffix
    return f"{service}.service"


def _normalize_service_dict(services: dict[str, str]) -> dict[str, str]:
    """Normalize service names in a dictionary."""
    if not isinstance(services, dict):
        return {}
    normalized_services = {}
    for service, state in services.items():
        normalized_name = normalize_service_name(service)
        normalized_services[normalized_name] = state
    return normalized_services


class ConfigError(AskError):
    def __init__(self, path: Path, problems: list[str]) -> None:
        super().__init__(path, problems)
        self.path = path
        self.problems = problems

    def __str__(self) -> str:
        lines = [f"Invalid configuration in {self.path}:"]
        lines += [f"  {problem}" for problem in self.problems]
        return "\n".join(lines)


class FlavorError(AskError):
    pass


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
            return f"Invalid TOML in {self.path}: {self.error}"
        line = int(match["line"])
        column = int(match["column"])
        source_line = self.path.read_text().splitlines()[line - 1]
        gutter = f"{line:>4}"
        return (
            f"Invalid TOML in {self.path} at line {line}, column {column}: "
            f"{match['message']}\n"
            f"{gutter} | {source_line}\n"
            f"{' ' * len(gutter)} | {' ' * (column - 1)}^"
        )


def read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as error:
        raise TomlSyntaxError(path, error) from None
    except UnicodeDecodeError:
        raise ConfigError(path, ["file is not valid UTF-8"]) from None
    except OSError as error:
        raise ConfigError(path, [f"cannot read file: {error.strerror}"]) from None


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


def resolve_taskfile_paths(source: Path, taskfiles: list[Path]) -> list[Path]:
    """Resolve taskfile paths relative to the file that declared them."""
    return [
        taskfile if taskfile.is_absolute() else source.parent / taskfile
        for taskfile in taskfiles
    ]


@dataclass
class LayerWhen:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    files: Annotated[
        list[StrictStr],
        Field(
            description="The layer applies when at least one of these files exists in the project directory."
        ),
    ]


BASE_LAYER = "base"


def _validate_service_state(
    value: dict[StrictStr, StrictStr],
) -> dict[StrictStr, StrictStr]:
    for service, state in value.items():
        if state not in ALLOWED_SERVICE_STATES:
            raise PydanticCustomError(
                "invalid_service_state",
                "Invalid service state '{state}' for service '{service}'. Allowed states: {allowed}",
                {
                    "state": state,
                    "service": service,
                    "allowed": ", ".join(sorted(ALLOWED_SERVICE_STATES)),
                },
            )
    # Normalize the service names
    return _normalize_service_dict(value)


@dataclass
class Layer:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    bind_mounts: Annotated[
        list[HomePath],
        Field(
            description="Host paths to bind-mount into the container; `~` expands to the home directory."
        ),
    ] = field(default_factory=list)
    packages: Annotated[
        list[StrictStr],
        Field(
            description="Packages to install; `aur:` prefix installs from the AUR, a `-` prefix removes a package set in a lower layer."
        ),
    ] = field(default_factory=list)
    services: Annotated[
        dict[StrictStr, StrictStr],
        AfterValidator(_validate_service_state),
        Field(
            description="systemd services to manage; keys are unit names (the `.service` suffix is optional), values are `enabled`, `disabled`, or `masked`."
        ),
    ] = field(default_factory=dict)
    agents: Annotated[
        AgentTable,
        BeforeValidator(agent.to_table),
        Field(
            description="Agents to enable in the layer; agent names map to `true`/`false` or a settings table."
        ),
    ] = field(default_factory=AgentTable)
    ides: Annotated[
        list[IdeName], Field(description="IDEs to install and expose in the layer.")
    ] = field(default_factory=list)
    env: Annotated[
        Env,
        Field(
            description="Environment variables to set; `false` unsets the variable instead."
        ),
    ] = field(default_factory=dict)
    taskfiles: Annotated[
        list[HomePath],
        Field(
            description="Extra pyinfra taskfiles to run last during converge; paths are relative to the file declaring them."
        ),
    ] = field(default_factory=list)
    order: Annotated[
        StrictInt,
        Field(
            description="Layers with lower order are applied first; equal orders are applied in unspecified order."
        ),
    ] = 0
    when: Annotated[
        LayerWhen | None,
        Field(description="Condition for the layer to apply; `null` means always."),
    ] = None


@dataclass
class Group:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    name: Annotated[
        StrictStr | None,
        Field(
            description="Group name; `null` mirrors the user's default group (the user's own name)."
        ),
    ] = None
    gid: Annotated[
        StrictInt | None,
        Field(description="Group id; `null` mirrors the user's id."),
    ] = None


@dataclass
class User:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    name: Annotated[
        StrictStr | None,
        Field(description="Container user name; `null` mirrors the calling user."),
    ] = None
    uid: Annotated[
        StrictInt | None,
        Field(description="Container user id; `null` mirrors the calling user."),
    ] = None
    extra_groups: Annotated[
        list[StrictStr], Field(description="Additional groups for the container user.")
    ] = field(default_factory=list)
    group: Annotated[
        Group,
        Field(description="The user's primary group; mirrors the user by default."),
    ] = field(default_factory=Group)


def _expand_home(pattern: object) -> object:
    if isinstance(pattern, str) and (pattern == "~" or pattern.startswith("~/")):
        return re.escape(str(Path.home())) + pattern.removeprefix("~")
    return pattern


@dataclass
class FlavorWhen:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    path: Annotated[
        list[Annotated[re.Pattern, BeforeValidator(_expand_home)]],
        Field(
            description="Projects whose absolute path matches one of these patterns use this flavour; `~` expands to the home directory. Matches the full path."
        ),
    ] = field(default_factory=list)


def _check_distribution(name: str) -> str:
    if name not in known_distributions():
        raise unknown_name("distribution", name, known_distributions())
    return name


def _check_base_layer(layers: dict[str, Layer]) -> dict[str, Layer]:
    base = layers.get(BASE_LAYER)
    if base is not None and base.when is not None:
        raise PydanticCustomError(
            "base_layer_conditions",
            "the base layer is always applied and cannot have when conditions",
        )
    return layers


@dataclass
class Flavor:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    distribution: Annotated[
        StrictStr,
        AfterValidator(_check_distribution),
        Field(description="The Linux distribution the container is created from."),
    ]
    default: Annotated[
        StrictBool,
        Field(
            description="Use this flavour when no other flavour's `when.path` matches."
        ),
    ] = False
    when: Annotated[
        FlavorWhen,
        Field(description="When this flavour applies, by matching the project path."),
    ] = field(default_factory=FlavorWhen)
    shell: Annotated[
        ShellOption,
        BeforeValidator(_flatten_options),
        Field(
            description="The shell to install; either a name string or a table with `name` and per-shell options (e.g. `zshrc = true`)."
        ),
    ] = field(default_factory=lambda: ShellOption(name="bash"))
    user: Annotated[
        User,
        Field(description="The container user; mirrors the calling user by default."),
    ] = field(default_factory=User)
    layers: Annotated[
        dict[str, Layer],
        AfterValidator(_check_base_layer),
        Field(
            description="Named layers applied bottom-up; the `base` layer always applies and cannot have conditions."
        ),
    ] = field(default_factory=dict)


def _check_single_default(flavors: dict[str, Flavor]) -> dict[str, Flavor]:
    defaults = [name for name, flavor in flavors.items() if flavor.default]
    if len(defaults) > 1:
        raise PydanticCustomError(
            "multiple_default_flavors",
            "more than one default flavour: {names}",
            {"names": ", ".join(repr(name) for name in defaults)},
        )
    return flavors


@dataclass
class Config:
    __pydantic_config__ = FORBID_UNKNOWN_KEYS
    flavors: Annotated[dict[str, Flavor], AfterValidator(_check_single_default)] = (
        field(default_factory=dict)
    )


def _applies_to(flavor: Flavor, project_dir: Path) -> bool:
    return any(pattern.fullmatch(str(project_dir)) for pattern in flavor.when.path)


def select_flavor(cfg: Config, project_dir: Path) -> tuple[str, Flavor]:
    matching = [
        name for name, flavor in cfg.flavors.items() if _applies_to(flavor, project_dir)
    ]
    if len(matching) > 1:
        raise FlavorError(
            f"Several flavours apply to {project_dir}: "
            f"{', '.join(repr(name) for name in matching)}. "
            "Narrow their when.path so that only one matches."
        )
    if matching:
        return matching[0], cfg.flavors[matching[0]]
    for name, flavor in cfg.flavors.items():
        if flavor.default:
            return name, flavor
    raise FlavorError(
        f"No flavour applies to {project_dir}. Add a flavour whose when.path "
        "matches it, or mark one with default = true."
    )


def resolve_user(flavor: Flavor) -> ResolvedUser:
    calling_user = pwd.getpwuid(os.getuid())
    name = flavor.user.name or calling_user.pw_name
    uid = flavor.user.uid if flavor.user.uid is not None else calling_user.pw_uid
    group_name = flavor.user.group.name or name
    gid = flavor.user.group.gid if flavor.user.group.gid is not None else uid
    return ResolvedUser(
        name=name,
        uid=uid,
        shell=flavor.shell.name,
        group_name=group_name,
        gid=gid,
        extra_groups=flavor.user.extra_groups,
    )


def default_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "ask" / "flavors"


def flavor_path(directory: Path, name: str) -> Path:
    return directory / f"{name}.toml"


def _is_hidden(location: tuple[str | int, ...], index: int) -> bool:
    # Hide the levels that _flatten_options and agent.to_table add, and the
    # marker pydantic adds to invalid keys, so problems use the TOML paths.
    part = location[index]
    parent = location[index - 1] if index > 0 else None
    grandparent = location[index - 2] if index > 1 else None
    return (
        (part == _OPTIONS and (parent == "shell" or grandparent == agent.ENTRIES))
        or (part == agent.ENTRIES and parent == "agents")
        or part == "[key]"
    )


def _problem(details: ErrorDetails) -> str:
    location = details["loc"]
    path = ".".join(
        str(part)
        for index, part in enumerate(location)
        if not _is_hidden(location, index)
    )
    if details["type"] == "unexpected_keyword_argument":
        return f"{path}: unknown key"
    return f"{path}: {details['msg']}"


def _validation_problems(error: ValidationError) -> list[str]:
    return [_problem(details) for details in error.errors()]


def _validate[T](path: Path, data: dict, schema: type[T]) -> T:
    try:
        return TypeAdapter(schema).validate_python(data)
    except ValidationError as error:
        raise ConfigError(path, _validation_problems(error)) from None


def load_as[T](path: Path, schema: type[T]) -> T:
    return _validate(path, read_toml(path), schema)


def _load_flavor(path: Path, single: bool) -> Flavor:
    data = read_toml(path)
    if single:
        data = {"default": True} | data
    flavor = _validate(path, data, Flavor)
    for layer in flavor.layers.values():
        layer.taskfiles = resolve_taskfile_paths(path, layer.taskfiles)
    return flavor


def load(directory: Path) -> Config:
    if not directory.is_dir():
        return Config(flavors={})
    paths = sorted(directory.glob("*.toml"))
    flavors = {path.stem: _load_flavor(path, len(paths) == 1) for path in paths}
    return _validate(directory, {"flavors": flavors}, Config)
