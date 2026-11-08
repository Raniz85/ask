from ask.agent import Claude
from ask.module import Module, resolve_packages
from ask.shell import Bash


def test_resolve_packages_combines_common_and_distribution_packages() -> None:
    # given packages declared for common, the target distribution, and another
    # distribution
    packages = {"common": ["python"], "arch": ["zsh"], "debian": ["other"]}

    # when resolving the packages for the target distribution
    result = resolve_packages(packages, "arch")

    # then the common packages and the target distribution's packages are
    # included, and the other distribution's packages are not
    assert result == ["python", "zsh"]


def test_resolve_packages_defaults_to_an_empty_list() -> None:
    # given no packages declared for either common or the target distribution
    packages: dict[str, list[str]] = {}

    # when resolving the packages for the target distribution
    result = resolve_packages(packages, "arch")

    # then no packages are included
    assert result == []


def test_bash_satisfies_the_module_protocol() -> None:
    # given the bash shell
    # when checking it against the module protocol
    # then it satisfies it
    assert isinstance(Bash(), Module)


def test_claude_satisfies_the_module_protocol() -> None:
    # given the claude agent
    # when checking it against the module protocol
    # then it satisfies it
    assert isinstance(Claude(), Module)
