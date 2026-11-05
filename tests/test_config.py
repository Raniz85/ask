from pathlib import Path

import pytest

from ask.config import Config, load


def test_load_reads_distribution_from_toml(tmp_path: Path) -> None:
    # given a config file declaring a distribution
    config_path = tmp_path / "ask.toml"
    config_path.write_text('distribution = "arch"\n')

    # when loading the config
    config = load(config_path)

    # then the distribution is available on the result
    assert config == Config(distribution="arch")


def test_load_ignores_unknown_fields(tmp_path: Path) -> None:
    # given a config file with an unknown field alongside the distribution
    config_path = tmp_path / "ask.toml"
    config_path.write_text('distribution = "arch"\nlayers = ["base"]\n')

    # when loading the config
    config = load(config_path)

    # then the unknown field is ignored and distribution is still read
    assert config == Config(distribution="arch")


def test_load_defaults_bind_mounts_to_empty_list(tmp_path: Path) -> None:
    # given a config file with no bind_mounts declared
    config_path = tmp_path / "ask.toml"
    config_path.write_text('distribution = "arch"\n')

    # when loading the config
    config = load(config_path)

    # then bind_mounts defaults to an empty list
    assert config.bind_mounts == []


def test_load_reads_bind_mounts_from_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # given a config file declaring bind_mounts, one using a home-relative path
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = tmp_path / "ask.toml"
    config_path.write_text('distribution = "arch"\nbind_mounts = ["~/foo", "/abs/path"]\n')

    # when loading the config
    config = load(config_path)

    # then each path is read, with "~" expanded against the home directory
    assert config.bind_mounts == [tmp_path / "foo", Path("/abs/path")]
