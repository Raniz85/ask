from pathlib import Path

import pytest

from ask.agent import Agent, Claude, Codex, OpenCode, Pi, resolve
from ask.config import ResolvedUser
from ask.incus import Mount


def test_claude_has_its_packages_and_state_paths() -> None:
    # given the claude agent
    # when inspecting its properties
    claude = Claude()

    # then its distro-keyed packages, agent instructions file, and categorized state
    # paths are as expected
    assert claude.name == "claude"
    assert claude.packages == {"arch": ["aur:claude-code"]}
    assert claude.agent_instructions_key == "claude_md"
    assert claude.agent_instructions_path == ".claude/CLAUDE.md"
    assert claude.auth_paths == [".claude/.credentials.json"]
    assert claude.skills_paths == [".claude/skills"]
    assert claude.config_paths == [".claude.json", ".claude/settings.json"]


def test_opencode_has_its_packages_and_state_paths() -> None:
    # given the opencode agent
    # when inspecting its properties
    opencode = OpenCode()

    # then its distro-keyed packages, agent instructions file, and categorized state
    # paths are as expected
    assert opencode.name == "opencode"
    assert opencode.packages == {"arch": ["opencode"]}
    assert opencode.agent_instructions_key == "agents_md"
    assert opencode.agent_instructions_path == ".config/opencode/AGENTS.md"
    assert opencode.auth_paths == [".local/share/opencode/auth.json"]
    assert opencode.skills_paths == [".config/opencode/skills"]
    assert opencode.config_paths == [
        ".config/opencode/opencode.jsonc",
        ".config/opencode/cli.json",
    ]


def test_codex_has_its_packages_and_state_paths() -> None:
    # given the codex agent
    # when inspecting its properties
    codex = Codex()

    # then its distro-keyed packages, agent instructions file, and categorized state
    # paths are as expected
    assert codex.name == "codex"
    assert codex.packages == {"arch": ["openai-codex"]}
    assert codex.agent_instructions_key == "agents_md"
    assert codex.agent_instructions_path == ".codex/AGENTS.md"
    assert codex.auth_paths == [".codex/auth.json"]
    assert codex.skills_paths == [".codex/skills"]
    assert codex.config_paths == [".codex/config.toml"]


def test_pi_has_its_packages_and_state_paths() -> None:
    # given the pi agent
    # when inspecting its properties
    pi = Pi()

    # then its distro-keyed packages, agent instructions file, and categorized state
    # paths are as expected
    assert pi.name == "pi"
    assert pi.packages == {"arch": ["aur:pi"]}
    assert pi.agent_instructions_key == "system_md"
    assert pi.agent_instructions_path == ".pi/agent/SYSTEM.md"
    assert pi.auth_paths == [".pi/agent/auth.json"]
    assert pi.skills_paths == [".pi/agent/skills"]
    assert pi.config_paths == [
        ".pi/agent/settings.json",
        ".pi/agent/mcp.json",
        ".pi/agent/models.json",
    ]


def test_resolve_returns_claude_for_claude() -> None:
    # given the name "claude"
    # when resolving it to an agent
    # then the Claude agent is returned
    assert resolve("claude") == Claude()


def test_resolve_returns_opencode_for_opencode() -> None:
    # given the name "opencode"
    # when resolving it to an agent
    # then the OpenCode agent is returned
    assert resolve("opencode") == OpenCode()


def test_resolve_returns_codex_for_codex() -> None:
    # given the name "codex"
    # when resolving it to an agent
    # then the Codex agent is returned
    assert resolve("codex") == Codex()


def test_resolve_returns_pi_for_pi() -> None:
    # given the name "pi"
    # when resolving it to an agent
    # then the Pi agent is returned
    assert resolve("pi") == Pi()


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


def _user() -> ResolvedUser:
    return ResolvedUser(
        name="raniz",
        uid=1000,
        shell="bash",
        group_name="raniz",
        gid=1000,
        extra_groups=[],
    )


