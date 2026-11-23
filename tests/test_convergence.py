import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from ask.agent import AgentSettings, AgentTable
from ask.config import Flavor, Layer, LayerWhen, User
from ask.convergence import effective_configuration, fingerprint
from ask.incus import Fingerprint
from ask.manifest import Manifest, ResolvedManifest
from ask.shell import ShellOption


def test_effective_configuration_contains_everything_that_converge_uses(
    tmp_path: Path,
) -> None:
    # given a manifest
    m = Manifest(
        packages=["ripgrep"],
        bind_mounts=[Path("/src")],
        tool_managers=["mise"],
    )

    # and a flavour with a user, a shell and a base layer
    flavor = Flavor(
        distribution="arch",
        shell=ShellOption(name="zsh"),
        user=User(name="raniz", uid=1000),
        layers={
            "base": Layer(
                packages=["git"],
                agents=AgentTable(entries={"claude": AgentSettings()}),
            )
        },
    )

    # when building the effective configuration
    configuration = effective_configuration(ResolvedManifest(m, flavor, tmp_path))

    # then it holds the flavour's distribution, shell and user, the layers that
    # apply, in order, and the manifest
    assert json.loads(configuration) == {
        "flavor": {
            "distribution": "arch",
            "shell": {"name": "zsh", "options": {}},
            "user": {
                "name": "raniz",
                "uid": 1000,
                "extra_groups": [],
                "group": {"name": None, "gid": None},
            },
        },
        "layers": [
            {
                "name": "base",
                "bind_mounts": [],
                "taskfiles": [],
                "packages": ["git"],
                "agents": {
                    "entries": {
                        "claude": {"enabled": True, "options": {}, "extensions": []}
                    }
                },
                "ides": [],
                "env": {},
                "services": {},
                "order": 0,
                "when": None,
            },
        ],
        "manifest": {
            "taskfiles": [],
            "packages": ["ripgrep"],
            "bind_mounts": ["/src"],
            "tool_managers": ["mise"],
            "services": {},
            "env": {},
        },
        "tool_manager_configs": {},
        "taskfiles": {},
    }


def test_effective_configuration_ignores_layers_that_do_not_apply(
    tmp_path: Path,
) -> None:
    # given flavours that differ only in a layer that does not apply to the
    # project
    base = Layer(packages=["git"])
    flavor = Flavor(distribution="arch", layers={"base": base})
    flavor_with_unapplied_layer = Flavor(
        distribution="arch",
        layers={
            "base": base,
            "python": Layer(
                packages=["python"], when=LayerWhen(files=["pyproject.toml"])
            ),
        },
    )

    # when building the effective configuration for both
    configurations = (
        effective_configuration(ResolvedManifest(Manifest(), flavor, tmp_path)),
        effective_configuration(
            ResolvedManifest(Manifest(), flavor_with_unapplied_layer, tmp_path)
        ),
    )

    # then they are identical
    assert configurations[0] == configurations[1]


def test_effective_configuration_ignores_the_default_agent(tmp_path: Path) -> None:
    # given flavours that differ only in their default agent
    def flavor(default: str) -> Flavor:
        return Flavor(
            distribution="arch",
            layers={
                "base": Layer(
                    agents=AgentTable(
                        default=default,
                        entries={"claude": AgentSettings(), "codex": AgentSettings()},
                    )
                )
            },
        )

    # when building the effective configuration for both
    configurations = (
        effective_configuration(
            ResolvedManifest(Manifest(), flavor("claude"), tmp_path)
        ),
        effective_configuration(
            ResolvedManifest(Manifest(), flavor("codex"), tmp_path)
        ),
    )

    # then they are identical, as the default agent only matters when an
    # agent is launched
    assert configurations[0] == configurations[1]


def test_effective_configuration_ignores_agent_environment_variables(
    tmp_path: Path,
) -> None:
    # given flavours that differ only in the variables they set for agents
    def flavor(value: str) -> Flavor:
        return Flavor(
            distribution="arch",
            layers={
                "base": Layer(
                    agents=AgentTable(
                        env={"FOO": value},
                        entries={"claude": AgentSettings(env={"BAR": value})},
                    )
                )
            },
        )

    # when building the effective configuration for both
    configurations = (
        effective_configuration(ResolvedManifest(Manifest(), flavor("a"), tmp_path)),
        effective_configuration(ResolvedManifest(Manifest(), flavor("b"), tmp_path)),
    )

    # then they are identical, as agent variables only matter when an agent is
    # launched
    assert configurations[0] == configurations[1]


def test_effective_configuration_changes_with_instance_environment_variables(
    tmp_path: Path,
) -> None:
    # given a layer and a manifest setting instance variables
    flavor = Flavor(distribution="arch", layers={"base": Layer(env={"A": "1"})})
    m = Manifest(env={"B": "2"})

    # when building the effective configuration
    configuration = json.loads(
        effective_configuration(ResolvedManifest(m, flavor, tmp_path))
    )

    # then it holds the variables, as they are provisioned on the instance
    assert configuration["layers"][0]["env"] == {"A": "1"}
    assert configuration["manifest"]["env"] == {"B": "2"}


