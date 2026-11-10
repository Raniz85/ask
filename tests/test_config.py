import re
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from ask.agent import AgentOption
from ask.config import (
    Config,
    ConfigError,
    Flavor,
    FlavorError,
    FlavorWhen,
    Group,
    Layer,
    LayerWhen,
    User,
    default_path,
    load,
    read_toml,
    resolve_user,
    select_flavor,
)
from ask.shell import ShellOption
from ask.user import ResolvedUser


def test_default_path_uses_xdg_config_home_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given XDG_CONFIG_HOME pointing at a custom location
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # when resolving the default global config path
    path = default_path()

    # then it is ask/config.toml under that location
    assert path == tmp_path / "ask" / "config.toml"


def test_default_path_falls_back_to_dot_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given no XDG_CONFIG_HOME set
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    # when resolving the default global config path
    path = default_path()

    # then it falls back to ~/.config/ask/config.toml
    assert path == tmp_path / ".config" / "ask" / "config.toml"


def test_default_path_treats_an_empty_xdg_config_home_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given XDG_CONFIG_HOME set to an empty value
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    # when resolving the default global config path
    path = default_path()

    # then it falls back to ~/.config/ask/config.toml
    assert path == tmp_path / ".config" / "ask" / "config.toml"


def _config_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_load_treats_a_missing_file_as_no_flavors(tmp_path: Path) -> None:
    # given a global config path that doesn't exist
    config_path = tmp_path / "config.toml"

    # when loading the config
    config = load(config_path)

    # then there are no flavours, rather than an error
    assert config == Config(flavors={})


def test_load_defaults_to_no_flavors(tmp_path: Path) -> None:
    # given a global config file with no flavours declared
    config_path = _config_file(tmp_path, "")

    # when loading the config
    config = load(config_path)

    # then there are no flavours
    assert config == Config(flavors={})


def test_load_reads_an_inline_flavor(tmp_path: Path) -> None:
    # given a global config declaring a flavour in place
    config_path = _config_file(tmp_path, '[flavors.arch]\ndistribution = "arch"\n')

    # when loading the config
    config = load(config_path)

    # then the flavour is read with its defaults
    assert config == Config(flavors={"arch": Flavor(distribution="arch")})


def test_load_defaults_a_flavor(tmp_path: Path) -> None:
    # given a flavour declaring only its distribution
    config_path = _config_file(tmp_path, '[flavors.arch]\ndistribution = "arch"\n')

    # when loading the config
    config = load(config_path)

    # then the flavour is not the default, has no path conditions, uses bash,
    # mirrors the calling user and has no layers
    assert config.flavors["arch"] == Flavor(
        distribution="arch",
        default=False,
        when=FlavorWhen(path=[]),
        shell=ShellOption(name="bash", options={}),
        user=User(
            name=None, uid=None, extra_groups=[], group=Group(name=None, gid=None)
        ),
        layers={},
    )


