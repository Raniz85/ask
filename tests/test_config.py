import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from ask.config import (
    AgentOption,
    Config,
    ConfigError,
    Group,
    Layer,
    ResolvedUser,
    ShellOption,
    User,
    default_path,
    load,
    read_toml,
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


def test_load_rejects_unknown_fields_in_layers(tmp_path: Path) -> None:
    # given a layer declaring a field other than the known layer fields
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.base]\nide = "jetbrains-idea"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the unknown field is reported by its path
    assert error.value.problems == ["layers.base.ide: unknown key"]


def test_load_reads_layer_packages(tmp_path: Path) -> None:
    # given a layer declaring packages for multiple distributions
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[layers.base]\npackages.common = ["python"]\npackages.arch = ["zsh"]\n'
    )

    # when loading the config
    config = load(config_path)

    # then the layer's packages are read, keyed by distribution
    assert config == Config(
        layers={
            "base": Layer(
                bind_mounts=[], packages={"common": ["python"], "arch": ["zsh"]}
            )
        }
    )


def test_load_reads_layer_agents(tmp_path: Path) -> None:
    # given a layer declaring agents to install, with shared state enabled
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.base]\nagents = ["claude"]\nshared_state = true\n')

    # when loading the config
    config = load(config_path)

    # then the layer's agents are read as name-only options, and the
    # shared_state flag is read
    assert config == Config(
        layers={
            "base": Layer(
                bind_mounts=[],
                packages={},
                agents=[AgentOption(name="claude")],
                shared_state=True,
            )
        }
    )


def test_load_reads_layer_agents_with_full_options(tmp_path: Path) -> None:
    # given a layer declaring an agent with its full set of options
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[layers.base]\n"
        "agents = [\n"
        '  { name = "claude", claude_md = false, auth = true, skills = true, config = true },\n'
        "]\n"
    )

    # when loading the config
    config = load(config_path)

    # then the agent's name and its options table are both read
    assert config == Config(
        layers={
            "base": Layer(
                bind_mounts=[],
                packages={},
                agents=[
                    AgentOption(
                        name="claude",
                        options={
                            "claude_md": False,
                            "auth": True,
                            "skills": True,
                            "config": True,
                        },
                    )
                ],
            )
        }
    )


def test_load_defaults_layer_agents_and_shared_state(tmp_path: Path) -> None:
    # given a layer declaring neither agents nor shared_state
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.base]\npackages.arch = ["zsh"]\n')

    # when loading the config
    config = load(config_path)

    # then the layer has no agents, and shared state is left unset
    assert config == Config(
        layers={
            "base": Layer(
                bind_mounts=[],
                packages={"arch": ["zsh"]},
                agents=[],
                shared_state=None,
            )
        }
    )


def test_load_defaults_shell_to_bash(tmp_path: Path) -> None:
    # given a config file with no shell declared
    config_path = tmp_path / "config.toml"
    config_path.write_text("")

    # when loading the config
    config = load(config_path)

    # then shell defaults to bash with default options
    assert config.shell == ShellOption(name="bash", options={})


def test_load_reads_shell_from_toml(tmp_path: Path) -> None:
    # given a config file declaring a shell
    config_path = tmp_path / "config.toml"
    config_path.write_text('shell = "zsh"\n')

    # when loading the config
    config = load(config_path)

    # then the declared shell is read with default options
    assert config.shell == ShellOption(name="zsh", options={})


def test_load_reads_shell_options_from_toml(tmp_path: Path) -> None:
    # given a config file declaring a shell table with file options
    config_path = tmp_path / "config.toml"
    config_path.write_text('[shell]\nname = "zsh"\nzshrc = false\nzprofile = true\n')

    # when loading the config
    config = load(config_path)

    # then the shell name and its file options are read
    assert config.shell == ShellOption(
        name="zsh", options={"zshrc": False, "zprofile": True}
    )


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
    cfg = Config(shell=ShellOption(name="zsh"), user=User())

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
        shell=ShellOption(name="bash"),
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
    cfg = Config(shell=ShellOption(name="bash"), user=User(name="raniz", uid=1000))

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


