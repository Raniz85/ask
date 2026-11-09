from pathlib import Path

import pytest

from ask.config import AgentOption, Config, ConfigError, Layer, ShellOption
from ask.manifest import Manifest
from ask.validation import check_config, check_manifest, load_config, load_manifest


def test_check_config_accepts_known_shells_and_agents_with_their_options() -> None:
    # given a config using a known shell and agent, with options they support
    cfg = Config(
        shell=ShellOption(name="zsh", options={"zprofile": True}),
        layers={
            "base": Layer(agents=[AgentOption(name="claude", options={"auth": False})])
        },
    )

    # when checking it
    problems = check_config(cfg)

    # then there are no problems
    assert problems == []


def test_check_config_rejects_unknown_shells() -> None:
    # given a config using a shell ask doesn't support
    cfg = Config(shell=ShellOption(name="foosh"))

    # when checking it
    problems = check_config(cfg)

    # then the shell is reported along with the supported ones
    assert problems == [
        "shell.name: unknown shell 'foosh' (known: bash, elvish, fish, ksh, tcsh, zsh)"
    ]


def test_check_config_rejects_options_the_shell_does_not_have() -> None:
    # given a config enabling a bash option for zsh
    cfg = Config(shell=ShellOption(name="zsh", options={"bashrc": True}))

    # when checking it
    problems = check_config(cfg)

    # then the option is reported along with the ones zsh supports
    assert problems == [
        "shell.bashrc: unknown option for zsh (known: zprofile, zshenv, zshrc)"
    ]


def test_check_config_rejects_unknown_agents() -> None:
    # given a layer using an agent ask doesn't support
    cfg = Config(
        shell=ShellOption(name="bash"),
        layers={
            "base": Layer(agents=[AgentOption(name="claude"), AgentOption(name="hal")])
        },
    )

    # when checking it
    problems = check_config(cfg)

    # then the agent is reported by its position along with the supported ones
    assert problems == [
        "layers.base.agents.1.name: unknown agent 'hal' "
        "(known: claude, codex, opencode, pi)"
    ]


def test_check_config_rejects_options_the_agent_does_not_have() -> None:
    # given a layer enabling an opencode option for claude
    cfg = Config(
        shell=ShellOption(name="bash"),
        layers={
            "base": Layer(
                agents=[AgentOption(name="claude", options={"agents_md": True})]
            )
        },
    )

    # when checking it
    problems = check_config(cfg)

    # then the option is reported along with the ones claude supports
    assert problems == [
        "layers.base.agents.0.agents_md: unknown option for claude "
        "(known: auth, claude_md, config, skills)"
    ]


def test_load_config_reports_problems_against_the_file(tmp_path: Path) -> None:
    # given a global config file using an unknown shell
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "foosh"\n')

    # when loading it
    with pytest.raises(ConfigError) as error:
        load_config(config_path)

    # then the problem is reported against the file
    assert error.value.path == config_path
    assert error.value.problems == [
        "shell.name: unknown shell 'foosh' (known: bash, elvish, fish, ksh, tcsh, zsh)"
    ]


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


def test_check_manifest_rejects_unknown_agents_and_their_options() -> None:
    # given a manifest using an agent ask doesn't support, and a known agent
    # with an option it doesn't have
    m = Manifest(
        distribution="arch",
        agents=[
            AgentOption(name="hal"),
            AgentOption(name="claude", options={"telepathy": True}),
        ],
    )
    cfg = Config(shell=ShellOption(name="bash"))

    # when checking it
    problems = check_manifest(m, cfg)

    # then both are reported by their position in the manifest's agents
    assert problems == [
        "agents.0.name: unknown agent 'hal' (known: claude, codex, opencode, pi)",
        "agents.1.telepathy: unknown option for claude "
        "(known: auth, claude_md, config, skills)",
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