def test_load_requires_a_flavor_distribution(tmp_path: Path) -> None:
    # given a flavour without a distribution
    config_path = _config_file(tmp_path, '[flavors.arch]\nshell = "zsh"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the missing distribution is reported by its path
    assert error.value.problems == ["flavors.arch.distribution: Field required"]


def test_load_rejects_unknown_distributions(tmp_path: Path) -> None:
    # given a flavour with a distribution Ask does not know
    config_path = _config_file(tmp_path, '[flavors.gentoo]\ndistribution = "gentoo"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the distribution is reported together with the known ones
    assert error.value.problems == [
        "flavors.gentoo.distribution: unknown distribution 'gentoo' (known: arch)"
    ]


def test_load_reads_a_flavor_from_a_file_next_to_the_config(tmp_path: Path) -> None:
    # given a global config referring to a flavour file by a relative path
    config_path = _config_file(tmp_path, 'flavors.arch = "arch.toml"\n')

    # and the flavour file next to it
    (tmp_path / "arch.toml").write_text('distribution = "arch"\nshell = "zsh"\n')

    # when loading the config
    config = load(config_path)

    # then the flavour is read from that file
    assert config == Config(
        flavors={"arch": Flavor(distribution="arch", shell=ShellOption(name="zsh"))}
    )


def test_load_reports_problems_in_a_flavor_file_against_that_file(
    tmp_path: Path,
) -> None:
    # given a global config referring to a flavour file
    config_path = _config_file(tmp_path, 'flavors.arch = "arch.toml"\n')

    # and a flavour file with an unknown key
    flavor_path = tmp_path / "arch.toml"
    flavor_path.write_text('distribution = "arch"\nide = "vscode"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the problem is reported against the flavour file, by its path in that file
    assert (error.value.path, error.value.problems) == (
        flavor_path,
        ["ide: unknown key"],
    )


def test_load_reports_a_missing_flavor_file(tmp_path: Path) -> None:
    # given a global config referring to a flavour file that does not exist
    config_path = _config_file(tmp_path, 'flavors.arch = "arch.toml"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the missing file is reported against its own path
    assert (error.value.path, error.value.problems) == (
        tmp_path / "arch.toml",
        ["cannot read file: No such file or directory"],
    )


def test_load_reads_the_default_flavor(tmp_path: Path) -> None:
    # given a flavour marked as the default
    config_path = _config_file(
        tmp_path, '[flavors.arch]\ndistribution = "arch"\ndefault = true\n'
    )

    # when loading the config
    config = load(config_path)

    # then the flavour is read as the default
    assert config.flavors["arch"].default is True


def test_load_rejects_more_than_one_default_flavor(tmp_path: Path) -> None:
    # given two flavours both marked as the default
    config_path = _config_file(
        tmp_path,
        '[flavors.one]\ndistribution = "arch"\ndefault = true\n'
        '[flavors.two]\ndistribution = "arch"\ndefault = true\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then both default flavours are named
    assert error.value.problems == [
        "flavors: more than one default flavour: 'one', 'two'"
    ]


def test_load_expands_the_home_directory_in_flavor_path_conditions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a home directory whose path contains regex metacharacters
    home = tmp_path / "home.d"
    monkeypatch.setenv("HOME", str(home))

    # and a flavour applying to a home-relative path regex
    config_path = _config_file(
        tmp_path,
        '[flavors.arch]\ndistribution = "arch"\nwhen.path = ["~/src/.*"]\n',
    )

    # when loading the config
    config = load(config_path)

    # then "~" is replaced by the escaped home directory, leaving the rest a regex
    assert config.flavors["arch"].when == FlavorWhen(
        path=[re.compile(re.escape(str(home)) + "/src/.*")]
    )


def test_load_rejects_invalid_flavor_path_regexes(tmp_path: Path) -> None:
    # given a flavour path condition that is not a valid regex
    config_path = _config_file(
        tmp_path, '[flavors.arch]\ndistribution = "arch"\nwhen.path = ["~/src/("]\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the regex is reported by its path
    assert error.value.problems == [
        "flavors.arch.when.path.0: Input should be a valid regular expression"
    ]


def test_load_reads_the_flavor_shell(tmp_path: Path) -> None:
    # given a flavour declaring a shell by name
    config_path = _config_file(
        tmp_path, '[flavors.arch]\ndistribution = "arch"\nshell = "zsh"\n'
    )

    # when loading the config
    config = load(config_path)

    # then the declared shell is read with default options
    assert config.flavors["arch"].shell == ShellOption(name="zsh", options={})


def test_load_reads_the_flavor_shell_options(tmp_path: Path) -> None:
    # given a flavour declaring a shell table with file options
    config_path = _config_file(
        tmp_path,
        '[flavors.arch]\ndistribution = "arch"\n'
        '[flavors.arch.shell]\nname = "zsh"\nzshrc = false\nzprofile = true\n',
    )

    # when loading the config
    config = load(config_path)

    # then the shell name and its file options are read
    assert config.flavors["arch"].shell == ShellOption(
        name="zsh", options={"zshrc": False, "zprofile": True}
    )


def test_load_reads_the_flavor_user(tmp_path: Path) -> None:
    # given a flavour declaring a user with a group and extra groups
    config_path = _config_file(
        tmp_path,
        '[flavors.arch]\ndistribution = "arch"\n'
        "[flavors.arch.user]\n"
        'name = "raniz"\n'
        "uid = 1000\n"
        'extra_groups = ["wheel"]\n'
        "[flavors.arch.user.group]\n"
        'name = "raniz"\n'
        "gid = 1000\n",
    )

    # when loading the config
    config = load(config_path)

    # then the declared user is read in full
    assert config.flavors["arch"].user == User(
        name="raniz",
        uid=1000,
        extra_groups=["wheel"],
        group=Group(name="raniz", gid=1000),
    )


def _flavor_with_layers(tmp_path: Path, layers: str) -> Path:
    return _config_file(tmp_path, '[flavors.arch]\ndistribution = "arch"\n' + layers)


def test_load_defaults_a_layer(tmp_path: Path) -> None:
    # given a flavour declaring an empty base layer
    config_path = _flavor_with_layers(tmp_path, "[flavors.arch.layers.base]\n")

    # when loading the config
    config = load(config_path)

    # then the layer has no bind mounts, packages or agents, order 0 and no
    # conditions
    assert config.flavors["arch"].layers == {
        "base": Layer(bind_mounts=[], packages=[], agents=[], order=0, when=None)
    }


def test_load_reads_layer_bind_mounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a layer with a home-relative bind mount
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = _flavor_with_layers(
        tmp_path, '[flavors.arch.layers.python]\nbind_mounts = ["~/.cache/uv"]\n'
    )

    # when loading the config
    config = load(config_path)

    # then the layer's bind mounts are read, with "~" expanded
    assert config.flavors["arch"].layers == {
        "python": Layer(bind_mounts=[tmp_path / ".cache" / "uv"])
    }


def test_load_reads_layer_packages(tmp_path: Path) -> None:
    # given a layer declaring packages
    config_path = _flavor_with_layers(
        tmp_path, '[flavors.arch.layers.base]\npackages = ["zsh", "aur:antigen"]\n'
    )

    # when loading the config
    config = load(config_path)

    # then the layer's packages are read as a plain list
    assert config.flavors["arch"].layers == {
        "base": Layer(packages=["zsh", "aur:antigen"])
    }


def test_load_rejects_layer_packages_keyed_by_distribution(tmp_path: Path) -> None:
    # given a layer declaring packages per distribution
    config_path = _flavor_with_layers(
        tmp_path, '[flavors.arch.layers.base]\npackages.arch = ["zsh"]\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the packages are reported as not being a list
    assert error.value.problems == [
        "flavors.arch.layers.base.packages: Input should be a valid list"
    ]


def test_load_reads_layer_agents(tmp_path: Path) -> None:
    # given a layer declaring agents to install
    config_path = _flavor_with_layers(
        tmp_path, '[flavors.arch.layers.base]\nagents = ["claude"]\n'
    )

    # when loading the config
    config = load(config_path)

    # then the layer's agents are read as name-only options
    assert config.flavors["arch"].layers == {
        "base": Layer(agents=[AgentOption(name="claude")])
    }


def test_load_reads_layer_agents_with_full_options(tmp_path: Path) -> None:
    # given a layer declaring an agent with its full set of options
    config_path = _flavor_with_layers(
        tmp_path,
        "[flavors.arch.layers.base]\n"
        "agents = [\n"
        '  { name = "claude", claude_md = false, auth = true, skills = true, config = true },\n'
        "]\n",
    )

    # when loading the config
    config = load(config_path)

    # then the agent's name and its options table are both read
    assert config.flavors["arch"].layers == {
        "base": Layer(
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


def test_load_reads_layer_order_and_conditions(tmp_path: Path) -> None:
    # given a layer with an order and a file condition
    config_path = _flavor_with_layers(
        tmp_path,
        "[flavors.arch.layers.python]\n"
        "order = 10\n"
        'when.files = ["pyproject.toml", "uv.lock"]\n',
    )

    # when loading the config
    config = load(config_path)

    # then the order and the file names are read
    assert config.flavors["arch"].layers == {
        "python": Layer(order=10, when=LayerWhen(files=["pyproject.toml", "uv.lock"]))
    }


def test_load_rejects_conditions_on_the_base_layer(tmp_path: Path) -> None:
    # given a base layer with a file condition
    config_path = _flavor_with_layers(
        tmp_path, '[flavors.arch.layers.base]\nwhen.files = ["pyproject.toml"]\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the condition is reported, since the base layer is always applied
    assert error.value.problems == [
        (
            "flavors.arch.layers: the base layer is always applied and cannot "
            "have when conditions"
        )
    ]


def test_load_rejects_tool_managers_in_a_layer(tmp_path: Path) -> None:
    # given a layer declaring tool managers
    config_path = _flavor_with_layers(
        tmp_path, '[flavors.arch.layers.base]\ntool_managers = ["mise"]\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then tool_managers is reported as an unknown key
    assert error.value.problems == [
        "flavors.arch.layers.base.tool_managers: unknown key"
    ]


def test_load_accepts_valid_service_states(tmp_path: Path) -> None:
    # given a flavour with valid service states
    for state in ["enabled", "disabled", "masked"]:
        # Create a fresh directory for each flavor to avoid multiple defaults
        flavor_dir = tmp_path / f"flavors_{state}"
        flavor_dir.mkdir()
        flavor_file = flavor_dir / "arch.toml"
        flavor_file.write_text(f"""
            distribution = "arch"
            default = true
            [layers.base]
            services."sshd.service" = "{state}"
            """)

        # when loading the config
        config = load(flavor_dir)

        # then it succeeds and the service state is preserved
        assert config.flavors["arch"].layers["base"].services["sshd.service"] == state


def test_load_rejects_invalid_service_states(tmp_path: Path) -> None:
    # given a flavour with an invalid service state
    flavors_dir = _flavor_file(
        tmp_path,
        """
        distribution = "arch"
        default = true
        [layers.base]
        services."sshd.service" = "invalid_state"
        """,
    )

    # when loading the config
    # then it raises a ConfigError
    with pytest.raises(ConfigError) as excinfo:
        load(flavors_dir)
    assert "Invalid service state 'invalid_state' for service 'sshd.service'" in str(
        excinfo.value
    )


def test_load_rejects_unknown_fields_in_layers(tmp_path: Path) -> None:
    # given a layer declaring a field other than the known layer fields
    config_path = _flavor_with_layers(
        tmp_path, "[flavors.arch.layers.base]\nshared_state = true\n"
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the unknown field is reported by its path
    assert error.value.problems == [
        "flavors.arch.layers.base.shared_state: unknown key"
    ]


def test_load_rejects_top_level_layers(tmp_path: Path) -> None:
    # given a global config declaring a layer outside any flavour
    config_path = _config_file(tmp_path, '[layers.base]\npackages = ["zsh"]\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the layers table is reported as an unknown key
    assert error.value.problems == ["layers: unknown key"]


def _mock_pwent(name: str, uid: int):
    pwent = type("MockPwent", (), {"pw_name": name, "pw_uid": uid})()
    return patch("ask.config.pwd.getpwuid", return_value=pwent)


def test_resolve_user_mirrors_the_calling_user_when_fully_unset() -> None:
    # given a flavour with no user declared, and a calling host user
    flavor = Flavor(distribution="arch", shell=ShellOption(name="zsh"), user=User())

    # when resolving the user
    with _mock_pwent("hostuser", 1234):
        resolved = resolve_user(flavor)

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
    # given a flavour declaring a full user and group
    flavor = Flavor(
        distribution="arch",
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
        resolved = resolve_user(flavor)

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
    # given a flavour declaring a user but no group
    flavor = Flavor(
        distribution="arch",
        shell=ShellOption(name="bash"),
        user=User(name="raniz", uid=1000),
    )

    # when resolving the user
    with _mock_pwent("hostuser", 1234):
        resolved = resolve_user(flavor)

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
        f"Invalid TOML in {path} at line 2, column 13: Illegal character '\\n'\n"
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
    assert str(error.value) == f"Invalid TOML in {path}: Something unexpected"


def test_config_error_lists_every_problem() -> None:
    # given a configuration error with two problems
    error = ConfigError(Path("/cfg/config.toml"), ["shell.name: bad", "user.uid: bad"])

    # when rendering it
    message = str(error)

    # then each problem is listed on its own indented line under the file
    assert message == (
        "Invalid configuration in /cfg/config.toml:\n  shell.name: bad\n  user.uid: bad"
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
    # given a flavour user with a non-integer uid
    config_path = _config_file(
        tmp_path,
        '[flavors.arch]\ndistribution = "arch"\n[flavors.arch.user]\nuid = "1000"\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the wrongly typed value is reported by its path
    assert error.value.problems == [
        "flavors.arch.user.uid: Input should be a valid integer"
    ]


def test_load_rejects_shell_options_of_the_wrong_type(tmp_path: Path) -> None:
    # given a flavour shell table with a non-boolean option
    config_path = _config_file(
        tmp_path,
        '[flavors.arch]\ndistribution = "arch"\n'
        '[flavors.arch.shell]\nname = "zsh"\nzshrc = "yes"\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the option is reported by the path it has in the TOML file
    assert error.value.problems == [
        "flavors.arch.shell.zshrc: Input should be a valid boolean"
    ]


def test_load_rejects_agent_options_of_the_wrong_type(tmp_path: Path) -> None:
    # given a layer agent table with a non-boolean option
    config_path = _flavor_with_layers(
        tmp_path,
        '[flavors.arch.layers.base]\nagents = [{ name = "claude", auth = 1 }]\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the option is reported by the path it has in the TOML file
    assert error.value.problems == [
        "flavors.arch.layers.base.agents.0.auth: Input should be a valid boolean"
    ]


def test_load_rejects_shell_tables_without_a_name(tmp_path: Path) -> None:
    # given a flavour shell table that only sets options
    config_path = _config_file(
        tmp_path,
        '[flavors.arch]\ndistribution = "arch"\n[flavors.arch.shell]\nzshrc = true\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then the missing name is reported
    assert error.value.problems == ["flavors.arch.shell.name: Field required"]


def test_load_reports_every_problem_at_once(tmp_path: Path) -> None:
    # given a global config with several unrelated problems
    config_path = _config_file(
        tmp_path,
        '[flavors.arch]\ndistribution = "arch"\nshell = 1\n'
        '[flavors.arch.user]\nuid = "1000"\n'
        "[flavors.arch.layers.base]\nbind_mount = []\n",
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(config_path)

    # then all of them are reported together
    assert error.value.problems == [
        "flavors.arch.shell: Input should be a valid string or table",
        "flavors.arch.user.uid: Input should be a valid integer",
        "flavors.arch.layers.base.bind_mount: unknown key",
    ]


def test_read_toml_reports_files_that_cannot_be_read(tmp_path: Path) -> None:
    # given a configuration path that is a directory rather than a file
    path = tmp_path / "ask.toml"
    path.mkdir()

    # when reading it
    with pytest.raises(ConfigError) as error:
        read_toml(path)

    # then the error names the file and why it cannot be read
    assert str(error.value) == (
        f"Invalid configuration in {path}:\n  cannot read file: Is a directory"
    )


def test_read_toml_reports_files_that_are_not_utf8(tmp_path: Path) -> None:
    # given a configuration file with bytes that are not valid UTF-8
    path = tmp_path / "ask.toml"
    path.write_bytes(b'distribution = "\xff"\n')

    # when reading it
    with pytest.raises(ConfigError) as error:
        read_toml(path)

    # then the error names the file and that it is not UTF-8
    assert str(error.value) == (
        f"Invalid configuration in {path}:\n  file is not valid UTF-8"
    )


def _flavor_for(*paths: Path, default: bool = False) -> Flavor:
    return Flavor(
        distribution="arch",
        default=default,
        when=FlavorWhen(path=[re.compile(re.escape(str(path))) for path in paths]),
    )


def test_select_flavor_picks_the_flavor_whose_path_matches_the_project() -> None:
    # given a default flavour and a flavour applying to the project's path
    project_dir = Path("/home/raniz/src/apt")
    matching = _flavor_for(project_dir)
    cfg = Config(flavors={"arch": _flavor_for(default=True), "debian": matching})

    # when selecting the flavour for the project
    selected = select_flavor(cfg, project_dir)

    # then the matching flavour is selected over the default
    assert selected == ("debian", matching)


def test_select_flavor_falls_back_to_the_default_flavor() -> None:
    # given a default flavour and a flavour applying to another path
    default = _flavor_for(default=True)
    cfg = Config(
        flavors={
            "arch": default,
            "debian": _flavor_for(Path("/home/raniz/src/debconf")),
        }
    )

    # when selecting the flavour for a project no path matches
    selected = select_flavor(cfg, Path("/home/raniz/src/ask"))

    # then the default flavour is selected
    assert selected == ("arch", default)


def test_select_flavor_requires_the_whole_path_to_match() -> None:
    # given a default flavour and a flavour applying to a path that is a prefix
    # of the project's path
    default = _flavor_for(default=True)
    cfg = Config(
        flavors={"arch": default, "debian": _flavor_for(Path("/home/raniz/src/apt"))}
    )

    # when selecting the flavour for the project
    selected = select_flavor(cfg, Path("/home/raniz/src/apt-tools"))

    # then the prefix does not count as a match, and the default is selected
    assert selected == ("arch", default)


def test_select_flavor_rejects_several_matching_flavors() -> None:
    # given two flavours both applying to the project's path
    project_dir = Path("/home/raniz/src/apt")
    cfg = Config(
        flavors={"one": _flavor_for(project_dir), "two": _flavor_for(project_dir)}
    )

    # when selecting the flavour for the project
    with pytest.raises(FlavorError) as error:
        select_flavor(cfg, project_dir)

    # then both flavours are named
    assert str(error.value) == (
        "Several flavours apply to /home/raniz/src/apt: 'one', 'two'. "
        "Narrow their when.path so that only one matches."
    )


def test_select_flavor_rejects_projects_no_flavor_applies_to() -> None:
    # given only a flavour applying to another path, and no default
    cfg = Config(flavors={"debian": _flavor_for(Path("/home/raniz/src/debconf"))})

    # when selecting the flavour for a project no path matches
    with pytest.raises(FlavorError) as error:
        select_flavor(cfg, Path("/home/raniz/src/ask"))

    # then the error says that no flavour applies
    assert str(error.value) == (
        "No flavour applies to /home/raniz/src/ask. Add a flavour whose when.path "
        "matches it, or mark one with default = true."
    )
