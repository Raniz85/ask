import pytest

from ask.shell import Bash, Zsh, resolve


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


def test_resolve_raises_for_unknown_shell() -> None:
    # given a name with no known shell
    # when resolving it to a shell
    # then a clear error is raised
    with pytest.raises(ValueError, match="fish"):
        resolve("fish")
