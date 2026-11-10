from pathlib import Path

import pytest

from ask.agent import AgentOption
from ask.config import Config, ConfigError, Flavor, FlavorError, Layer, LayerWhen
from ask.manifest import Manifest, ResolvedManifest
from ask.shell import ShellOption
from ask.validation import (
    ManifestNotFoundError,
    check_manifest,
    flavor_warnings,
    load_config,
    load_manifest,
    resolve_project,
)


def test_load_config_returns_valid_configs(tmp_path: Path) -> None:
    # given a flavours directory with a valid flavour file
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()
    (flavors_dir / "arch.toml").write_text('distribution = "arch"\nshell = "zsh"\n')

    # when loading it
    cfg = load_config(flavors_dir)

    # then the config is returned
    assert cfg == Config(
        flavors={
            "arch": Flavor(
                distribution="arch", default=True, shell=ShellOption(name="zsh")
            )
        }
    )


def test_flavor_warnings_reports_options_on_removed_agents() -> None:
    # given a flavour layer removing one agent with options and one without,
    # and enabling another agent with options
    flavor = Flavor(
        distribution="arch",
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
    warnings = flavor_warnings(flavor)

    # then only the removal with options is reported, by its position in the
    # flavour file
    assert warnings == [
        "layers.base.agents.0: options have no effect when removing agent 'claude'"
    ]


def test_load_config_prints_warnings_against_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # given a flavour file with a layer removing an agent with options
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()
    (flavors_dir / "arch.toml").write_text(
        'distribution = "arch"\n'
        '[layers.base]\nagents = [{ name = "-claude", auth = false }]\n'
    )

    # when loading the flavours
    load_config(flavors_dir)

    # then the warning is printed to stderr against the flavour file
    assert capsys.readouterr().err == (
        f"ask: warning in {flavors_dir / 'arch.toml'}\n"
        "  layers.base.agents.0: options have no effect when "
        "removing agent 'claude'\n"
    )


def test_load_manifest_returns_valid_manifests(tmp_path: Path) -> None:
    # given a valid manifest file
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('packages = ["git"]\n')

    # when loading it
    m = load_manifest(manifest_path)

    # then the manifest is returned
    assert m == Manifest(packages=["git"])


def test_load_manifest_reports_a_missing_manifest(tmp_path: Path) -> None:
    # given a project directory without an ask.toml
    path = tmp_path / "ask.toml"

    # when loading the manifest
    with pytest.raises(ManifestNotFoundError) as error:
        load_manifest(path)

    # then the error says where ask looked and what it needs
    assert str(error.value) == (
        f"No ask.toml found in {tmp_path}. "
        "Run ask from a project directory containing ask.toml."
    )


def test_check_manifest_reports_missing_bind_mount_sources(tmp_path: Path) -> None:
    # given a manifest bind mounting a path that exists and one that does not
    missing = tmp_path / "missing"
    m = Manifest(bind_mounts=[tmp_path, missing])

    # when checking it
    problems = check_manifest(m)

    # then only the missing path is reported, at its position in the manifest
    assert problems == [f"bind_mounts.1: path {missing} does not exist"]


def test_load_manifest_reports_problems_against_the_file(tmp_path: Path) -> None:
    # given a manifest file bind mounting a path that does not exist
    missing = tmp_path / "missing"
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text(f'bind_mounts = ["{missing}"]\n')

    # when loading it
    with pytest.raises(ConfigError) as error:
        load_manifest(manifest_path)

    # then the problem is reported against the file
    assert (error.value.path, error.value.problems) == (
        manifest_path,
        [f"bind_mounts.0: path {missing} does not exist"],
    )


def test_resolve_project_resolves_the_manifest_against_the_selected_flavor(
    tmp_path: Path,
) -> None:
    # given a default flavour and a manifest
    flavor = Flavor(distribution="arch", default=True, layers={"base": Layer()})
    m = Manifest(packages=["git"])

    # when resolving the project
    resolved = resolve_project(
        tmp_path / "flavors", Config(flavors={"arch": flavor}), m, tmp_path
    )

    # then the manifest is resolved against that flavour, for the project
    assert resolved == ResolvedManifest(m, flavor, tmp_path)


def test_resolve_project_reports_projects_no_flavor_applies_to(
    tmp_path: Path,
) -> None:
    # given a global config without any flavours
    cfg = Config(flavors={})

    # when resolving the project
    with pytest.raises(FlavorError) as error:
        resolve_project(tmp_path / "flavors", cfg, Manifest(), tmp_path)

    # then the error says that no flavour applies
    assert str(error.value) == (
        f"No flavour applies to {tmp_path}. Add a flavour whose when.path "
        "matches it, or mark one with default = true."
    )


def test_resolve_project_reports_missing_bind_mount_sources_from_applied_layers(
    tmp_path: Path,
) -> None:
    # given a default flavour with a base layer bind mounting a missing path,
    # and a layer that does not apply to the project with the same missing path
    missing = tmp_path / "missing"
    flavor = Flavor(
        distribution="arch",
        default=True,
        layers={
            "base": Layer(bind_mounts=[tmp_path, missing]),
            "python": Layer(
                bind_mounts=[missing], when=LayerWhen(files=["pyproject.toml"])
            ),
        },
    )
    flavors_dir = tmp_path / "flavors"

    # when resolving the project
    with pytest.raises(ConfigError) as error:
        resolve_project(
            flavors_dir, Config(flavors={"arch": flavor}), Manifest(), tmp_path
        )

    # then the missing path is reported once against the flavour file, by its
    # position in the applied layer
    assert (error.value.path, error.value.problems) == (
        flavors_dir / "arch.toml",
        [f"layers.base.bind_mounts.1: path {missing} does not exist"],
    )
