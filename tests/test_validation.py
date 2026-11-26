from pathlib import Path

import pytest

from ask.config import Config, ConfigError, Flavor, FlavorError, Layer, LayerWhen
from ask.manifest import Manifest, ResolvedManifest
from ask.shell import ShellOption
from ask.validation import (
    ManifestNotFoundError,
    check_manifest,
    find_project_dir,
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

    # then the error says where ask looked and hints at ask init
    assert str(error.value) == (
        f"No ask.toml found in {tmp_path}. "
        "Run `ask init` to create one, or run ask from a project directory "
        "containing ask.toml."
    )


def test_find_project_dir_returns_the_start_dir_when_it_contains_ask_toml(
    tmp_path: Path,
) -> None:
    # given a directory containing an ask.toml
    (tmp_path / "ask.toml").write_text("")

    # when finding the project directory from it
    project_dir = find_project_dir(tmp_path)

    # then it is the directory itself
    assert project_dir == tmp_path


def test_find_project_dir_traverses_parents_until_it_finds_ask_toml(
    tmp_path: Path,
) -> None:
    # given an ask.toml in a parent directory, and a child directory below it
    (tmp_path / "ask.toml").write_text("")
    child = tmp_path / "src" / "ask"
    child.mkdir(parents=True)

    # when finding the project directory from the child
    project_dir = find_project_dir(child)

    # then it is the parent directory containing the ask.toml
    assert project_dir == tmp_path


def test_find_project_dir_returns_the_start_dir_when_no_ask_toml_exists(
    tmp_path: Path,
) -> None:
    # given a directory tree without any ask.toml up to the root
    child = tmp_path / "src" / "ask"
    child.mkdir(parents=True)

    # when finding the project directory from the child
    project_dir = find_project_dir(child)

    # then it falls back to the start directory, so load_manifest reports the
    # missing manifest against it
    assert project_dir == child


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
    assert resolved == ResolvedManifest(m, flavor, "arch", tmp_path)


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


def test_check_manifest_reports_missing_taskfiles(tmp_path: Path) -> None:
    # given a manifest referencing a taskfile that exists and one that does not
    existing = tmp_path / "provision.py"
    existing.touch()
    missing = tmp_path / "missing.py"
    m = Manifest(taskfiles=[existing, missing])

    # when checking it
    problems = check_manifest(m)

    # then only the missing taskfile is reported, at its position in the manifest
    assert problems == [f"taskfiles.1: path {missing} does not exist"]


def test_load_manifest_reports_missing_taskfiles_against_the_file(
    tmp_path: Path,
) -> None:
    # given a manifest file referencing a taskfile that does not exist
    manifest_path = tmp_path / "ask.toml"
    manifest_path.write_text('taskfiles = ["missing.py"]\n')

    # when loading it
    with pytest.raises(ConfigError) as error:
        load_manifest(manifest_path)

    # then the problem is reported against the file, with the path resolved
    # against the manifest's directory
    assert (error.value.path, error.value.problems) == (
        manifest_path,
        [f"taskfiles.0: path {tmp_path / 'missing.py'} does not exist"],
    )


def test_resolve_project_reports_missing_taskfiles_from_applied_layers(
    tmp_path: Path,
) -> None:
    # given a default flavour with a base layer referencing a missing taskfile,
    # and a layer that does not apply to the project with the same missing path
    missing = tmp_path / "missing.py"
    flavor = Flavor(
        distribution="arch",
        default=True,
        layers={
            "base": Layer(taskfiles=[missing]),
            "python": Layer(
                taskfiles=[missing], when=LayerWhen(files=["pyproject.toml"])
            ),
        },
    )
    flavors_dir = tmp_path / "flavors"

    # when resolving the project
    with pytest.raises(ConfigError) as error:
        resolve_project(
            flavors_dir, Config(flavors={"arch": flavor}), Manifest(), tmp_path
        )

    # then the missing taskfile is reported once against the flavour file, by
    # its position in the applied layer
    assert (error.value.path, error.value.problems) == (
        flavors_dir / "arch.toml",
        [f"layers.base.taskfiles.0: path {missing} does not exist"],
    )