def test_effective_configuration_changes_when_a_layer_starts_to_apply(
    tmp_path: Path,
) -> None:
    # given a flavour with a layer applying to projects with a pyproject.toml
    flavor = Flavor(
        distribution="arch",
        layers={"python": Layer(when=LayerWhen(files=["pyproject.toml"]))},
    )
    resolved = ResolvedManifest(Manifest(), flavor, tmp_path)
    before = effective_configuration(resolved)

    # and the project gaining a pyproject.toml
    (tmp_path / "pyproject.toml").write_text("")

    # when building the effective configuration again
    after = effective_configuration(resolved)

    # then it is different
    assert before != after


def test_effective_configuration_contains_the_projects_mise_config(
    tmp_path: Path,
) -> None:
    # given a project with a mise.toml, whose manifest opts into mise
    (tmp_path / "mise.toml").write_text('[tools]\nerlang = "29.1.1"\n')
    m = Manifest(tool_managers=["mise"])

    # when building the effective configuration
    configuration = effective_configuration(
        ResolvedManifest(m, Flavor(distribution="arch"), tmp_path)
    )

    # then it holds the contents of the mise config, by file
    assert json.loads(configuration)["tool_manager_configs"] == {
        "mise": {"mise.toml": '[tools]\nerlang = "29.1.1"\n'}
    }


def test_effective_configuration_leaves_out_config_of_tool_managers_not_opted_into(
    tmp_path: Path,
) -> None:
    # given a project with a mise.toml, whose manifest does not opt into mise
    (tmp_path / "mise.toml").write_text('[tools]\nerlang = "29.1.1"\n')

    # when building the effective configuration
    configuration = effective_configuration(
        ResolvedManifest(Manifest(), Flavor(distribution="arch"), tmp_path)
    )

    # then the mise config is not part of it
    assert json.loads(configuration)["tool_manager_configs"] == {}


def test_effective_configuration_contains_the_pi_extensions(tmp_path: Path) -> None:
    # given a layer declaring extensions for pi
    flavor = Flavor(
        distribution="arch",
        layers={
            "base": Layer(
                agents=AgentTable(
                    entries={"pi": AgentSettings(extensions=["@foo/bar"])}
                )
            )
        },
    )

    # when building the effective configuration
    configuration = json.loads(
        effective_configuration(ResolvedManifest(Manifest(), flavor, tmp_path))
    )

    # then it holds the extensions, as they are provisioned on the instance
    assert configuration["layers"][0]["agents"]["entries"]["pi"]["extensions"] == [
        "@foo/bar"
    ]


def test_effective_configuration_changes_with_the_pi_extensions(
    tmp_path: Path,
) -> None:
    # given flavours that differ only in the extensions declared for pi
    def flavor(extensions: list[str]) -> Flavor:
        return Flavor(
            distribution="arch",
            layers={
                "base": Layer(
                    agents=AgentTable(
                        entries={"pi": AgentSettings(extensions=extensions)}
                    )
                )
            },
        )

    # when building the effective configuration for both
    configurations = (
        effective_configuration(
            ResolvedManifest(Manifest(), flavor(["@foo/bar"]), tmp_path)
        ),
        effective_configuration(
            ResolvedManifest(Manifest(), flavor(["@foo/baz"]), tmp_path)
        ),
    )

    # then they are different
    assert configurations[0] != configurations[1]


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


def test_effective_configuration_contains_taskfile_digests(tmp_path: Path) -> None:
    # given a layer and a manifest each declaring a taskfile
    layer_task = tmp_path / "layer-task.py"
    layer_task.write_text("# layer task\n")
    manifest_task = tmp_path / "manifest-task.py"
    manifest_task.write_text("# manifest task\n")
    flavor = Flavor(distribution="arch", layers={"base": Layer(taskfiles=[layer_task])})
    m = Manifest(taskfiles=[manifest_task])

    # when building the effective configuration
    configuration = json.loads(
        effective_configuration(ResolvedManifest(m, flavor, tmp_path))
    )

    # then every taskfile is represented by the hash of its contents
    assert configuration["taskfiles"] == {
        str(layer_task): hashlib.sha256(b"# layer task\n").hexdigest(),
        str(manifest_task): hashlib.sha256(b"# manifest task\n").hexdigest(),
    }


def test_effective_configuration_changes_with_taskfile_contents(tmp_path: Path) -> None:
    # given a taskfile whose contents change between two resolutions
    task = tmp_path / "task.py"

    def configuration_with(contents: str) -> str:
        task.write_text(contents)
        flavor = Flavor(distribution="arch", layers={"base": Layer(taskfiles=[task])})
        return effective_configuration(ResolvedManifest(Manifest(), flavor, tmp_path))

    # then the effective configuration changes with the taskfile's contents
    assert configuration_with("a = 1\n") != configuration_with("a = 2\n")
