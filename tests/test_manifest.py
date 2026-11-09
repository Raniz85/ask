from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ask.agent import Agent
from ask.config import AgentOption, Layer, ResolvedUser
from ask.incus import Mount
from ask.manifest import Manifest, ResolvedManifest, load


def test_load_reads_distribution_from_toml(tmp_path: Path) -> None:
    # given a manifest file declaring a distribution
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then the distribution is available on the result
    assert manifest == Manifest(distribution="arch")


def test_load_ignores_unknown_fields(tmp_path: Path) -> None:
    # given a manifest file with an unknown field alongside the distribution
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('distribution = "arch"\nide = "jetbrains-idea"\n')

    # when loading the manifest
    manifest = load(manifest_path)

    # then the unknown field is ignored and distribution is still read
    assert manifest == Manifest(distribution="arch")


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


def test_bind_mounts_combines_project_and_layer_mounts() -> None:
    # given a manifest with its own bind mount and one declared layer, and the
    # defined layers mapping, defining that layer's bind mount
    manifest = Manifest(
        distribution="arch", bind_mounts=[Path("/project/mount")], layers=["python"]
    )
    layers = {"python": Layer(bind_mounts=[Path("/layer/mount")])}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of bind mounts
    mounts = resolved.bind_mounts

    # then the project-level and layer-level mounts are both included
    assert mounts == [Path("/project/mount"), Path("/layer/mount")]


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


def test_packages_combines_project_and_layer_packages() -> None:
    # given a manifest with its own packages and one declared layer, and the
    # defined layers mapping, defining that layer's packages
    manifest = Manifest(
        distribution="arch", packages={"arch": ["project-pkg"]}, layers=["python"]
    )
    layers = {"python": Layer(packages={"arch": ["layer-pkg"]})}
    resolved = ResolvedManifest(manifest, layers)

    # when resolving the full set of packages
    packages = resolved.packages

    # then the project-level and layer-level packages are both included
    assert packages == ["project-pkg", "layer-pkg"]


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
