from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ask.agent import Agent, AgentOption
from ask.config import ConfigError, Layer
from ask.incus import Mount
from ask.manifest import Manifest, ResolvedManifest, load
from ask.user import ResolvedUser


def test_load_reads_distribution_from_toml(tmp_path: Path) -> None:
    # given a manifest file declaring a distribution
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then the distribution is available on the result
    assert manifest == Manifest(distribution="arch")


def test_load_rejects_unknown_fields(tmp_path: Path) -> None:
    # given a manifest file with an unknown field alongside the distribution
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\nide = "jetbrains-idea"\n')

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then the unknown field is reported
    assert error.value.problems == ["ide: unknown key"]


def test_load_defaults_bind_mounts_to_empty_list(tmp_path: Path) -> None:
    # given a manifest file with no bind_mounts declared
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then bind_mounts defaults to an empty list
    assert manifest.bind_mounts == []


def test_load_reads_bind_mounts_from_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a manifest file declaring bind_mounts, one using a home-relative path
    monkeypatch.setenv("HOME", str(tmp_path))
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text(
        'distribution = "arch"\nbind_mounts = ["~/foo", "/abs/path"]\n'
    )

    # when loading the manifest
    manifest = load(manifest_path)

    # then each path is read, with "~" expanded against the home directory
    assert manifest.bind_mounts == [tmp_path / "foo", Path("/abs/path")]


def test_load_defaults_packages_to_empty_dict(tmp_path: Path) -> None:
    # given a manifest file with no packages declared
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then packages defaults to an empty dict
    assert manifest.packages == {}


def test_load_reads_packages_from_toml(tmp_path: Path) -> None:
    # given a manifest file declaring packages for multiple distributions
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text(
        'distribution = "arch"\npackages.common = ["python"]\npackages.arch = ["zsh"]\n'
    )

    # when loading the manifest
    manifest = load(manifest_path)

    # then the declared packages are read, keyed by distribution
    assert manifest.packages == {"common": ["python"], "arch": ["zsh"]}


def test_load_defaults_layers_to_empty_list(tmp_path: Path) -> None:
    # given a manifest file with no layers declared
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then layers defaults to an empty list
    assert manifest.layers == []


def test_load_reads_layers_from_toml(tmp_path: Path) -> None:
    # given a manifest file declaring layers
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\nlayers = ["base", "python"]\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then the declared layer names are read, in order
    assert manifest.layers == ["base", "python"]


def test_load_reads_agents_and_shared_state_from_toml(tmp_path: Path) -> None:
    # given a manifest file enabling agents, one with options, and shared state
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text(
        'distribution = "arch"\n'
        'agents = ["claude", { name = "codex", auth = false }]\n'
        "shared_state = true\n"
    )

    # when loading the manifest
    manifest = load(manifest_path)

    # then the agents and shared state are read like in a layer
    assert manifest.agents == [
        AgentOption(name="claude"),
        AgentOption(name="codex", options={"auth": False}),
    ]
    assert manifest.shared_state is True


def test_bind_mounts_applies_layers_before_the_project() -> None:
    # given a manifest with its own bind mount and one declared layer, and the
    # defined layers mapping, defining that layer's bind mount
    manifest = Manifest(
        distribution="arch", bind_mounts=[Path("/project/mount")], layers=["python"]
    )
    layers = {"python": Layer(bind_mounts=[Path("/layer/mount")])}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of bind mounts
    mounts = resolved.bind_mounts

    # then the layer-level mounts come first, followed by the project-level ones
    assert mounts == [Path("/layer/mount"), Path("/project/mount")]


def test_bind_mounts_merges_duplicates() -> None:
    # given a manifest and two declared layers all mounting the same path, and
    # one layer mounting another path as well
    manifest = Manifest(
        distribution="arch", bind_mounts=[Path("/shared")], layers=["base", "python"]
    )
    layers = {
        "base": Layer(bind_mounts=[Path("/shared"), Path("/base")]),
        "python": Layer(bind_mounts=[Path("/shared")]),
    }
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of bind mounts
    mounts = resolved.bind_mounts

    # then each path is mounted once, at its first position
    assert mounts == [Path("/shared"), Path("/base")]


