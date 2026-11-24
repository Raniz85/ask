from pathlib import Path

import pytest

from ask import config
from ask.config import ConfigError
from ask.ide import (
    Ide,
    Pycharm,
    known_names,
    known_with_aliases,
    resolve,
    resolve_name,
)
from ask.incus import Mount
from ask.user import ResolvedUser


def test_pycharm_has_its_packages_and_state_paths() -> None:
    # given the pycharm ide
    # when inspecting its properties
    pycharm = Pycharm()

    # then its arch packages include the AUR package and xwayland-satellite,
    # and its state paths cover the JetBrains config directories
    assert pycharm.packages_for("arch") == [
        "aur:pycharm",
        "xwayland-satellite",
    ]
    assert pycharm.packages_for("debian") == ["curl", "tar", "gzip"]
    assert pycharm.config_paths == [
        ".config/JetBrains",
        ".local/share/JetBrains",
        ".cache/JetBrains",
    ]


def test_resolve_returns_pycharm_for_pycharm() -> None:
    # given the name "pycharm"
    # when resolving it to an ide
    # then the Pycharm ide is returned
    assert resolve("pycharm") == Pycharm()


def test_resolve_raises_for_unknown_ide() -> None:
    # given a name with no known ide
    # when resolving it to an ide
    # then a clear error is raised
    with pytest.raises(ValueError, match="vscode"):
        resolve("vscode")


def test_resolve_name_returns_none_for_unknown_ide() -> None:
    # given a name with no known ide
    # when resolving it as a command-line name
    # then None is returned
    assert resolve_name("vscode") is None
    assert resolve_name("pycharm") == Pycharm()


def test_known_names_lists_every_supported_ide_sorted() -> None:
    # given the registry of supported ides
    # when listing the known ide names
    # then every supported ide is listed, sorted by name
    assert known_names() == [
        "clion",
        "datagrip",
        "goland",
        "idea",
        "phpstorm",
        "pycharm",
        "rider",
        "rubymine",
        "rustrover",
        "webstorm",
    ]


def test_known_with_aliases_lists_each_ides_aliases() -> None:
    # given the registry of supported ides
    # when listing the known names for command-line help
    # then each ide is listed by name, with aliases where they exist
    assert known_with_aliases() == [
        "clion",
        "datagrip",
        "goland",
        "idea (aliases: intellij-idea)",
        "phpstorm",
        "pycharm",
        "rider",
        "rubymine",
        "rustrover",
        "webstorm",
    ]


def test_packages_for_combines_common_and_distribution_packages() -> None:
    # given an ide with common, per-distribution, and other-distribution
    # packages
    test_ide = Ide(
        name="test",
        packages={"common": ["shared-pkg"], "arch": ["arch-pkg"], "debian": ["other"]},
    )

    # when resolving its packages for the target distribution
    packages = test_ide.packages_for("arch")

    # then the common packages and the target distribution's packages are
    # included, and the other distribution's packages are not
    assert packages == ["shared-pkg", "arch-pkg"]


def _user() -> ResolvedUser:
    return ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )


def test_mounts_for_returns_a_mount_for_each_existing_state_path(
    tmp_path: Path,
) -> None:
    # given the pycharm ide, a host home directory where every one of its
    # state paths exists, and a resolved user
    pycharm = Pycharm()
    user = _user()
    for state_path in pycharm.config_paths:
        path = tmp_path / state_path
        path.mkdir(parents=True, exist_ok=True)

    # when resolving its mounts for that user
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(Path, "home", lambda: tmp_path)
        mounts = pycharm.mounts_for(user)

    # then every state path is mounted from the host home directory to the
    # matching path under the user's container home
    assert mounts == [
        Mount(
            host_path=tmp_path / state_path,
            container_path=Path("/home/raniz") / state_path,
        )
        for state_path in pycharm.config_paths
    ]


def test_mounts_for_omits_a_state_path_that_does_not_exist_on_the_host(
    tmp_path: Path,
) -> None:
    # given the pycharm ide, a host home directory where every state path
    # exists except the cache directory
    pycharm = Pycharm()
    user = _user()
    for state_path in pycharm.config_paths:
        if state_path == ".cache/JetBrains":
            continue
        path = tmp_path / state_path
        path.mkdir(parents=True, exist_ok=True)

    # when resolving its mounts for that user
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(Path, "home", lambda: tmp_path)
        mounts = pycharm.mounts_for(user)

    # then the missing cache directory is omitted
    assert [mount.host_path.name for mount in mounts] == [
        ".config",
        ".local",
    ] or [mount.host_path for mount in mounts] == [
        tmp_path / ".config/JetBrains",
        tmp_path / ".local/share/JetBrains",
    ]


def _load_problems(tmp_path: Path, toml: str) -> list[str]:
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()
    (flavors_dir / "arch.toml").write_text('distribution = "arch"\n' + toml)
    with pytest.raises(ConfigError) as error:
        config.load(flavors_dir)
    return error.value.problems


def test_loading_a_config_accepts_known_ides(tmp_path: Path) -> None:
    # given a layer listing pycharm as an ide
    toml = '[layers.base]\nides = ["pycharm"]\n'

    # when loading it
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()
    (flavors_dir / "arch.toml").write_text('distribution = "arch"\n' + toml)
    cfg = config.load(flavors_dir)

    # then the ide is read
    assert cfg.flavors["arch"].layers["base"].ides == ["pycharm"]


def test_loading_a_config_rejects_unknown_ides(tmp_path: Path) -> None:
    # given a layer listing an ide ask doesn't support
    toml = '[layers.base]\nides = ["vscode"]\n'

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the ide is reported by its name along with the supported ones
    assert problems == [
        (
            "layers.base.ides.0: unknown ide 'vscode' (known: clion, datagrip, "
            "goland, idea, phpstorm, pycharm, rider, rubymine, rustrover, webstorm)"
        )
    ]
