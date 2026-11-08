from pathlib import Path

import pytest

from ask.config import ResolvedUser
from ask.incus import Mount
from ask.shell import Bash, Fish, Zsh, resolve


def test_bash_has_its_rc_filename_and_package() -> None:
    # given the bash shell
    # when inspecting its properties
    bash = Bash()

    # then its name, rc filename and required package are as expected
    assert bash.name == "bash"
    assert bash.rc_filename == ".bashrc"
    assert bash.packages == ["bash"]


def test_zsh_has_its_rc_filename_and_package() -> None:
    # given the zsh shell
    # when inspecting its properties
    zsh = Zsh()

    # then its name, rc filename and required package are as expected
    assert zsh.name == "zsh"
    assert zsh.rc_filename == ".zshrc"
    assert zsh.packages == ["zsh"]


def test_fish_has_its_rc_filename_and_package() -> None:
    # given the fish shell
    # when inspecting its properties
    fish = Fish()

    # then its name, rc filename and required package are as expected
    assert fish.name == "fish"
    assert fish.rc_filename == ".config/fish/config.fish"
    assert fish.packages == ["fish"]


def test_resolve_returns_bash_for_bash() -> None:
    # given the name "bash"
    # when resolving it to a shell
    # then the Bash shell is returned
    assert resolve("bash") == Bash()


def test_resolve_returns_zsh_for_zsh() -> None:
    # given the name "zsh"
    # when resolving it to a shell
    # then the Zsh shell is returned
    assert resolve("zsh") == Zsh()


def test_resolve_returns_fish_for_fish() -> None:
    # given the name "fish"
    # when resolving it to a shell
    # then the Fish shell is returned
    assert resolve("fish") == Fish()


def test_resolve_raises_for_unknown_shell() -> None:
    # given a name with no known shell
    # when resolving it to a shell
    # then a clear error is raised
    with pytest.raises(ValueError, match="ksh"):
        resolve("ksh")


def test_packages_for_returns_its_packages_regardless_of_distribution() -> None:
    # given the zsh shell
    zsh = Zsh()

    # when resolving its packages for a distribution
    packages = zsh.packages_for("arch")

    # then its own packages are returned, independent of distribution
    assert packages == ["zsh"]


def test_mounts_for_returns_the_rc_file_mount_readonly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # given the zsh shell, a host home directory, and a resolved user
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    zsh = Zsh()
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="zsh",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when resolving its mounts for that user
    mounts = zsh.mounts_for(user)

    # then the rc file is mounted read-only from the host home directory to
    # the matching path under the user's container home
    assert mounts == [
        Mount(
            host_path=tmp_path / ".zshrc",
            container_path=Path("/home/raniz/.zshrc"),
            readonly=True,
        )
    ]


def test_mounts_for_returns_the_nested_rc_file_mount_readonly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # given the fish shell, a host home directory, and a resolved user
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    fish = Fish()
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="fish",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when resolving its mounts for that user
    mounts = fish.mounts_for(user)

    # then the rc file is mounted read-only from its nested host path to the
    # matching nested path under the user's container home
    assert mounts == [
        Mount(
            host_path=tmp_path / ".config/fish/config.fish",
            container_path=Path("/home/raniz/.config/fish/config.fish"),
            readonly=True,
        )
    ]
