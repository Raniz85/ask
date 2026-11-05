import os
import pwd
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Layer:
    bind_mounts: list[Path] = field(default_factory=list)
    packages: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Group:
    name: str | None = None
    gid: int | None = None


@dataclass
class User:
    name: str | None = None
    uid: int | None = None
    extra_groups: list[str] = field(default_factory=list)
    group: Group = field(default_factory=Group)


@dataclass
class Config:
    shell: str = "bash"
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
        shell=cfg.shell,
        group_name=group_name,
        gid=gid,
        extra_groups=cfg.user.extra_groups,
    )


def default_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_PATH", str(Path.home() / ".config"))
    return Path(config_home) / "ask" / "config.toml"


def load(path: Path) -> Config:
    if not path.exists():
        return Config(layers={})
    with path.open("rb") as f:
        data = tomllib.load(f)
    layers = {
        name: Layer(
            bind_mounts=[
                Path(p).expanduser() for p in layer_data.get("bind_mounts", [])
            ],
            packages={
                distro: list(pkgs)
                for distro, pkgs in layer_data.get("packages", {}).items()
            },
        )
        for name, layer_data in data.get("layers", {}).items()
    }

    user_data = data.get("user", {})
    group_data = user_data.get("group", {})
    user = User(
        name=user_data.get("name"),
        uid=user_data.get("uid"),
        extra_groups=list(user_data.get("extra_groups", [])),
        group=Group(name=group_data.get("name"), gid=group_data.get("gid")),
    )

    return Config(shell=data.get("shell", "bash"), user=user, layers=layers)