def test_bind_mounts_raises_on_unknown_layer() -> None:
    # given a manifest declaring a layer that isn't defined in the layers mapping
    manifest = Manifest(distribution="arch", layers=["nonexistent"])
    resolved = ResolvedManifest(manifest, {})

    # when resolving the full set of bind mounts
    # then a clear error is raised
    with pytest.raises(ValueError, match="nonexistent"):
        resolved.bind_mounts


def test_packages_combines_common_and_distribution_packages() -> None:
    # given a manifest targeting arch, declaring common and per-distribution
    # packages
    manifest = Manifest(
        distribution="arch",
        packages={"common": ["python"], "arch": ["zsh"], "debian": ["other"]},
    )
    resolved = ResolvedManifest(manifest, {})

    # when resolving the full set of packages
    packages = resolved.packages

    # then the common packages and the packages for the manifest's own
    # distribution are included, and other distributions' packages are not
    assert packages == ["python", "zsh"]


def test_packages_applies_layers_before_the_project() -> None:
    # given a manifest with its own packages and one declared layer, and the
    # defined layers mapping, defining that layer's packages
    manifest = Manifest(
        distribution="arch", packages={"arch": ["project-pkg"]}, layers=["python"]
    )
    layers = {"python": Layer(packages={"arch": ["layer-pkg"]})}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of packages
    packages = resolved.packages

    # then the layer-level packages come first, followed by the project-level ones
    assert packages == ["layer-pkg", "project-pkg"]


def test_packages_merges_duplicates() -> None:
    # given a manifest and a declared layer both installing the same package,
    # once as a common package and once for the manifest's distribution, and
    # the layer installing another package as well
    manifest = Manifest(
        distribution="arch", packages={"arch": ["git"]}, layers=["base"]
    )
    layers = {"base": Layer(packages={"common": ["git"], "arch": ["zsh", "git"]})}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of packages
    packages = resolved.packages

    # then each package is installed once, at its first position
    assert packages == ["git", "zsh"]


def test_packages_removes_dash_prefixed_packages_from_lower_layers() -> None:
    # given a declared layer installing two packages for the manifest's
    # distribution, and a manifest removing one of them through its common
    # packages, and removing a package no layer installs
    manifest = Manifest(
        distribution="arch",
        packages={"common": ["-git", "-nonexistent"]},
        layers=["base"],
    )
    layers = {"base": Layer(packages={"arch": ["git", "zsh"]})}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of packages
    packages = resolved.packages

    # then the removed package is gone, and the removal of the package no
    # layer installs has no effect
    assert packages == ["zsh"]


def test_packages_removal_does_not_affect_its_own_layer() -> None:
    # given a declared layer installing a package, and a manifest both removing
    # and installing that package
    manifest = Manifest(
        distribution="arch",
        packages={"common": ["-git"], "arch": ["git"]},
        layers=["base"],
    )
    layers = {"base": Layer(packages={"arch": ["git", "zsh"]})}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of packages
    packages = resolved.packages

    # then the package is removed from the lower layer, but installed by the
    # manifest itself
    assert packages == ["zsh", "git"]


def test_packages_raises_on_unknown_layer() -> None:
    # given a manifest declaring a layer that isn't defined in the layers mapping
    manifest = Manifest(distribution="arch", layers=["nonexistent"])
    resolved = ResolvedManifest(manifest, {})

    # when resolving the full set of packages
    # then a clear error is raised
    with pytest.raises(ValueError, match="nonexistent"):
        resolved.packages


def test_agent_names_combines_agents_from_every_declared_layer() -> None:
    # given a manifest declaring two layers, each enabling an agent
    manifest = Manifest(distribution="arch", layers=["base", "python"])
    layers = {
        "base": Layer(agents=[AgentOption(name="claude")]),
        "python": Layer(agents=[AgentOption(name="other")]),
    }
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of agent names
    agent_names = resolved.agent_names

    # then the agent names from both layers are included, without being
    # resolved to actual agents
    assert agent_names == ["claude", "other"]


def test_agent_names_applies_layers_before_the_project() -> None:
    # given a manifest enabling its own agent and declaring one layer, and the
    # defined layers mapping, defining that layer's agent
    manifest = Manifest(
        distribution="arch", agents=[AgentOption(name="codex")], layers=["base"]
    )
    layers = {"base": Layer(agents=[AgentOption(name="claude")])}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of agent names
    agent_names = resolved.agent_names

    # then the layer's agent comes first, followed by the project-level one
    assert agent_names == ["claude", "codex"]