def test_read_toml_reports_syntax_errors_with_the_offending_line(
    tmp_path: Path,
) -> None:
    # given a TOML file with an unterminated string on line 2
    path = tmp_path / "config.toml"
    path.write_text('a = 1\nshell = "zsh\nb = 2\n')

    # when reading it
    with pytest.raises(ConfigError) as error:
        read_toml(path)

    # then the error points at the line and column, with a caret under it
    assert str(error.value) == (
        f"invalid TOML in {path} at line 2, column 13: Illegal character '\\n'\n"
        '   2 | shell = "zsh\n'
        "     |             ^"
    )


def test_config_error_falls_back_to_the_bare_message_without_a_position(
    tmp_path: Path,
) -> None:
    # given a decode error message that carries no line or column
    path = tmp_path / "config.toml"
    path.write_text("")
    decode_error = tomllib.TOMLDecodeError("Something unexpected")

    # when reading a file that fails with that error
    with (
        patch("ask.config.tomllib.load", side_effect=decode_error),
        pytest.raises(ConfigError) as error,
    ):
        read_toml(path)

    # then the message is reported as-is, without a snippet
    assert str(error.value) == f"invalid TOML in {path}: Something unexpected"


def test_config_error_lists_every_problem() -> None:
    # given a configuration error with two problems
    error = ConfigError(Path("/cfg/config.toml"), ["shell.name: bad", "user.uid: bad"])

    # when rendering it
    message = str(error)

    # then each problem is listed on its own indented line under the file
    assert message == (
        "invalid configuration in /cfg/config.toml\n  shell.name: bad\n  user.uid: bad"
    )


def test_load_reports_syntax_errors_as_config_errors(tmp_path: Path) -> None:
    # given a global config file with a syntax error
    config_path = tmp_path / "config.toml"
    config_path.write_text("shell = \n")

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the error names the file
    assert error.value.path == config_path


def test_load_rejects_values_of_the_wrong_type(tmp_path: Path) -> None:
    # given a global config with a non-integer uid
    config_path = tmp_path / "config.toml"
    config_path.write_text('[user]\nuid = "1000"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the wrongly typed value is reported by its path
    assert error.value.problems == ["user.uid: Input should be a valid integer"]


def test_load_rejects_shell_options_of_the_wrong_type(tmp_path: Path) -> None:
    # given a shell table with a non-boolean option
    config_path = tmp_path / "config.toml"
    config_path.write_text('[shell]\nname = "zsh"\nzshrc = "yes"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the option is reported by the path it has in the TOML file
    assert error.value.problems == ["shell.zshrc: Input should be a valid boolean"]


def test_load_rejects_agent_options_of_the_wrong_type(tmp_path: Path) -> None:
    # given a layer agent table with a non-boolean option
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layers.base]\nagents = [{ name = "claude", auth = 1 }]\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the option is reported by the path it has in the TOML file
    assert error.value.problems == [
        "layers.base.agents.0.auth: Input should be a valid boolean"
    ]


def test_load_rejects_shell_tables_without_a_name(tmp_path: Path) -> None:
    # given a shell table that only sets options
    config_path = tmp_path / "config.toml"
    config_path.write_text("[shell]\nzshrc = true\n")

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the missing name is reported
    assert error.value.problems == ["shell.name: Field required"]


def test_load_reports_every_problem_at_once(tmp_path: Path) -> None:
    # given a global config with several unrelated problems
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'shell = 1\n[user]\nuid = "1000"\n[layers.base]\nbind_mount = []\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then all of them are reported together
    assert error.value.problems == [
        "shell: Input should be a valid string or table",
        "user.uid: Input should be a valid integer",
        "layers.base.bind_mount: unknown key",
    ]