def _touch(tmp_path: Path, *state_paths: str) -> None:
    for state_path in state_paths:
        path = tmp_path / state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


_CLAUDE_STATE_PATHS = [
    ".claude/CLAUDE.md",
    ".claude/.credentials.json",
    ".claude/skills",
    ".claude.json",
    ".claude/settings.json",
]


def test_mounts_for_returns_a_mount_for_agent_instructions_auth_skills_and_config_by_default(
    tmp_path: Path,
) -> None:
    # given the claude agent, a host home directory where every one of its
    # state paths exists, and a resolved user
    claude = Claude()
    user = _user()
    _touch(tmp_path, *_CLAUDE_STATE_PATHS)

    # when resolving its mounts for that user, without passing any options
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(Path, "home", lambda: tmp_path)
        mounts = claude.mounts_for(user)

    # then every category's state paths are mounted, in agent-instructions/auth/skills/
    # config order, from the host home directory to the matching path under
    # the user's container home
    assert mounts == [
        Mount(
            host_path=tmp_path / state_path,
            container_path=Path("/home/raniz") / state_path,
        )
        for state_path in [
            ".claude/CLAUDE.md",
            ".claude/.credentials.json",
            ".claude/skills",
            ".claude.json",
            ".claude/settings.json",
        ]
    ]


def test_mounts_for_omits_a_category_disabled_by_options(tmp_path: Path) -> None:
    # given the claude agent, a host home directory where every one of its
    # state paths exists, and a resolved user
    claude = Claude()
    user = _user()
    _touch(tmp_path, *_CLAUDE_STATE_PATHS)

    # when resolving its mounts for that user with auth and skills disabled
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(Path, "home", lambda: tmp_path)
        mounts = claude.mounts_for(user, {"auth": False, "skills": False})

    # then only the agent instructions file and config paths are mounted
    assert mounts == [
        Mount(
            host_path=tmp_path / state_path,
            container_path=Path("/home/raniz") / state_path,
        )
        for state_path in [".claude/CLAUDE.md", ".claude.json", ".claude/settings.json"]
    ]


def test_mounts_for_omits_agent_instructions_when_disabled_by_its_agent_specific_key(
    tmp_path: Path,
) -> None:
    # given the claude agent, a host home directory where every one of its
    # state paths exists, and a resolved user
    claude = Claude()
    user = _user()
    _touch(tmp_path, *_CLAUDE_STATE_PATHS)

    # when resolving its mounts for that user with the agent-specific
    # "claude_md" key disabled
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(Path, "home", lambda: tmp_path)
        mounts = claude.mounts_for(user, {"claude_md": False})

    # then the agent instructions file is omitted, but every other category is still
    # mounted
    assert mounts == [
        Mount(
            host_path=tmp_path / state_path,
            container_path=Path("/home/raniz") / state_path,
        )
        for state_path in [
            ".claude/.credentials.json",
            ".claude/skills",
            ".claude.json",
            ".claude/settings.json",
        ]
    ]


def test_mounts_for_omits_a_state_path_that_does_not_exist_on_the_host(
    tmp_path: Path,
) -> None:
    # given the claude agent, a host home directory where every state path
    # exists except the skills directory, and a resolved user
    claude = Claude()
    user = _user()
    _touch(
        tmp_path,
        *(path for path in _CLAUDE_STATE_PATHS if path != ".claude/skills"),
    )

    # when resolving its mounts for that user, without passing any options
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(Path, "home", lambda: tmp_path)
        mounts = claude.mounts_for(user)

    # then the missing skills directory is omitted, even though the skills
    # category is enabled by default
    assert mounts == [
        Mount(
            host_path=tmp_path / state_path,
            container_path=Path("/home/raniz") / state_path,
        )
        for state_path in [
            ".claude/CLAUDE.md",
            ".claude/.credentials.json",
            ".claude.json",
            ".claude/settings.json",
        ]
    ]