def test_agent_names_merges_duplicates() -> None:
    # given a manifest enabling an agent that its declared layer also enables,
    # alongside another agent
    manifest = Manifest(
        distribution="arch", agents=[AgentOption(name="claude")], layers=["base"]
    )
    layers = {
        "base": Layer(agents=[AgentOption(name="claude"), AgentOption(name="codex")])
    }
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of agent names
    agent_names = resolved.agent_names

    # then each agent is named once, at its first position
    assert agent_names == ["claude", "codex"]


def test_agent_names_removes_dash_prefixed_agents_from_lower_layers() -> None:
    # given a declared layer enabling two agents, and a manifest removing one of
    # them and an agent no layer enables
    manifest = Manifest(
        distribution="arch",
        agents=[AgentOption(name="-claude"), AgentOption(name="-pi")],
        layers=["base"],
    )
    layers = {
        "base": Layer(agents=[AgentOption(name="claude"), AgentOption(name="codex")])
    }
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of agent names
    agent_names = resolved.agent_names

    # then the removed agent is gone, and the removal of the agent no layer
    # enables has no effect
    assert agent_names == ["codex"]


def test_agent_names_raises_on_unknown_layer() -> None:
    # given a manifest declaring a layer that isn't defined in the layers mapping
    manifest = Manifest(distribution="arch", layers=["nonexistent"])
    resolved = ResolvedManifest(manifest, {})

    # when resolving the full set of agent names
    # then a clear error is raised
    with pytest.raises(ValueError, match="nonexistent"):
        resolved.agent_names


def test_agents_resolves_each_configured_agent_name_in_order() -> None:
    # given a manifest declaring two layers, each enabling an agent
    manifest = Manifest(distribution="arch", layers=["base", "python"])
    layers = {
        "base": Layer(agents=[AgentOption(name="claude")]),
        "python": Layer(agents=[AgentOption(name="other")]),
    }
    resolved = ResolvedManifest(manifest, layers)
    claude_agent = Agent(name="claude")
    other_agent = Agent(name="other")

    # when resolving the full set of agents
    with patch("ask.manifest.agent.resolve") as resolve:
        resolve.side_effect = {"claude": claude_agent, "other": other_agent}.__getitem__
        agents = resolved.agents

    # then each configured agent name is resolved, in order
    resolve.assert_has_calls([call("claude"), call("other")])
    assert agents == [claude_agent, other_agent]


def test_shared_state_mounts_calls_mounts_for_with_each_agents_options() -> None:
    # given a manifest declaring one layer with shared state enabled,
    # declaring an agent with its own options, and another layer without
    # shared state
    manifest = Manifest(distribution="arch", layers=["base", "python"])
    layers = {
        "base": Layer(
            agents=[AgentOption(name="claude", options={"auth": False})],
            shared_state=True,
        ),
        "python": Layer(agents=[AgentOption(name="other")], shared_state=False),
    }
    resolved = ResolvedManifest(manifest, layers)
    claude_agent = MagicMock()
    claude_mounts = [
        Mount(host_path=Path("/host/state"), container_path=Path("/container/state"))
    ]
    claude_agent.mounts_for.return_value = claude_mounts
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when resolving the mounts whose state should be shared
    with patch("ask.manifest.agent.resolve", return_value=claude_agent) as resolve:
        mounts = resolved.shared_state_mounts(user)

    # then only the agent from the shared-state layer is resolved, its
    # mounts_for is called with the user and its own options, and the
    # resulting mounts are returned
    resolve.assert_called_once_with("claude")
    claude_agent.mounts_for.assert_called_once_with(user, {"auth": False})
    assert mounts == claude_mounts


def test_shared_state_mounts_includes_project_agents_with_shared_state() -> None:
    # given a manifest with shared state enabled, declaring its own agent with
    # options, and no layers
    manifest = Manifest(
        distribution="arch",
        agents=[AgentOption(name="codex", options={"auth": False})],
        shared_state=True,
    )
    resolved = ResolvedManifest(manifest, {})
    codex_agent = MagicMock()
    codex_mounts = [
        Mount(host_path=Path("/host/codex"), container_path=Path("/container/codex"))
    ]
    codex_agent.mounts_for.return_value = codex_mounts
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when resolving the mounts whose state should be shared
    with patch("ask.manifest.agent.resolve", return_value=codex_agent) as resolve:
        mounts = resolved.shared_state_mounts(user)

    # then the project's agent is resolved, its mounts_for is called with the
    # user and its own options, and the resulting mounts are returned
    resolve.assert_called_once_with("codex")
    codex_agent.mounts_for.assert_called_once_with(user, {"auth": False})
    assert mounts == codex_mounts


