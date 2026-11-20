from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ask.agent import Agent, AgentError, AgentSettings, AgentTable
from ask.config import ConfigError, Flavor, Layer, LayerWhen
from ask.incus import Mount
from ask.manifest import Manifest, ResolvedManifest, load
from ask.tool_manager import Mise
from ask.user import ResolvedUser


def _manifest_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "ask.toml"
    path.write_text(text)
    return path


def test_load_defaults_an_empty_manifest(tmp_path: Path) -> None:
    # given an empty manifest file
    manifest_path = _manifest_file(tmp_path, "")

    # when loading the manifest
    manifest = load(manifest_path)

    # then it has no packages, bind mounts or tool managers
    assert manifest == Manifest(packages=[], bind_mounts=[], tool_managers=[])


def test_load_reads_packages_from_toml(tmp_path: Path) -> None:
    # given a manifest file declaring packages
    manifest_path = _manifest_file(tmp_path, 'packages = ["uv", "python"]\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then the packages are read as a plain list, in order
    assert manifest == Manifest(packages=["uv", "python"])


def test_load_reads_bind_mounts_from_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a manifest file declaring bind_mounts, one using a home-relative path
    monkeypatch.setenv("HOME", str(tmp_path))
    manifest_path = _manifest_file(tmp_path, 'bind_mounts = ["~/foo", "/abs/path"]\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then each path is read, with "~" expanded against the home directory
    assert manifest == Manifest(bind_mounts=[tmp_path / "foo", Path("/abs/path")])


def test_load_reads_services_from_toml(tmp_path: Path) -> None:
    # given a manifest file declaring services
    manifest_path = _manifest_file(
        tmp_path,
        'services."sshd.service" = "enabled"\nservices."man-db.timer" = "disabled"\n',
    )

    # when loading the manifest
    manifest = load(manifest_path)

    # then the services are read as a dict
    assert manifest == Manifest(
        services={"sshd.service": "enabled", "man-db.timer": "disabled"}
    )


def test_load_reads_tool_managers_from_toml(tmp_path: Path) -> None:
    # given a manifest file opting into mise
    manifest_path = _manifest_file(tmp_path, 'tool_managers = ["mise"]\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then the tool manager is read
    assert manifest == Manifest(tool_managers=["mise"])


def test_load_reads_scripts_from_toml(tmp_path: Path) -> None:
    # given a manifest file declaring scripts
    manifest_path = _manifest_file(
        tmp_path, '[scripts]\ntest = "pytest"\nlint = "ruff check"\n'
    )

    # when loading the manifest
    manifest = load(manifest_path)

    # then the scripts are read as a dict of command strings
    assert manifest.scripts == {"test": "pytest", "lint": "ruff check"}


def test_load_rejects_an_empty_script_command(tmp_path: Path) -> None:
    # given a manifest file declaring a script with an empty command
    manifest_path = _manifest_file(tmp_path, '[scripts]\ntest = ""\n')

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then the empty command is reported against the scripts table
    assert error.value.problems == [
        "scripts: script command cannot be empty for script 'test'"
    ]


def test_load_reads_environment_variables_from_toml(tmp_path: Path) -> None:
    # given a manifest file setting one variable and removing another
    manifest_path = _manifest_file(
        tmp_path, 'env = { EDITOR = "nvim", PAGER = false }\n'
    )

    # when loading the manifest
    manifest = load(manifest_path)

    # then both are read
    assert manifest == Manifest(env={"EDITOR": "nvim", "PAGER": False})


def test_load_rejects_keys_that_belong_to_flavors_and_layers(tmp_path: Path) -> None:
    # given a manifest file declaring keys that only flavours and their layers have
    manifest_path = _manifest_file(
        tmp_path,
        'distribution = "arch"\nlayers = ["base"]\nagents = { claude = true }\norder = 1\n',
    )

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then each of them is reported as an unknown key
    assert error.value.problems == [
        "distribution: unknown key",
        "layers: unknown key",
        "agents: unknown key",
        "order: unknown key",
    ]


def test_load_rejects_packages_keyed_by_distribution(tmp_path: Path) -> None:
    # given a manifest file declaring packages per distribution
    manifest_path = _manifest_file(tmp_path, 'packages.arch = ["zsh"]\n')

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then the packages are reported as not being a list
    assert error.value.problems == ["packages: Input should be a valid list"]


def test_load_reports_syntax_errors_as_config_errors(tmp_path: Path) -> None:
    # given a manifest file with a syntax error
    manifest_path = _manifest_file(tmp_path, "packages = \n")

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then the error names the file
    assert error.value.path == manifest_path


def test_load_reports_every_wrongly_typed_value(tmp_path: Path) -> None:
    # given a manifest file with several wrongly typed values
    manifest_path = _manifest_file(
        tmp_path, 'packages = ["git", 2]\nbind_mounts = "~/foo"\ntool_managers = 1\n'
    )

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then all of them are reported together
    assert error.value.problems == [
        "packages.1: Input should be a valid string",
        "bind_mounts: Input should be a valid list",
        "tool_managers: Input should be a valid list",
    ]


def test_load_rejects_removing_tool_managers(tmp_path: Path) -> None:
    # given a manifest file removing a tool manager with the "-" prefix
    manifest_path = _manifest_file(tmp_path, 'tool_managers = ["-mise"]\n')

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then the removal is reported, since there is nothing to remove it from
    assert error.value.problems == [
        (
            "tool_managers.0: tool managers are only enabled by ask.toml and "
            "cannot be removed with '-'"
        )
    ]


def test_load_rejects_unknown_tool_managers(tmp_path: Path) -> None:
    # given a manifest file opting into a tool manager ask doesn't support
    manifest_path = _manifest_file(tmp_path, 'tool_managers = ["mise", "asdf"]\n')

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then the unsupported one is reported along with the supported ones
    assert error.value.problems == [
        "tool_managers.1: unknown tool manager 'asdf' (known: mise)"
    ]


_NO_PROJECT_FILES = Path("/nonexistent-project")


def _resolved(
    layers: dict[str, Layer],
    manifest: Manifest | None = None,
    project_dir: Path = _NO_PROJECT_FILES,
) -> ResolvedManifest:
    flavor = Flavor(distribution="arch", layers=layers)
    return ResolvedManifest(manifest or Manifest(), flavor, project_dir)


def test_layer_names_applies_the_base_layer_first() -> None:
    # given a flavour declaring an unconditional layer with a lower order before
    # its base layer
    resolved = _resolved({"python": Layer(order=-5), "base": Layer()})

    # when resolving the names of the applied layers
    layer_names = resolved.layer_names

    # then the base layer comes first
    assert layer_names == ["base", "python"]


def test_layer_names_applies_layers_whose_files_exist_in_the_project(
    tmp_path: Path,
) -> None:
    # given a project containing a pyproject.toml
    (tmp_path / "pyproject.toml").write_text("")

    # and a flavour with a layer applying to either of two files, one of them
    # being pyproject.toml
    resolved = _resolved(
        {"python": Layer(when=LayerWhen(files=["setup.py", "pyproject.toml"]))},
        project_dir=tmp_path,
    )

    # when resolving the names of the applied layers
    layer_names = resolved.layer_names

    # then the layer is applied
    assert layer_names == ["python"]


def test_layer_names_skips_layers_whose_files_do_not_exist_in_the_project(
    tmp_path: Path,
) -> None:
    # given a project containing only a Cargo.toml
    (tmp_path / "Cargo.toml").write_text("")

    # and a flavour with a base layer and a layer applying to pyproject.toml
    resolved = _resolved(
        {
            "base": Layer(),
            "python": Layer(when=LayerWhen(files=["pyproject.toml"])),
        },
        project_dir=tmp_path,
    )

    # when resolving the names of the applied layers
    layer_names = resolved.layer_names

    # then only the base layer is applied
    assert layer_names == ["base"]


def test_layer_names_only_matches_files_directly_in_the_project(
    tmp_path: Path,
) -> None:
    # given a project containing pyproject.toml only in a subdirectory
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "pyproject.toml").write_text("")

    # and a flavour with a layer applying to pyproject.toml
    resolved = _resolved(
        {"python": Layer(when=LayerWhen(files=["pyproject.toml"]))},
        project_dir=tmp_path,
    )

    # when resolving the names of the applied layers
    layer_names = resolved.layer_names

    # then the layer is not applied
    assert layer_names == []


def test_layer_names_orders_layers_by_order_keeping_declaration_order_for_ties() -> (
    None
):
    # given a flavour declaring unconditional layers with and without an order
    resolved = _resolved(
        {
            "late": Layer(order=10),
            "first": Layer(),
            "second": Layer(),
            "early": Layer(order=-1),
        }
    )

    # when resolving the names of the applied layers
    layer_names = resolved.layer_names

    # then they are sorted by order, layers with the same order keeping the
    # order they were declared in
    assert layer_names == ["early", "first", "second", "late"]


def test_bind_mounts_applies_layers_before_the_project() -> None:
    # given a manifest with its own bind mount, and a flavour layer with another
    manifest = Manifest(bind_mounts=[Path("/project/mount")])
    resolved = _resolved(
        {"python": Layer(bind_mounts=[Path("/layer/mount")])}, manifest
    )

    # when resolving the full set of bind mounts
    mounts = resolved.bind_mounts

    # then the layer-level mounts come first, followed by the project-level ones
    assert mounts == [Path("/layer/mount"), Path("/project/mount")]


def test_bind_mounts_merges_duplicates() -> None:
    # given a manifest and two layers all mounting the same path, and one layer
    # mounting another path as well
    manifest = Manifest(bind_mounts=[Path("/shared")])
    resolved = _resolved(
        {
            "base": Layer(bind_mounts=[Path("/shared"), Path("/base")]),
            "python": Layer(bind_mounts=[Path("/shared")]),
        },
        manifest,
    )

    # when resolving the full set of bind mounts
    mounts = resolved.bind_mounts

    # then each path is mounted once, at its first position
    assert mounts == [Path("/shared"), Path("/base")]


def test_bind_mounts_leaves_out_layers_that_are_not_applied(tmp_path: Path) -> None:
    # given a flavour with a base layer and a layer applying to a file the
    # project doesn't contain, both mounting a path
    resolved = _resolved(
        {
            "base": Layer(bind_mounts=[Path("/base")]),
            "python": Layer(
                bind_mounts=[Path("/python")],
                when=LayerWhen(files=["pyproject.toml"]),
            ),
        },
        project_dir=tmp_path,
    )

    # when resolving the full set of bind mounts
    mounts = resolved.bind_mounts

    # then only the applied layer's path is mounted
    assert mounts == [Path("/base")]


def test_packages_applies_layers_before_the_project() -> None:
    # given a manifest with its own package, and a flavour layer with another
    manifest = Manifest(packages=["project-pkg"])
    resolved = _resolved({"python": Layer(packages=["layer-pkg"])}, manifest)

    # when resolving the full set of packages
    packages = resolved.packages

    # then the layer-level packages come first, followed by the project-level ones
    assert packages == ["layer-pkg", "project-pkg"]


def test_packages_applies_layers_in_their_order() -> None:
    # given a flavour with a base layer and two layers with different orders,
    # each installing a package
    resolved = _resolved(
        {
            "late": Layer(order=10, packages=["late-pkg"]),
            "early": Layer(packages=["early-pkg"]),
            "base": Layer(packages=["base-pkg"]),
        }
    )

    # when resolving the full set of packages
    packages = resolved.packages

    # then the packages follow the order the layers are applied in
    assert packages == ["base-pkg", "early-pkg", "late-pkg"]


def test_packages_merges_duplicates() -> None:
    # given a manifest and a layer both installing the same package, and the
    # layer installing another package as well
    manifest = Manifest(packages=["git"])
    resolved = _resolved({"base": Layer(packages=["git", "zsh", "git"])}, manifest)

    # when resolving the full set of packages
    packages = resolved.packages

    # then each package is installed once, at its first position
    assert packages == ["git", "zsh"]


def test_packages_removes_dash_prefixed_packages_from_lower_layers() -> None:
    # given a layer installing two packages, and a manifest removing one of them
    # and a package no layer installs
    manifest = Manifest(packages=["-git", "-nonexistent"])
    resolved = _resolved({"base": Layer(packages=["git", "zsh"])}, manifest)

    # when resolving the full set of packages
    packages = resolved.packages

    # then the removed package is gone, and the removal of the package no
    # layer installs has no effect
    assert packages == ["zsh"]


def test_packages_removal_does_not_affect_its_own_layer() -> None:
    # given a layer installing a package, and a manifest both removing and
    # installing that package
    manifest = Manifest(packages=["-git", "git"])
    resolved = _resolved({"base": Layer(packages=["git", "zsh"])}, manifest)

    # when resolving the full set of packages
    packages = resolved.packages

    # then the package is removed from the lower layer, but installed by the
    # manifest itself
    assert packages == ["zsh", "git"]


def _enabling(*names: str, default: str | None = None) -> AgentTable:
    return AgentTable(
        default=default, entries={name: AgentSettings() for name in names}
    )


def test_agent_names_combines_agents_from_every_applied_layer() -> None:
    # given a flavour with two layers, each enabling an agent
    resolved = _resolved(
        {
            "base": Layer(agents=_enabling("claude")),
            "python": Layer(agents=_enabling("other")),
        }
    )

    # when resolving the full set of agent names
    agent_names = resolved.agent_names

    # then the agent names from both layers are included, in the order the
    # layers are applied, without being resolved to actual agents
    assert agent_names == ["claude", "other"]


def test_agent_names_merges_duplicates() -> None:
    # given two layers enabling the same agent, the second one alongside
    # another agent
    resolved = _resolved(
        {
            "base": Layer(agents=_enabling("claude")),
            "python": Layer(agents=_enabling("codex", "claude")),
        }
    )

    # when resolving the full set of agent names
    agent_names = resolved.agent_names

    # then each agent is named once, at its first position
    assert agent_names == ["claude", "codex"]


def test_agent_names_removes_disabled_agents_from_lower_layers() -> None:
    # given a layer enabling two agents, and a later layer removing one of them
    # and an agent no layer enables
    resolved = _resolved(
        {
            "base": Layer(agents=_enabling("claude", "codex")),
            "python": Layer(
                agents=AgentTable(
                    entries={
                        "claude": AgentSettings(enabled=False),
                        "pi": AgentSettings(enabled=False),
                    }
                )
            ),
        }
    )

    # when resolving the full set of agent names
    agent_names = resolved.agent_names

    # then the removed agent is gone, and the removal of the agent no layer
    # enables has no effect
    assert agent_names == ["codex"]


def test_agent_extensions_combines_extensions_from_every_applied_layer() -> None:
    # given two layers enabling pi, each declaring extensions, one repeating
    # an extension of the other
    resolved = _resolved(
        {
            "base": Layer(
                agents=AgentTable(entries={"pi": AgentSettings(extensions=["@a/one"])})
            ),
            "python": Layer(
                agents=AgentTable(
                    entries={
                        "pi": AgentSettings(extensions=["@b/two", "@a/one"]),
                        "claude": AgentSettings(),
                    }
                )
            ),
        }
    )

    # when resolving the agent extensions
    extensions = resolved.agent_extensions

    # then the extensions of both layers are included, in order, without
    # duplicates
    assert extensions == {"pi": ["@a/one", "@b/two"]}


def test_agent_extensions_is_empty_when_no_extension_agent_is_enabled() -> None:
    # given a layer enabling an agent other than pi
    resolved = _resolved({"base": Layer(agents=_enabling("claude"))})

    # when resolving the agent extensions
    extensions = resolved.agent_extensions

    # then there are none
    assert extensions == {}


def test_agent_extensions_is_empty_when_pi_is_disabled_in_a_later_layer() -> None:
    # given a layer enabling pi with extensions, and a later layer disabling pi
    resolved = _resolved(
        {
            "base": Layer(
                agents=AgentTable(entries={"pi": AgentSettings(extensions=["@a/one"])})
            ),
            "python": Layer(
                agents=AgentTable(entries={"pi": AgentSettings(enabled=False)})
            ),
        }
    )

    # when resolving the agent extensions
    extensions = resolved.agent_extensions

    # then there are none
    assert extensions == {}


def test_agent_extensions_includes_oh_my_pi_extensions() -> None:
    # given a layer enabling oh-my-pi with extensions
    resolved = _resolved(
        {
            "base": Layer(
                agents=AgentTable(
                    entries={"oh-my-pi": AgentSettings(extensions=["@foo/bar"])}
                )
            )
        }
    )

    # when resolving the agent extensions
    extensions = resolved.agent_extensions

    # then oh-my-pi's extensions are included
    assert extensions == {"oh-my-pi": ["@foo/bar"]}


def test_agents_resolves_each_configured_agent_name_in_order() -> None:
    # given a flavour with two layers, each enabling an agent
    resolved = _resolved(
        {
            "base": Layer(agents=_enabling("claude")),
            "python": Layer(agents=_enabling("other")),
        }
    )
    claude_agent = Agent(name="claude")
    other_agent = Agent(name="other")

    # when resolving the full set of agents
    with patch("ask.manifest.agent.resolve") as resolve:
        resolve.side_effect = {"claude": claude_agent, "other": other_agent}.__getitem__
        agents = resolved.agents

    # then each configured agent name is resolved, in order
    resolve.assert_has_calls([call("claude"), call("other")])
    assert agents == [claude_agent, other_agent]


def test_default_agent_is_the_first_agent_without_an_explicit_default() -> None:
    # given two layers enabling agents, none naming a default
    resolved = _resolved(
        {
            "base": Layer(agents=_enabling("codex")),
            "python": Layer(agents=_enabling("claude")),
        }
    )

    # when resolving the default agent
    default = resolved.default_agent

    # then it is the first enabled agent
    assert default == "codex"


def test_default_agent_is_the_default_of_the_last_layer_naming_one() -> None:
    # given three layers enabling agents, the first two naming a default
    resolved = _resolved(
        {
            "base": Layer(agents=_enabling("claude", "codex", default="codex")),
            "python": Layer(agents=_enabling("pi", default="pi")),
            "rust": Layer(agents=_enabling("opencode")),
        }
    )

    # when resolving the default agent
    default = resolved.default_agent

    # then it is the default named by the last layer that names one
    assert default == "pi"


def test_default_agent_is_none_without_agents() -> None:
    # given a layer enabling no agents
    resolved = _resolved({"base": Layer()})

    # when resolving the default agent
    default = resolved.default_agent

    # then there is none
    assert default is None


def test_default_agent_rejects_a_default_that_is_not_enabled() -> None:
    # given a layer naming a default agent, and a later layer removing it
    resolved = _resolved(
        {
            "base": Layer(agents=_enabling("claude", "codex", default="codex")),
            "python": Layer(
                agents=AgentTable(entries={"codex": AgentSettings(enabled=False)})
            ),
        }
    )

    # when resolving the default agent
    with pytest.raises(AgentError) as error:
        _ = resolved.default_agent

    # then the default is reported as not being enabled
    assert str(error.value) == (
        "The default agent 'codex' is not enabled in the flavour layers that "
        "apply to this project."
    )


def test_instance_env_merges_layers_then_the_manifest() -> None:
    # given two layers and a manifest setting, overriding and removing
    # variables
    resolved = _resolved(
        {
            "base": Layer(env={"EDITOR": "vi", "PAGER": "less", "LANG": "C"}),
            "python": Layer(env={"EDITOR": "nvim", "PAGER": False}),
        },
        Manifest(env={"LANG": "C.UTF-8"}),
    )

    # when resolving the instance environment
    env = resolved.instance_env

    # then later layers win, and the manifest wins over every layer
    assert env == {"EDITOR": "nvim", "LANG": "C.UTF-8"}


def test_agent_env_layers_every_agent_and_the_agent_over_the_instance() -> None:
    # given variables set for the instance, every agent and one agent, across
    # two layers
    resolved = _resolved(
        {
            "base": Layer(
                env={"A": "instance", "B": "instance", "C": "instance"},
                agents=AgentTable(
                    env={"B": "agents", "D": "agents"},
                    entries={"claude": AgentSettings(env={"C": "claude"})},
                ),
            ),
            "python": Layer(
                agents=AgentTable(
                    env={"D": "python agents"},
                    entries={"claude": AgentSettings(env={"A": False})},
                ),
            ),
        }
    )

    # when resolving the environment of the agent
    env = resolved.agent_env("claude")

    # then every agent's variables win over the instance's, the agent's own
    # win over both, and removing a variable removes it from every level
    assert env == {"B": "agents", "C": "claude", "D": "python agents"}


def test_agent_env_forgets_the_variables_of_removed_agents() -> None:
    # given a layer setting a variable for an agent, a second layer removing
    # that agent, and a third layer enabling it again
    resolved = _resolved(
        {
            "base": Layer(
                agents=AgentTable(entries={"claude": AgentSettings(env={"FOO": "1"})})
            ),
            "no-claude": Layer(
                agents=AgentTable(entries={"claude": AgentSettings(enabled=False)})
            ),
            "claude-again": Layer(agents=_enabling("claude")),
        }
    )

    # when resolving the environment of the agent
    env = resolved.agent_env("claude")

    # then the re-enabled agent does not inherit the removed agent's variables
    assert env == {}


def test_agent_env_of_an_agent_that_is_not_enabled_is_that_of_every_agent() -> None:
    # given a layer setting variables for the instance and for every agent,
    # without enabling the agent
    resolved = _resolved(
        {"base": Layer(env={"A": "instance"}, agents=AgentTable(env={"B": "agents"}))}
    )

    # when resolving the environment of the agent
    env = resolved.agent_env("claude")

    # then it has the instance's and every agent's variables
    assert env == {"A": "instance", "B": "agents"}


def _user() -> ResolvedUser:
    return ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )


def test_agent_mounts_calls_mounts_for_with_each_agents_options() -> None:
    # given a flavour with two layers, each declaring an agent, one of them
    # with its own options
    resolved = _resolved(
        {
            "base": Layer(
                agents=AgentTable(
                    entries={"claude": AgentSettings(options={"auth": False})}
                )
            ),
            "python": Layer(agents=_enabling("other")),
        }
    )
    claude_agent = MagicMock()
    claude_mounts = [
        Mount(host_path=Path("/host/state"), container_path=Path("/container/state"))
    ]
    claude_agent.mounts_for.return_value = claude_mounts
    other_agent = MagicMock()
    other_mounts = [
        Mount(host_path=Path("/host/other"), container_path=Path("/container/other"))
    ]
    other_agent.mounts_for.return_value = other_mounts

    # when resolving the agents' mounts
    with patch(
        "ask.manifest.agent.resolve", side_effect=[claude_agent, other_agent]
    ) as resolve:
        mounts = resolved.agent_mounts(_user())

    # then each agent is resolved, its mounts_for is called with the user and
    # its own options, and the resulting mounts are returned in order
    resolve.assert_has_calls([call("claude"), call("other")])
    claude_agent.mounts_for.assert_called_once_with(_user(), {"auth": False})
    other_agent.mounts_for.assert_called_once_with(_user(), {})
    assert mounts == claude_mounts + other_mounts


def test_agent_mounts_merges_agent_options_with_later_layers_winning() -> None:
    # given a layer enabling an agent with two options, and a later layer
    # enabling the same agent, overriding one option
    resolved = _resolved(
        {
            "base": Layer(
                agents=AgentTable(
                    entries={
                        "claude": AgentSettings(
                            options={"auth": False, "skills": False}
                        )
                    }
                )
            ),
            "python": Layer(
                agents=AgentTable(
                    entries={"claude": AgentSettings(options={"auth": True})}
                )
            ),
        }
    )
    claude_agent = MagicMock()
    claude_agent.mounts_for.return_value = []

    # when resolving the agents' mounts
    with patch("ask.manifest.agent.resolve", return_value=claude_agent):
        resolved.agent_mounts(_user())

    # then the agent's mounts are resolved once with the merged options, the
    # later layer's value winning
    claude_agent.mounts_for.assert_called_once_with(
        _user(), {"auth": True, "skills": False}
    )


def test_agent_mounts_forgets_options_of_removed_agents() -> None:
    # given a layer enabling an agent with an option, a second layer removing
    # that agent, and a third layer enabling it again without options
    resolved = _resolved(
        {
            "base": Layer(
                agents=AgentTable(
                    entries={"claude": AgentSettings(options={"auth": False})}
                )
            ),
            "no-claude": Layer(
                agents=AgentTable(entries={"claude": AgentSettings(enabled=False)})
            ),
            "claude-again": Layer(agents=_enabling("claude")),
        }
    )
    claude_agent = MagicMock()
    claude_agent.mounts_for.return_value = []

    # when resolving the agents' mounts
    with patch("ask.manifest.agent.resolve", return_value=claude_agent):
        resolved.agent_mounts(_user())

    # then the re-enabled agent does not inherit the removed agent's options
    claude_agent.mounts_for.assert_called_once_with(_user(), {})


def test_tool_managers_enables_no_tool_manager_by_default() -> None:
    # given a manifest that doesn't mention tool managers, and a base layer
    resolved = _resolved({"base": Layer()})

    # when resolving the enabled tool managers
    tool_managers = resolved.tool_managers

    # then no tool manager is enabled
    assert tool_managers == []


def test_services_merges_services_from_layers(tmp_path: Path) -> None:
    # given a flavour with two layers, each declaring services
    flavor = Flavor(
        distribution="arch",
        layers={
            "base": Layer(
                services={"sshd.service": "enabled", "man-db.timer": "disabled"},
            ),
            "python": Layer(
                when=LayerWhen(files=["pyproject.toml"]),
                services={"cronie.service": "started"},
            ),
        },
    )
    project_dir = tmp_path
    (project_dir / "pyproject.toml").touch()

    # when resolving the manifest
    resolved = ResolvedManifest(Manifest(), flavor, project_dir)

    # then the services from both layers are merged
    assert resolved.services == {
        "sshd.service": "enabled",
        "man-db.timer": "disabled",
        "cronie.service": "started",
    }


def test_services_ignores_layers_that_do_not_apply(tmp_path: Path) -> None:
    # given a flavour with two layers, one that applies and one that doesn't
    flavor = Flavor(
        distribution="arch",
        layers={
            "base": Layer(
                services={"sshd.service": "enabled"},
            ),
            "python": Layer(
                when=LayerWhen(files=["pyproject.toml"]),
                services={"cronie.service": "started"},
            ),
        },
    )
    project_dir = tmp_path
    # pyproject.toml does not exist

    # when resolving the manifest
    resolved = ResolvedManifest(Manifest(), flavor, project_dir)

    # then only the services from the base layer are included
    assert resolved.services == {"sshd.service": "enabled"}


def test_services_empty_when_no_layers_have_services() -> None:
    # given a flavour with no services
    resolved = _resolved({"base": Layer()})

    # when resolving the services
    services = resolved.services

    # then services is an empty dict
    assert services == {}


def test_services_includes_services_from_the_manifest() -> None:
    # given a manifest with services
    resolved = _resolved({}, Manifest(services={"project.service": "enabled"}))

    # when resolving the services
    services = resolved.services

    # then the manifest services are included
    assert services == {"project.service": "enabled"}


def test_services_manifest_overrides_layer_services() -> None:
    # given a layer and a manifest both declaring the same service
    resolved = _resolved(
        {"base": Layer(services={"conflict.service": "disabled"})},
        Manifest(services={"conflict.service": "enabled"}),
    )

    # when resolving the services
    services = resolved.services

    # then the manifest service takes precedence
    assert services == {"conflict.service": "enabled"}


def test_services_merges_manifest_and_layer_services() -> None:
    # given a layer and a manifest declaring different services
    resolved = _resolved(
        {"base": Layer(services={"layer.service": "enabled"})},
        Manifest(services={"manifest.service": "disabled"}),
    )

    # when resolving the services
    services = resolved.services

    # then both services are included
    assert services == {
        "layer.service": "enabled",
        "manifest.service": "disabled",
    }


def test_services_normalizes_short_names_in_manifest() -> None:
    # given a manifest with short service names (no suffix) and a layer with full names
    resolved = _resolved(
        {
            "base": Layer(
                services={"existing.service": "enabled", "docker.socket": "masked"}
            )
        },
        Manifest(services={"short": "disabled", "another": "masked"}),
    )

    # when resolving the services
    services = resolved.services

    # then short service names are normalized to include .service suffix while full names are preserved
    assert services == {
        "existing.service": "enabled",
        "docker.socket": "masked",  # Preserved full name
        "short.service": "disabled",  # Normalized short name
        "another.service": "masked",  # Normalized short name
    }


def test_tool_managers_enables_the_tool_managers_the_manifest_lists() -> None:
    # given a manifest opting into mise
    resolved = _resolved({}, Manifest(tool_managers=["mise"]))

    # when resolving the enabled tool managers
    tool_managers = resolved.tool_managers

    # then mise is enabled
    assert tool_managers == [Mise()]
