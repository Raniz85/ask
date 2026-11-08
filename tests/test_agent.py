from pathlib import Path

import pytest

from ask.agent import Agent, Claude, resolve
from ask.config import ResolvedUser
from ask.incus import Mount


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


def test_packages_for_combines_common_and_distribution_packages() -> None:
    # given an agent with common, per-distribution, and other-distribution
    # packages
    test_agent = Agent(
        name="test",
        packages={"common": ["shared-pkg"], "arch": ["arch-pkg"], "debian": ["other"]},
    )

    # when resolving its packages for the target distribution
    packages = test_agent.packages_for("arch")

    # then the common packages and the target distribution's packages are
    # included, and the other distribution's packages are not
    assert packages == ["shared-pkg", "arch-pkg"]


def test_mounts_for_returns_a_mount_for_each_state_path(tmp_path: Path) -> None:
    # given the claude agent, a host home directory, and a resolved user
    claude = Claude()
    user = ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )

    # when resolving its mounts for that user
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(Path, "home", lambda: tmp_path)
        mounts = claude.mounts_for(user)

    # then each state path is mounted from the host home directory to the
    # matching path under the user's container home
    assert mounts == [
        Mount(
            host_path=tmp_path / state_path,
            container_path=Path("/home/raniz") / state_path,
        )
        for state_path in claude.state_paths
    ]