def _user() -> ResolvedUser:
    return ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )


def test_shared_state_mounts_merges_agent_options_with_later_layers_winning() -> None:
    # given a declared layer sharing state for an agent with two options, and a
    # manifest enabling the same agent, overriding one option and leaving
    # shared state unset
    manifest = Manifest(
        distribution="arch",
        agents=[AgentOption(name="claude", options={"auth": True})],
        layers=["base"],
    )
    layers = {
        "base": Layer(
            agents=[
                AgentOption(name="claude", options={"auth": False, "skills": False})
            ],
            shared_state=True,
        )
    }
    resolved = ResolvedManifest(manifest, layers)
    claude_agent = MagicMock()
    claude_agent.mounts_for.return_value = []

    # when resolving the mounts whose state should be shared
    with patch("ask.manifest.agent.resolve", return_value=claude_agent):
        resolved.shared_state_mounts(_user())

    # then the agent's state is still shared, and its mounts are resolved once
    # with the merged options, the manifest's value winning
    claude_agent.mounts_for.assert_called_once_with(
        _user(), {"auth": True, "skills": False}
    )


def test_shared_state_mounts_lets_later_layers_turn_sharing_off() -> None:
    # given a declared layer sharing state for an agent, and a manifest enabling
    # the same agent with shared state explicitly off
    manifest = Manifest(
        distribution="arch",
        agents=[AgentOption(name="claude")],
        shared_state=False,
        layers=["base"],
    )
    layers = {"base": Layer(agents=[AgentOption(name="claude")], shared_state=True)}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the mounts whose state should be shared
    with patch("ask.manifest.agent.resolve") as resolve:
        mounts = resolved.shared_state_mounts(_user())

    # then the agent's state is not shared
    resolve.assert_not_called()
    assert mounts == []


def test_shared_state_mounts_forgets_options_and_sharing_of_removed_agents() -> None:
    # given a declared layer sharing state for an agent with an option, a
    # second layer removing that agent, and a manifest enabling it again
    # without options or shared state
    manifest = Manifest(
        distribution="arch",
        agents=[AgentOption(name="claude")],
        layers=["base", "no-claude"],
    )
    layers = {
        "base": Layer(
            agents=[AgentOption(name="claude", options={"auth": False})],
            shared_state=True,
        ),
        "no-claude": Layer(agents=[AgentOption(name="-claude")]),
    }
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the mounts whose state should be shared
    with patch("ask.manifest.agent.resolve") as resolve:
        mounts = resolved.shared_state_mounts(_user())

    # then the re-enabled agent does not inherit the removed agent's shared
    # state, so nothing is shared
    resolve.assert_not_called()
    assert mounts == []


def test_shared_state_mounts_raises_on_unknown_layer() -> None:
    # given a manifest declaring a layer that isn't defined in the layers mapping
    manifest = Manifest(distribution="arch", layers=["nonexistent"])
    resolved = ResolvedManifest(manifest, {})
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when resolving the mounts whose state should be shared
    # then a clear error is raised
    with pytest.raises(ValueError, match="nonexistent"):
        resolved.shared_state_mounts(user)


def test_load_reports_syntax_errors_as_config_errors(tmp_path: Path) -> None:
    # given a manifest file with a syntax error
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text("distribution = \n")

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then the error names the file
    assert error.value.path == manifest_path


def test_load_requires_a_distribution(tmp_path: Path) -> None:
    # given a manifest file without a distribution
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('layers = ["base"]\n')

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then the missing distribution is reported against the file
    assert error.value.path == manifest_path
    assert error.value.problems == ["distribution: Field required"]


def test_load_reports_every_wrongly_typed_value(tmp_path: Path) -> None:
    # given a manifest file with several wrongly typed values
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text(
        'distribution = 1\nlayers = "base"\npackages.arch = ["git", 2]\n'
    )

    # when loading the manifest
    with pytest.raises(ConfigError) as error:
        load(manifest_path)

    # then all of them are reported together
    assert error.value.problems == [
        "packages.arch.1: Input should be a valid string",
        "distribution: Input should be a valid string",
        "layers: Input should be a valid list",
    ]
