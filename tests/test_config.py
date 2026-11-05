from pathlib import Path
from unittest.mock import patch

import pytest

from ask.config import (
    Config,
    Group,
    Layer,
    ResolvedUser,
    User,
    default_path,
    load,
    resolve_user,
)


def test_default_path_uses_xdg_config_path_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given XDG_CONFIG_PATH pointing at a custom location
    monkeypatch.setenv("XDG_CONFIG_PATH", str(tmp_path))

    # when resolving the default global config path
    path = default_path()

    # then it is ask/config.toml under that location
    assert path == tmp_path / "ask" / "config.toml"


def test_default_path_falls_back_to_dot_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given no XDG_CONFIG_PATH set
    monkeypatch.delenv("XDG_CONFIG_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    # when resolving the default global config path
    path = default_path()

    # then it falls back to ~/.config/ask/config.toml
    assert path == tmp_path / ".config" / "ask" / "config.toml"


def test_load_treats_a_missing_file_as_no_layers(tmp_path: Path) -> None:
    # given a global config path that doesn't exist
    config_path = tmp_path / "config.toml"

    # when loading the config
    config = load(config_path)

    # then there are no layers, rather than an error
    assert config == Config(layers={})


def test_load_defaults_to_no_layers(tmp_path: Path) -> None:
    # given a global config file with no layers declared
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when loading the config
    config = load(config_path)

    # then there are no layers
    assert config == Config(layers={})


def test_load_reads_layer_bind_mounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a global config file declaring a layer with a home-relative bind mount
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.python]\nbind_mounts = ["~/.cache/uv"]\n')

    # when loading the config
    config = load(config_path)

    # then the layer's bind mounts are read, with "~" expanded
    assert config == Config(
        layers={"python": Layer(bind_mounts=[tmp_path / ".cache" / "uv"])}
    )


def test_load_ignores_unknown_fields_in_layers(tmp_path: Path) -> None:
    # given a layer declaring fields other than bind_mounts
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.base]\npackages.arch = ["zsh"]\n')

    # when loading the config
    config = load(config_path)

    # then the unknown fields are ignored and the layer defaults to no bind mounts
    assert config == Config(layers={"base": Layer(bind_mounts=[])})


def test_load_defaults_shell_to_bash(tmp_path: Path) -> None:
    # given a config file with no shell declared
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when loading the config
    config = load(config_path)

    # then shell defaults to bash
    assert config.shell == "bash"


def test_load_reads_shell_from_toml(tmp_path: Path) -> None:
    # given a config file declaring a shell
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n')

    # when loading the config
    config = load(config_path)

    # then the declared shell is read
    assert config.shell == "zsh"


def test_load_defaults_user_to_unset(tmp_path: Path) -> None:
    # given a config file with no user declared
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when loading the config
    config = load(config_path)

    # then the user is unset throughout, to be resolved against the calling user later
    assert config.user == User(
        name=None, uid=None, extra_groups=[], group=Group(name=None, gid=None)
    )


def test_load_reads_user_from_toml(tmp_path: Path) -> None:
    # given a config file declaring a user with a group and extra groups
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[user]\n"
        'name = "raniz"\n'
        "uid = 1000\n"
        'extra_groups = ["wheel"]\n'
        "[user.group]\n"
        'name = "raniz"\n'
        "gid = 1000\n"
    )

    # when loading the config
    config = load(config_path)

    # then the declared user is read in full
    assert config.user == User(
        name="raniz",
        uid=1000,
        extra_groups=["wheel"],
        group=Group(name="raniz", gid=1000),
    )


def _mock_pwent(name: str, uid: int):
    pwent = type("MockPwent", (), {"pw_name": name, "pw_uid": uid})()
    return patch("ask.config.pwd.getpwuid", return_value=pwent)


def test_resolve_user_mirrors_the_calling_user_when_fully_unset() -> None:
    # given a config with no user declared, and a calling host user
    cfg = Config(shell="zsh", user=User())

    # when resolving the user
    with _mock_pwent("hostuser", 1234):
        resolved = resolve_user(cfg)

    # then the user mirrors the calling host user, with a private group of the
    # same name and matching gid
    assert resolved == ResolvedUser(
        name="hostuser",
        uid=1234,
        shell="zsh",
        group_name="hostuser",
        gid=1234,
        extra_groups=[],
    )


def test_resolve_user_uses_declared_fields_over_the_calling_user() -> None:
    # given a config declaring a full user and group
    cfg = Config(
        shell="bash",
        user=User(
            name="raniz",
            uid=1000,
            extra_groups=["wheel"],
            group=Group(name="raniz", gid=1000),
        ),
    )

    # when resolving the user
    with _mock_pwent("hostuser", 1234):
        resolved = resolve_user(cfg)

    # then the declared fields are used verbatim, ignoring the calling host user
    assert resolved == ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=["wheel"],
    )


def test_resolve_user_defaults_group_to_a_private_group_of_the_declared_user() -> None:
    # given a config declaring a user but no group
    cfg = Config(shell="bash", user=User(name="raniz", uid=1000))

    # when resolving the user
    with _mock_pwent("hostuser", 1234):
        resolved = resolve_user(cfg)

    # then the group defaults to the declared user's own name and uid, not the
    # calling host user's
    assert resolved == ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )
