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
    default_dir,
    load,
    read_toml,
    resolve_user,
    select_flavor,
)
from ask.shell import ShellOption
from ask.user import ResolvedUser


def test_default_dir_uses_xdg_config_home_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given XDG_CONFIG_HOME pointing at a custom location
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # when resolving the default flavours directory
    path = default_dir()

    # then it is ask/flavors under that location
    assert path == tmp_path / "ask" / "flavors"


def test_default_dir_falls_back_to_dot_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given no XDG_CONFIG_HOME set
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    # when resolving the default flavours directory
    path = default_dir()

    # then it falls back to ~/.config/ask/flavors
    assert path == tmp_path / ".config" / "ask" / "flavors"


def test_default_dir_treats_an_empty_xdg_config_home_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given XDG_CONFIG_HOME set to an empty value
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    # when resolving the default flavours directory
    path = default_dir()

    # then it falls back to ~/.config/ask/flavors
    assert path == tmp_path / ".config" / "ask" / "flavors"


def _flavor_file(tmp_path: Path, text: str, name: str = "arch") -> Path:
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir(exist_ok=True)
    (flavors_dir / f"{name}.toml").write_text(text)
    return flavors_dir


def test_load_treats_a_missing_directory_as_no_flavors(tmp_path: Path) -> None:
    # given a flavours directory that doesn't exist
    flavors_dir = tmp_path / "flavors"

    # when loading the config
    config = load(flavors_dir)

    # then there are no flavours, rather than an error
    assert config == Config(flavors={})


def test_load_defaults_to_no_flavors(tmp_path: Path) -> None:
    # given an empty flavours directory
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()

    # when loading the config
    config = load(flavors_dir)

    # then there are no flavours
    assert config == Config(flavors={})


def test_load_names_each_flavor_after_its_file(tmp_path: Path) -> None:
    # given two flavour files
    _flavor_file(tmp_path, 'distribution = "arch"\nshell = "zsh"\n', name="work")
    flavors_dir = _flavor_file(tmp_path, 'distribution = "arch"\n', name="home")

    # when loading the config
    config = load(flavors_dir)

    # then each file is a flavour named after the file, sorted by name
    assert list(config.flavors.items()) == [
        ("home", Flavor(distribution="arch")),
        ("work", Flavor(distribution="arch", shell=ShellOption(name="zsh"))),
    ]


def test_load_ignores_files_that_are_not_toml(tmp_path: Path) -> None:
    # given a flavour file next to a file that is not TOML
    flavors_dir = _flavor_file(tmp_path, 'distribution = "arch"\n', name="home")
    (flavors_dir / "notes.txt").write_text("not a flavour")

    # when loading the config
    config = load(flavors_dir)

    # then only the TOML file is a flavour
    assert list(config.flavors) == ["home"]


def test_load_makes_a_single_flavor_the_default(tmp_path: Path) -> None:
    # given a single flavour file that does not say whether it is the default
    flavors_dir = _flavor_file(tmp_path, 'distribution = "arch"\n')

    # when loading the config
    config = load(flavors_dir)

    # then it is the default
    assert config == Config(flavors={"arch": Flavor(distribution="arch", default=True)})


def test_load_keeps_an_explicit_default_on_a_single_flavor(tmp_path: Path) -> None:
    # given a single flavour file that is explicitly not the default
    flavors_dir = _flavor_file(tmp_path, 'distribution = "arch"\ndefault = false\n')

    # when loading the config
    config = load(flavors_dir)

    # then it is not the default
    assert config == Config(flavors={"arch": Flavor(distribution="arch")})


def test_load_defaults_a_flavor(tmp_path: Path) -> None:
    # given two flavours, one declaring only its distribution
    _flavor_file(tmp_path, 'distribution = "arch"\n', name="other")
    flavors_dir = _flavor_file(tmp_path, 'distribution = "arch"\n')

    # when loading the config
    config = load(flavors_dir)

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
    flavors_dir = _flavor_file(tmp_path, 'shell = "zsh"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the missing distribution is reported against the flavour file, by its
    # path in that file
    assert (error.value.path, error.value.problems) == (
        flavors_dir / "arch.toml",
        ["distribution: Field required"],
    )


def test_load_rejects_unknown_distributions(tmp_path: Path) -> None:
    # given a flavour with a distribution Ask does not know
    flavors_dir = _flavor_file(tmp_path, 'distribution = "gentoo"\n')

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the distribution is reported together with the known ones
    assert error.value.problems == [
        "distribution: unknown distribution 'gentoo' (known: arch)"
    ]


def test_load_reports_flavor_files_that_cannot_be_read(tmp_path: Path) -> None:
    # given a flavour file that is not valid UTF-8
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()
    (flavors_dir / "arch.toml").write_bytes(b"\xff\xfe")

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the problem is reported against the flavour file
    assert (error.value.path, error.value.problems) == (
        flavors_dir / "arch.toml",
        ["file is not valid UTF-8"],
    )


def test_load_reads_the_default_flavor(tmp_path: Path) -> None:
    # given two flavours, one marked as the default
    _flavor_file(tmp_path, 'distribution = "arch"\n', name="other")
    flavors_dir = _flavor_file(tmp_path, 'distribution = "arch"\ndefault = true\n')

    # when loading the config
    config = load(flavors_dir)

    # then only the marked flavour is the default
    assert [name for name, flavor in config.flavors.items() if flavor.default] == [
        "arch"
    ]


def test_load_rejects_more_than_one_default_flavor(tmp_path: Path) -> None:
    # given two flavours both marked as the default
    _flavor_file(tmp_path, 'distribution = "arch"\ndefault = true\n', name="one")
    flavors_dir = _flavor_file(
        tmp_path, 'distribution = "arch"\ndefault = true\n', name="two"
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then both default flavours are named, against the flavours directory
    assert (error.value.path, error.value.problems) == (
        flavors_dir,
        ["flavors: more than one default flavour: 'one', 'two'"],
    )


def test_load_expands_the_home_directory_in_flavor_path_conditions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a home directory whose path contains regex metacharacters
    home = tmp_path / "home.d"
    monkeypatch.setenv("HOME", str(home))

    # and a flavour applying to a home-relative path regex
    flavors_dir = _flavor_file(
        tmp_path,
        'distribution = "arch"\nwhen.path = ["~/src/.*"]\n',
    )

    # when loading the config
    config = load(flavors_dir)

    # then "~" is replaced by the escaped home directory, leaving the rest a regex
    assert config.flavors["arch"].when == FlavorWhen(
        path=[re.compile(re.escape(str(home)) + "/src/.*")]
    )


def test_load_rejects_invalid_flavor_path_regexes(tmp_path: Path) -> None:
    # given a flavour path condition that is not a valid regex
    flavors_dir = _flavor_file(
        tmp_path, 'distribution = "arch"\nwhen.path = ["~/src/("]\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the regex is reported by its path
    assert error.value.problems == [
        "when.path.0: Input should be a valid regular expression"
    ]


def test_load_reads_the_flavor_shell(tmp_path: Path) -> None:
    # given a flavour declaring a shell by name
    flavors_dir = _flavor_file(tmp_path, 'distribution = "arch"\nshell = "zsh"\n')

    # when loading the config
    config = load(flavors_dir)

    # then the declared shell is read with default options
    assert config.flavors["arch"].shell == ShellOption(name="zsh", options={})


def test_load_reads_the_flavor_shell_options(tmp_path: Path) -> None:
    # given a flavour declaring a shell table with file options
    flavors_dir = _flavor_file(
        tmp_path,
        'distribution = "arch"\n'
        '[shell]\nname = "zsh"\nzshrc = false\nzprofile = true\n',
    )

    # when loading the config
    config = load(flavors_dir)

    # then the shell name and its file options are read
    assert config.flavors["arch"].shell == ShellOption(
        name="zsh", options={"zshrc": False, "zprofile": True}
    )


def test_load_reads_the_flavor_user(tmp_path: Path) -> None:
    # given a flavour declaring a user with a group and extra groups
    flavors_dir = _flavor_file(
        tmp_path,
        'distribution = "arch"\n'
        "[user]\n"
        'name = "raniz"\n'
        "uid = 1000\n"
        'extra_groups = ["wheel"]\n'
        "[user.group]\n"
        'name = "raniz"\n'
        "gid = 1000\n",
    )

    # when loading the config
    config = load(flavors_dir)

    # then the declared user is read in full
    assert config.flavors["arch"].user == User(
        name="raniz",
        uid=1000,
        extra_groups=["wheel"],
        group=Group(name="raniz", gid=1000),
    )


def _flavor_with_layers(tmp_path: Path, layers: str) -> Path:
    return _flavor_file(tmp_path, 'distribution = "arch"\n' + layers)


def test_load_defaults_a_layer(tmp_path: Path) -> None:
    # given a flavour declaring an empty base layer
    flavors_dir = _flavor_with_layers(tmp_path, "[layers.base]\n")

    # when loading the config
    config = load(flavors_dir)

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
    flavors_dir = _flavor_with_layers(
        tmp_path, '[layers.python]\nbind_mounts = ["~/.cache/uv"]\n'
    )

    # when loading the config
    config = load(flavors_dir)

    # then the layer's bind mounts are read, with "~" expanded
    assert config.flavors["arch"].layers == {
        "python": Layer(bind_mounts=[tmp_path / ".cache" / "uv"])
    }


def test_load_reads_layer_packages(tmp_path: Path) -> None:
    # given a layer declaring packages
    flavors_dir = _flavor_with_layers(
        tmp_path, '[layers.base]\npackages = ["zsh", "aur:antigen"]\n'
    )

    # when loading the config
    config = load(flavors_dir)

    # then the layer's packages are read as a plain list
    assert config.flavors["arch"].layers == {
        "base": Layer(packages=["zsh", "aur:antigen"])
    }


def test_load_rejects_layer_packages_keyed_by_distribution(tmp_path: Path) -> None:
    # given a layer declaring packages per distribution
    flavors_dir = _flavor_with_layers(
        tmp_path, '[layers.base]\npackages.arch = ["zsh"]\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the packages are reported as not being a list
    assert error.value.problems == [
        "layers.base.packages: Input should be a valid list"
    ]


def test_load_reads_layer_agents(tmp_path: Path) -> None:
    # given a layer declaring agents to install
    flavors_dir = _flavor_with_layers(tmp_path, '[layers.base]\nagents = ["claude"]\n')

    # when loading the config
    config = load(flavors_dir)

    # then the layer's agents are read as name-only options
    assert config.flavors["arch"].layers == {
        "base": Layer(agents=[AgentOption(name="claude")])
    }


def test_load_reads_layer_agents_with_full_options(tmp_path: Path) -> None:
    # given a layer declaring an agent with its full set of options
    flavors_dir = _flavor_with_layers(
        tmp_path,
        "[layers.base]\n"
        "agents = [\n"
        '  { name = "claude", claude_md = false, auth = true, skills = true, config = true },\n'
        "]\n",
    )

    # when loading the config
    config = load(flavors_dir)

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
    flavors_dir = _flavor_with_layers(
        tmp_path,
        '[layers.python]\norder = 10\nwhen.files = ["pyproject.toml", "uv.lock"]\n',
    )

    # when loading the config
    config = load(flavors_dir)

    # then the order and the file names are read
    assert config.flavors["arch"].layers == {
        "python": Layer(order=10, when=LayerWhen(files=["pyproject.toml", "uv.lock"]))
    }


def test_load_rejects_conditions_on_the_base_layer(tmp_path: Path) -> None:
    # given a base layer with a file condition
    flavors_dir = _flavor_with_layers(
        tmp_path, '[layers.base]\nwhen.files = ["pyproject.toml"]\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the condition is reported, since the base layer is always applied
    assert error.value.problems == [
        ("layers: the base layer is always applied and cannot have when conditions")
    ]


def test_load_rejects_tool_managers_in_a_layer(tmp_path: Path) -> None:
    # given a layer declaring tool managers
    flavors_dir = _flavor_with_layers(
        tmp_path, '[layers.base]\ntool_managers = ["mise"]\n'
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then tool_managers is reported as an unknown key
    assert error.value.problems == ["layers.base.tool_managers: unknown key"]


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


def test_load_preserves_full_service_names(tmp_path: Path) -> None:
    # given a flavour with services using full names
    flavor_dir = tmp_path / "flavors"
    flavor_dir.mkdir()
    flavor_file = flavor_dir / "arch.toml"
    flavor_file.write_text("""
        distribution = "arch"
        default = true
        [layers.base]
        services."sshd.service" = "enabled"
        services."docker.socket" = "disabled"
        services."man-db.timer" = "masked"
        """)

    # when loading the config
    config = load(flavor_dir)

    # then full service names are preserved
    services = config.flavors["arch"].layers["base"].services
    assert services["sshd.service"] == "enabled"
    assert services["docker.socket"] == "disabled"
    assert services["man-db.timer"] == "masked"


def test_load_normalizes_short_service_names(tmp_path: Path) -> None:
    # given a flavour with services using short names (no suffix)
    flavor_dir = tmp_path / "flavors"
    flavor_dir.mkdir()
    flavor_file = flavor_dir / "arch.toml"
    flavor_file.write_text("""
        distribution = "arch"
        default = true
        [layers.base]
        services.sshd = "enabled"
        services.docker = "disabled"
        """)

    # when loading the config
    config = load(flavor_dir)

    # then short service names are normalized to include .service suffix
    services = config.flavors["arch"].layers["base"].services
    assert services["sshd.service"] == "enabled"
    assert services["docker.service"] == "disabled"


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
    flavors_dir = _flavor_with_layers(tmp_path, "[layers.base]\nshared_state = true\n")

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the unknown field is reported by its path
    assert error.value.problems == ["layers.base.shared_state: unknown key"]


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
    # given a flavour file with a syntax error
    flavors_dir = _flavor_file(tmp_path, "shell = \n")

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the error names the flavour file
    assert error.value.path == flavors_dir / "arch.toml"


def test_load_rejects_values_of_the_wrong_type(tmp_path: Path) -> None:
    # given a flavour user with a non-integer uid
    flavors_dir = _flavor_file(
        tmp_path,
        'distribution = "arch"\n[user]\nuid = "1000"\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the wrongly typed value is reported by its path
    assert error.value.problems == ["user.uid: Input should be a valid integer"]


def test_load_rejects_shell_options_of_the_wrong_type(tmp_path: Path) -> None:
    # given a flavour shell table with a non-boolean option
    flavors_dir = _flavor_file(
        tmp_path,
        'distribution = "arch"\n[shell]\nname = "zsh"\nzshrc = "yes"\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the option is reported by the path it has in the TOML file
    assert error.value.problems == ["shell.zshrc: Input should be a valid boolean"]


def test_load_rejects_agent_options_of_the_wrong_type(tmp_path: Path) -> None:
    # given a layer agent table with a non-boolean option
    flavors_dir = _flavor_with_layers(
        tmp_path,
        '[layers.base]\nagents = [{ name = "claude", auth = 1 }]\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the option is reported by the path it has in the TOML file
    assert error.value.problems == [
        "layers.base.agents.0.auth: Input should be a valid boolean"
    ]


def test_load_rejects_shell_tables_without_a_name(tmp_path: Path) -> None:
    # given a flavour shell table that only sets options
    flavors_dir = _flavor_file(
        tmp_path,
        'distribution = "arch"\n[shell]\nzshrc = true\n',
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then the missing name is reported
    assert error.value.problems == ["shell.name: Field required"]


def test_load_reports_every_problem_at_once(tmp_path: Path) -> None:
    # given a flavour with several unrelated problems
    flavors_dir = _flavor_file(
        tmp_path,
        'distribution = "arch"\nshell = 1\n'
        '[user]\nuid = "1000"\n'
        "[layers.base]\nbind_mount = []\n",
    )

    # when loading the config
    with pytest.raises(ConfigError) as error:
        load(flavors_dir)

    # then all of them are reported together
    assert error.value.problems == [
        "shell: Input should be a valid string or table",
        "user.uid: Input should be a valid integer",
        "layers.base.bind_mount: unknown key",
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
