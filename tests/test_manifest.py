from pathlib import Path

import pytest

from ask.config import Config, Layer
from ask.manifest import Manifest, load, resolve_bind_mounts, resolve_packages


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


def test_resolve_bind_mounts_combines_project_and_layer_mounts() -> None:
    # given a manifest with its own bind mount and one declared layer, and a config
    # defining that layer's bind mount
    manifest = Manifest(
        distribution="arch", bind_mounts=[Path("/project/mount")], layers=["python"]
    )
    config = Config(layers={"python": Layer(bind_mounts=[Path("/layer/mount")])})

    # when resolving the full set of bind mounts
    mounts = resolve_bind_mounts(manifest, config)

    # then the project-level and layer-level mounts are both included
    assert mounts == [Path("/project/mount"), Path("/layer/mount")]


def test_resolve_bind_mounts_raises_on_unknown_layer() -> None:
    # given a manifest declaring a layer that isn't defined in the config
    manifest = Manifest(distribution="arch", layers=["nonexistent"])
    config = Config(layers={})

    # when resolving the full set of bind mounts
    # then a clear error is raised
    with pytest.raises(ValueError, match="nonexistent"):
        resolve_bind_mounts(manifest, config)


def test_resolve_packages_combines_common_and_distribution_packages() -> None:
    # given a manifest targeting arch, declaring common and per-distribution
    # packages
    manifest = Manifest(
        distribution="arch",
        packages={"common": ["python"], "arch": ["zsh"], "debian": ["other"]},
    )
    config = Config(layers={})

    # when resolving the full set of packages
    packages = resolve_packages(manifest, config)

    # then the common packages and the packages for the manifest's own
    # distribution are included, and other distributions' packages are not
    assert packages == ["python", "zsh"]


def test_resolve_packages_combines_project_and_layer_packages() -> None:
    # given a manifest with its own packages and one declared layer, and a
    # config defining that layer's packages
    manifest = Manifest(
        distribution="arch", packages={"arch": ["project-pkg"]}, layers=["python"]
    )
    config = Config(layers={"python": Layer(packages={"arch": ["layer-pkg"]})})

    # when resolving the full set of packages
    packages = resolve_packages(manifest, config)

    # then the project-level and layer-level packages are both included
    assert packages == ["project-pkg", "layer-pkg"]


def test_resolve_packages_raises_on_unknown_layer() -> None:
    # given a manifest declaring a layer that isn't defined in the config
    manifest = Manifest(distribution="arch", layers=["nonexistent"])
    config = Config(layers={})

    # when resolving the full set of packages
    # then a clear error is raised
    with pytest.raises(ValueError, match="nonexistent"):
        resolve_packages(manifest, config)
