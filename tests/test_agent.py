import pytest

from ask.agent import Claude, resolve


def test_claude_has_its_packages_and_state_paths() -> None:
    # given the claude agent
    # when inspecting its properties
    claude = Claude()

    # then its distro-keyed packages and home-relative state paths are as
    # expected
    assert claude.name == "claude"
    assert claude.packages == {"arch": ["aur:claude-code"]}
    assert claude.state_paths == [
        ".claude.json",
        ".claude/.credentials.json",
        ".claude/settings.json",
        ".claude/skills",
        ".claude/CLAUDE.md",
    ]


def test_resolve_returns_claude_for_claude() -> None:
    # given the name "claude"
    # when resolving it to an agent
    # then the Claude agent is returned
    assert resolve("claude") == Claude()


def test_resolve_raises_for_unknown_agent() -> None:
    # given a name with no known agent
    # when resolving it to an agent
    # then a clear error is raised
    with pytest.raises(ValueError, match="copilot"):
        resolve("copilot")
