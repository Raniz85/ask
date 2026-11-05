from pathlib import Path

import pytest

from ask.config import Config, Layer, default_path, load


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


def test_load_reads_layer_bind_mounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
