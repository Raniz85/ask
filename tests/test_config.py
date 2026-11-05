from pathlib import Path

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
