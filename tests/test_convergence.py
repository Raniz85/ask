import json
from pathlib import Path
from unittest.mock import patch

from ask.agent import AgentOption
from ask.config import Config, Layer, User
from ask.convergence import effective_configuration, fingerprint
from ask.incus import Fingerprint
from ask.manifest import Manifest
from ask.shell import ShellOption


def test_effective_configuration_contains_everything_that_converge_uses(
    tmp_path: Path,
) -> None:
    # given a manifest using a layer from the global config
    m = Manifest(
        distribution="arch",
        layers=["base"],
        bind_mounts=[Path("/src")],
        packages={"arch": ["ripgrep"]},
        agents=[AgentOption(name="claude")],
        tool_managers=["-mise"],
    )

    # and a global config defining that layer, a user and a shell
    cfg = Config(
        shell=ShellOption(name="zsh"),
        user=User(name="raniz", uid=1000),
        layers={"base": Layer(packages={"arch": ["git"]})},
    )

    # when building the effective configuration
    configuration = effective_configuration(m, cfg, tmp_path)

    # then it holds the manifest, the layer it uses, and the user and shell
    assert json.loads(configuration) == {
        "manifest": {
            "distribution": "arch",
            "layers": ["base"],
            "bind_mounts": ["/src"],
            "packages": {"arch": ["ripgrep"]},
            "agents": [{"name": "claude", "options": {}}],
            "tool_managers": ["-mise"],
        },
        "layers": {
            "base": {
                "bind_mounts": [],
                "packages": {"arch": ["git"]},
                "agents": [],
                "tool_managers": [],
            },
        },
        "user": {
            "name": "raniz",
            "uid": 1000,
            "extra_groups": [],
            "group": {"name": None, "gid": None},
        },
        "shell": {"name": "zsh", "options": {}},
        "tool_manager_configs": {},
    }


def test_effective_configuration_ignores_layers_the_manifest_does_not_use(
    tmp_path: Path,
) -> None:
    # given a manifest using one layer
    m = Manifest(distribution="arch", layers=["base"])

    # and global configs that differ only in a layer the manifest does not use
    base = Layer(packages={"arch": ["git"]})
    cfg = Config(layers={"base": base})
    cfg_with_unused_layer = Config(
        layers={"base": base, "unused": Layer(packages={"arch": ["emacs"]})}
    )

    # when building the effective configuration for both
    configurations = (
        effective_configuration(m, cfg, tmp_path),
        effective_configuration(m, cfg_with_unused_layer, tmp_path),
    )

    # then they are identical
    assert configurations[0] == configurations[1]


def test_effective_configuration_does_not_depend_on_table_key_order(
    tmp_path: Path,
) -> None:
    # given manifests that declare the same packages in a different table order
    m = Manifest(distribution="arch", packages={"arch": ["git"], "debian": ["vim"]})
    reordered = Manifest(
        distribution="arch", packages={"debian": ["vim"], "arch": ["git"]}
    )

    # when building the effective configuration for both
    configurations = (
        effective_configuration(m, Config(), tmp_path),
        effective_configuration(reordered, Config(), tmp_path),
    )

    # then they are identical
    assert configurations[0] == configurations[1]


def test_effective_configuration_contains_the_projects_mise_config(
    tmp_path: Path,
) -> None:
    # given a project with a mise.toml
    (tmp_path / "mise.toml").write_text('[tools]\nerlang = "29.1.1"\n')

    # when building the effective configuration
    configuration = effective_configuration(
        Manifest(distribution="arch"), Config(), tmp_path
    )

    # then it holds the contents of the mise config, by file
    assert json.loads(configuration)["tool_manager_configs"] == {
        "mise": {"mise.toml": '[tools]\nerlang = "29.1.1"\n'}
    }


def test_effective_configuration_leaves_out_config_of_opted_out_tool_managers(
    tmp_path: Path,
) -> None:
    # given a project with a mise.toml, whose manifest opts out of mise
    (tmp_path / "mise.toml").write_text('[tools]\nerlang = "29.1.1"\n')
    m = Manifest(distribution="arch", tool_managers=["-mise"])

    # when building the effective configuration
    configuration = effective_configuration(m, Config(), tmp_path)

    # then the mise config is not part of it
    assert json.loads(configuration)["tool_manager_configs"] == {}


def test_fingerprint_is_the_installed_version_and_a_hash_of_the_configuration() -> None:
    # given an installed version of ask
    with patch("ask.convergence.version", return_value="1.2.3"):
        # when fingerprinting a configuration
        result = fingerprint('{"distribution":"arch"}')

    # then it holds that version and the SHA-256 of the configuration
    assert result == Fingerprint(
        version="1.2.3",
        config_hash="b4d08efec2bc0df9d45d54d803868e9963a72785c179ce078a4fdab29322ebb8",
    )
