from pathlib import Path

import pytest

from ask.agent import AgentOption
from ask.config import Config, ConfigError, Layer
from ask.manifest import Manifest
from ask.shell import ShellOption
from ask.validation import (
    check_manifest,
    config_warnings,
    load_config,
    ManifestNotFoundError,
    load_manifest,
    manifest_warnings,
)


def test_load_config_returns_valid_configs(tmp_path: Path) -> None:
    # given a valid global config file
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n')

    # when loading it
    cfg = load_config(config_path)

    # then the config is returned
    assert cfg == Config(shell=ShellOption(name="zsh"))


def test_check_manifest_accepts_known_distributions_and_defined_layers() -> None:
    # given a manifest using a known distribution and a layer the config defines
    m = Manifest(distribution="arch", layers=["base"])
    cfg = Config(shell=ShellOption(name="bash"), layers={"base": Layer()})

    # when checking it
    problems = check_manifest(m, cfg)

    # then there are no problems
    assert problems == []


def test_check_manifest_rejects_unknown_distributions() -> None:
    # given a manifest using a distribution ask has no image for
    m = Manifest(distribution="gentoo")
    cfg = Config(shell=ShellOption(name="bash"))

    # when checking it
    problems = check_manifest(m, cfg)

    # then the distribution is reported along with the supported ones
    assert problems == ["distribution: unknown distribution 'gentoo' (known: arch)"]


def test_check_manifest_rejects_layers_the_config_does_not_define() -> None:
    # given a manifest using one defined and one undefined layer
    m = Manifest(distribution="arch", layers=["base", "rust"])
    cfg = Config(
        shell=ShellOption(name="bash"),
        layers={"python": Layer(), "base": Layer()},
    )

    # when checking it
    problems = check_manifest(m, cfg)

    # then the undefined layer is reported by its position, along with the
    # layers the global config defines
    assert problems == [
        "layers.1: layer 'rust' is not defined in the global config "
        "(known: base, python)"
    ]


def test_check_manifest_says_when_the_config_defines_no_layers() -> None:
    # given a manifest using a layer, and a config without any layers
    m = Manifest(distribution="arch", layers=["base"])
    cfg = Config(shell=ShellOption(name="bash"))

    # when checking it
    problems = check_manifest(m, cfg)

    # then the report says there are no layers to choose from
    assert problems == [
        "layers.0: layer 'base' is not defined in the global config (known: none)"
    ]


def test_load_manifest_reports_problems_against_the_file(tmp_path: Path) -> None:
    # given a manifest file using an unknown distribution
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "gentoo"\n')
    cfg = Config(shell=ShellOption(name="bash"))

    # when loading it
    with pytest.raises(ConfigError) as error:
        load_manifest(manifest_path, cfg)

    # then the problem is reported against the file
    assert error.value.path == manifest_path
    assert error.value.problems == [
        "distribution: unknown distribution 'gentoo' (known: arch)"
    ]


def test_load_manifest_returns_valid_manifests(tmp_path: Path) -> None:
    # given a valid manifest file
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\n')
    cfg = Config(shell=ShellOption(name="bash"))

    # when loading it
    m = load_manifest(manifest_path, cfg)

    # then the manifest is returned
    assert m == Manifest(distribution="arch")


def test_config_warnings_reports_options_on_removed_agents() -> None:
    # given a layer removing one agent with options and one without, and
    # enabling another agent with options
    cfg = Config(
        shell=ShellOption(name="bash"),
        layers={
            "base": Layer(
                agents=[
                    AgentOption(name="-claude", options={"auth": False}),
                    AgentOption(name="-codex"),
                    AgentOption(name="pi", options={"auth": False}),
                ]
            )
        },
    )

    # when collecting its warnings
    warnings = config_warnings(cfg)

    # then only the removal with options is reported, by its position
    assert warnings == [
        "layers.base.agents.0: options have no effect when removing agent 'claude'"
    ]


def test_manifest_warnings_reports_options_on_removed_agents() -> None:
    # given a manifest removing an agent with options
    m = Manifest(
        distribution="arch",
        agents=[AgentOption(name="-claude", options={"auth": False})],
    )

    # when collecting its warnings
    warnings = manifest_warnings(m)

    # then the removal with options is reported by its position
    assert warnings == ["agents.0: options have no effect when removing agent 'claude'"]


def test_load_config_prints_warnings_against_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a global config file removing an agent with options
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[layers.base]\nagents = [{ name = "-claude", auth = false }]\n'
    )

    # when loading it
    load_config(config_path)

    # then the warning is printed to stderr against the file
    assert capsys.readouterr().err == (
        f"ask: warning in {config_path}\n"
        "  layers.base.agents.0: options have no effect when removing agent "
        "'claude'\n"
    )


def test_load_manifest_prints_warnings_against_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a manifest file removing an agent with options
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text(
        'distribution = "arch"\nagents = [{ name = "-claude", auth = false }]\n'
    )
    cfg = Config(shell=ShellOption(name="bash"))

    # when loading it
    load_manifest(manifest_path, cfg)

    # then the warning is printed to stderr against the file
    assert capsys.readouterr().err == (
        f"ask: warning in {manifest_path}\n"
        "  agents.0: options have no effect when removing agent 'claude'\n"
    )


def test_load_manifest_prints_nothing_without_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a valid manifest file without anything to warn about
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\n')
    cfg = Config(shell=ShellOption(name="bash"))

    # when loading it
    load_manifest(manifest_path, cfg)

    # then nothing is printed to stderr
    assert capsys.readouterr().err == ""


def test_load_manifest_reports_a_missing_manifest(tmp_path: Path) -> None:
    # given a project directory without an ask.toml
    path = tmp_path / "ask.toml"

    # when loading the manifest
    with pytest.raises(ManifestNotFoundError) as error:
        load_manifest(path, Config())

    # then the error says where ask looked and what it needs
    assert str(error.value) == (
        f"No ask.toml found in {tmp_path}. "
        "Run ask from a project directory containing ask.toml."
    )


def test_check_manifest_reports_missing_bind_mount_sources(tmp_path: Path) -> None:
    # given a manifest bind mounting a path that exists and one that does not
    missing = tmp_path / "missing"
    m = Manifest(distribution="arch", bind_mounts=[tmp_path, missing])

    # when checking it
    problems = check_manifest(m, Config())

    # then only the missing path is reported, at its position in the manifest
    assert problems == [f"bind_mounts.1: path {missing} does not exist"]


def test_check_manifest_reports_missing_bind_mount_sources_from_used_layers(
    tmp_path: Path,
) -> None:
    # given a manifest using a layer that bind mounts a missing path
    missing = tmp_path / "missing"
    m = Manifest(distribution="arch", layers=["base"])

    # and a global config defining that layer and an unused layer with the
    # same missing path
    cfg = Config(
        layers={
            "base": Layer(bind_mounts=[tmp_path, missing]),
            "unused": Layer(bind_mounts=[missing]),
        }
    )

    # when checking the manifest
    problems = check_manifest(m, cfg)

    # then the missing path is reported once, against the used layer
    assert problems == [
        f"layers.0: bind mount {missing} from layer 'base' does not exist"
    ]
