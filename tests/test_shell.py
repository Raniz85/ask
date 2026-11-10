from pathlib import Path

import pytest

from ask import config
from ask.config import ConfigError
from ask.incus import Mount
from ask.shell import (
    Bash,
    Elvish,
    Fish,
    Ksh,
    ShellFile,
    Tcsh,
    Zsh,
    known_names,
    resolve,
)
from ask.user import ResolvedUser


def test_bash_has_its_files_and_package() -> None:
    # given the bash shell
    # when inspecting its properties
    bash = Bash()

    # then its name, files and required package are as expected
    assert bash.name == "bash"
    assert bash.files == [
        ShellFile("bashrc", ".bashrc", enabled_by_default=True),
        ShellFile("bash_profile", ".bash_profile"),
        ShellFile("profile", ".profile"),
    ]
    assert bash.packages == ["bash"]


def test_zsh_has_its_files_and_package() -> None:
    # given the zsh shell
    # when inspecting its properties
    zsh = Zsh()

    # then its name, files and required package are as expected
    assert zsh.name == "zsh"
    assert zsh.files == [
        ShellFile("zshrc", ".zshrc", enabled_by_default=True),
        ShellFile("zprofile", ".zprofile"),
        ShellFile("zshenv", ".zshenv"),
    ]
    assert zsh.packages == ["zsh"]


def test_fish_has_its_files_and_package() -> None:
    # given the fish shell
    # when inspecting its properties
    fish = Fish()

    # then its name, files and required package are as expected
    assert fish.name == "fish"
    assert fish.files == [
        ShellFile("config", ".config/fish/config.fish", enabled_by_default=True),
        ShellFile("functions", ".config/fish/functions"),
        ShellFile("conf_d", ".config/fish/conf.d"),
    ]
    assert fish.packages == ["fish"]


def test_ksh_has_its_files_and_package() -> None:
    # given the ksh shell
    # when inspecting its properties
    ksh = Ksh()

    # then its name, files and required package are as expected
    assert ksh.name == "ksh"
    assert ksh.files == [
        ShellFile("kshrc", ".kshrc", enabled_by_default=True),
        ShellFile("profile", ".profile"),
    ]
    assert ksh.packages == ["ksh"]


def test_elvish_has_its_files_and_package() -> None:
    # given the elvish shell
    # when inspecting its properties
    elvish = Elvish()

    # then its name, files and required package are as expected
    assert elvish.name == "elvish"
    assert elvish.files == [
        ShellFile("rc", ".config/elvish/rc.elv", enabled_by_default=True),
        ShellFile("lib", ".config/elvish/lib"),
    ]
    assert elvish.packages == ["elvish"]


def test_tcsh_has_its_files_and_package() -> None:
    # given the tcsh shell
    # when inspecting its properties
    tcsh = Tcsh()

    # then its name, files and required package are as expected
    assert tcsh.name == "tcsh"
    assert tcsh.files == [
        ShellFile("tcshrc", ".tcshrc", enabled_by_default=True),
        ShellFile("login", ".login"),
    ]
    assert tcsh.packages == ["tcsh"]


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


def test_resolve_returns_ksh_for_ksh() -> None:
    # given the name "ksh"
    # when resolving it to a shell
    # then the Ksh shell is returned
    assert resolve("ksh") == Ksh()


def test_resolve_returns_elvish_for_elvish() -> None:
    # given the name "elvish"
    # when resolving it to a shell
    # then the Elvish shell is returned
    assert resolve("elvish") == Elvish()


def test_resolve_returns_tcsh_for_tcsh() -> None:
    # given the name "tcsh"
    # when resolving it to a shell
    # then the Tcsh shell is returned
    assert resolve("tcsh") == Tcsh()


def test_resolve_raises_for_unknown_shell() -> None:
    # given a name with no known shell
    # when resolving it to a shell
    # then a clear error is raised
    with pytest.raises(ValueError, match="nu"):
        resolve("nu")


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


def _user(shell: str) -> ResolvedUser:
    return ResolvedUser(
        name="raniz",
        uid=1000,
        shell=shell,
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )


def test_mounts_for_includes_files_enabled_by_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # given the zsh shell, a host home directory, and a resolved user
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    zsh = Zsh()
    user = _user("zsh")

    # when resolving its mounts with zprofile and zshenv enabled
    mounts = zsh.mounts_for(user, {"zprofile": True, "zshenv": True})

    # then the default rc file and the enabled files are all mounted read-only
    assert mounts == [
        Mount(
            host_path=tmp_path / ".zshrc",
            container_path=Path("/home/raniz/.zshrc"),
            readonly=True,
        ),
        Mount(
            host_path=tmp_path / ".zprofile",
            container_path=Path("/home/raniz/.zprofile"),
            readonly=True,
        ),
        Mount(
            host_path=tmp_path / ".zshenv",
            container_path=Path("/home/raniz/.zshenv"),
            readonly=True,
        ),
    ]


def test_mounts_for_excludes_files_disabled_by_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # given the zsh shell, a host home directory, and a resolved user
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    zsh = Zsh()
    user = _user("zsh")

    # when resolving its mounts with the default rc file disabled
    mounts = zsh.mounts_for(user, {"zshrc": False, "zprofile": True})

    # then only the explicitly enabled file is mounted
    assert mounts == [
        Mount(
            host_path=tmp_path / ".zprofile",
            container_path=Path("/home/raniz/.zprofile"),
            readonly=True,
        )
    ]


def test_option_keys_are_the_keys_of_the_shells_files() -> None:
    # given the zsh shell
    zsh = Zsh()

    # when listing its option keys
    keys = zsh.option_keys()

    # then they are the keys of its configuration files
    assert keys == {"zshrc", "zprofile", "zshenv"}


def test_known_names_lists_every_supported_shell_sorted() -> None:
    # given the registry of supported shells
    # when listing the known shell names
    names = known_names()

    # then every supported shell is listed, sorted by name
    assert names == ["bash", "elvish", "fish", "ksh", "tcsh", "zsh"]


def _load_problems(tmp_path: Path, toml: str) -> list[str]:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[flavors.arch]\ndistribution = "arch"\n' + toml)
    with pytest.raises(ConfigError) as error:
        config.load(config_path)
    return error.value.problems


def test_loading_a_config_rejects_unknown_shells(tmp_path: Path) -> None:
    # given a flavour using a shell ask doesn't support
    toml = 'shell = "foosh"\n'

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the shell is reported along with the supported ones
    assert problems == [
        "flavors.arch.shell.name: unknown shell 'foosh' (known: bash, elvish, fish, ksh, tcsh, zsh)"
    ]


def test_loading_a_config_rejects_an_option_the_shell_does_not_have(
    tmp_path: Path,
) -> None:
    # given a flavour enabling a bash option for zsh
    toml = '[flavors.arch.shell]\nname = "zsh"\nbashrc = true\n'

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the option is reported along with the ones zsh supports
    assert problems == [
        "flavors.arch.shell: unknown option 'bashrc' for zsh (known: zprofile, zshenv, zshrc)"
    ]


def test_loading_a_config_rejects_every_option_the_shell_does_not_have(
    tmp_path: Path,
) -> None:
    # given a flavour enabling two bash options for zsh
    toml = '[flavors.arch.shell]\nname = "zsh"\nbashrc = true\nbash_profile = false\n'

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then both options are reported in one problem
    assert problems == [
        "flavors.arch.shell: unknown options 'bash_profile', 'bashrc' for zsh "
        "(known: zprofile, zshenv, zshrc)"
    ]


def test_loading_a_config_with_an_unknown_shell_does_not_check_its_options(
    tmp_path: Path,
) -> None:
    # given a flavour using an unknown shell with options
    toml = '[flavors.arch.shell]\nname = "foosh"\nzshrc = true\n'

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then only the shell itself is reported
    assert problems == [
        "flavors.arch.shell.name: unknown shell 'foosh' (known: bash, elvish, fish, ksh, tcsh, zsh)"
    ]
