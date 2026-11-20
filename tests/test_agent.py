from pathlib import Path

import pytest

from ask import config
from ask.agent import (
    Agent,
    AptRepository,
    Claude,
    Codex,
    OhMyPi,
    OpenCode,
    Pi,
    known_names,
    known_with_aliases,
    resolve,
    resolve_name,
)
from ask.config import ConfigError
from ask.incus import Mount
from ask.user import ResolvedUser


def test_claude_has_its_packages_and_state_paths() -> None:
    # given the claude agent
    # when inspecting its properties
    claude = Claude()

    # then its distro-keyed packages, agent instructions file, and categorized state
    # paths are as expected
    assert claude.name == "claude"
    assert claude.packages == {
        "arch": ["aur:claude-code"],
        "debian": ["claude-code"],
    }
    assert claude.apt_repositories == [
        AptRepository(
            key_url="https://downloads.claude.ai/keys/claude-code.asc",
            keyring_path="/etc/apt/keyrings/claude-code.asc",
            repo="deb [signed-by=/etc/apt/keyrings/claude-code.asc] "
            "https://downloads.claude.ai/claude-code/apt/latest latest main",
            filename="claude-code",
        )
    ]
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
    assert opencode.packages == {
        "arch": ["opencode"],
        "debian": ["nodejs", "npm", "npm:opencode-ai"],
    }
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
    assert codex.packages == {
        "arch": ["openai-codex"],
        "debian": ["nodejs", "npm", "npm:@openai/codex"],
    }
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
    assert pi.packages == {"arch": ["aur:pi"], "debian": ["curl", "nodejs", "npm"]}
    # npm is needed by `pi install npm:<ext>`, not by pi itself
    assert "npm" in pi.packages_for("debian")
    assert pi.agent_instructions_key == "system_md"
    assert pi.agent_instructions_path == ".pi/agent/SYSTEM.md"
    assert pi.auth_paths == [".pi/agent/auth.json"]
    assert pi.skills_paths == [".pi/agent/skills"]
    assert pi.config_paths == [
        ".pi/agent/settings.json",
        ".pi/agent/mcp.json",
        ".pi/agent/models.json",
    ]


def test_oh_my_pi_has_its_packages_and_state_paths() -> None:
    # given the oh-my-pi agent
    # when inspecting its properties
    omp = OhMyPi()

    # then its distro-keyed packages, agent instructions file, and categorized state
    # paths are as expected
    assert omp.name == "oh-my-pi"
    assert omp.packages == {"arch": ["aur:oh-my-pi-bin"], "debian": ["curl"]}
    assert omp.agent_instructions_key == "agents_md"
    assert omp.agent_instructions_path == ".omp/agent/AGENTS.md"
    assert omp.auth_paths == [".omp/agent/auth.json"]
    assert omp.skills_paths == [".omp/agent/skills"]
    assert omp.config_paths == [
        ".omp/agent/settings.json",
        ".omp/agent/mcp.json",
        ".omp/agent/models.yml",
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


def test_resolve_returns_oh_my_pi_for_oh_my_pi() -> None:
    # given the name "oh-my-pi"
    # when resolving it to an agent
    # then the OhMyPi agent is returned
    assert resolve("oh-my-pi") == OhMyPi()


def test_oh_my_pi_binary_is_omp() -> None:
    # given the oh-my-pi agent
    # when reading its binary name
    # then it is omp, not the agent name
    assert OhMyPi().binary == "omp"
    assert Pi().binary == "pi"


def test_resolve_raises_for_unknown_agent() -> None:
    # given a name with no known agent
    # when resolving it to an agent
    # then a clear error is raised
    with pytest.raises(ValueError, match="copilot"):
        resolve("copilot")


def test_oh_my_pi_has_omp_as_its_alias() -> None:
    # given the oh-my-pi agent
    # when reading its aliases
    # then omp is an alias, and the other agents have none
    assert OhMyPi().aliases == ("omp",)
    assert all(agent.aliases == () for agent in (Claude(), Codex(), OpenCode(), Pi()))


def test_resolve_name_accepts_aliases() -> None:
    # given a canonical agent name and an alias
    # when resolving either as a command-line name
    # then both resolve to the same agent
    assert resolve_name("oh-my-pi") == OhMyPi()
    assert resolve_name("omp") == OhMyPi()
    assert resolve_name("claude") == Claude()
    assert resolve_name("copilot") is None


def test_resolve_rejects_aliases() -> None:
    # given an alias, which configuration must not use
    # when resolving it through the configuration path
    # then it is not a known agent
    with pytest.raises(ValueError, match="omp"):
        resolve("omp")


def test_known_with_aliases_lists_each_agents_aliases() -> None:
    # given the registry of supported agents
    # when listing the known names for command-line help
    # then each agent's aliases are listed next to its name
    assert known_with_aliases() == [
        "claude",
        "codex",
        "oh-my-pi (aliases: omp)",
        "opencode",
        "pi",
    ]


def test_apt_repositories_for_returns_them_only_on_debian() -> None:
    # given the claude agent, which installs from Anthropic's apt repository
    # on debian, and the codex agent, which has no vendor apt repository
    claude = Claude()
    codex = Codex()

    # when resolving their apt repositories per distribution
    # then claude's repository is returned on debian only, and codex has none
    assert claude.apt_repositories_for("debian") == claude.apt_repositories
    assert claude.apt_repositories_for("arch") == []
    assert codex.apt_repositories_for("debian") == []


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


def test_option_keys_are_the_instructions_key_and_the_state_categories() -> None:
    # given the claude agent
    claude = Claude()

    # when listing its option keys
    keys = claude.option_keys()

    # then they are its agent instructions key and the shared state categories
    assert keys == {"claude_md", "auth", "skills", "config"}


def test_option_keys_omit_the_instructions_key_without_an_instructions_path() -> None:
    # given an agent with no agent instructions file
    agent = Agent(name="bare")

    # when listing its option keys
    keys = agent.option_keys()

    # then only the shared state categories are options
    assert keys == {"auth", "skills", "config"}


def test_known_names_lists_every_supported_agent_sorted() -> None:
    # given the registry of supported agents
    # when listing the known agent names
    names = known_names()

    # then every supported agent is listed, sorted by name
    assert names == ["claude", "codex", "oh-my-pi", "opencode", "pi"]


def _load_problems(tmp_path: Path, toml: str) -> list[str]:
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()
    (flavors_dir / "arch.toml").write_text('distribution = "arch"\n' + toml)
    with pytest.raises(ConfigError) as error:
        config.load(flavors_dir)
    return error.value.problems


def test_loading_a_config_rejects_unknown_agents(tmp_path: Path) -> None:
    # given a layer using a known agent and an agent ask doesn't support
    toml = "[layers.base.agents]\nclaude = true\nhal = true\n"

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the agent is reported by its name along with the supported ones
    assert problems == [
        "layers.base.agents.hal: unknown agent 'hal' (known: claude, codex, oh-my-pi, opencode, pi)"
    ]


def test_loading_a_config_rejects_an_agent_alias(tmp_path: Path) -> None:
    # given a layer using an alias, which only works on the command line
    toml = "[layers.base.agents]\nomp = true\n"

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the alias is rejected, listing only the canonical names
    assert problems == [
        "layers.base.agents.omp: unknown agent 'omp' (known: claude, codex, oh-my-pi, opencode, pi)"
    ]


def test_loading_a_config_rejects_removing_unknown_agents(tmp_path: Path) -> None:
    # given a layer removing an agent ask doesn't support
    toml = "[layers.base.agents]\nhal = false\n"

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the agent is reported by its name along with the supported ones
    assert problems == [
        "layers.base.agents.hal: unknown agent 'hal' (known: claude, codex, oh-my-pi, opencode, pi)"
    ]


def test_loading_a_config_rejects_options_the_agent_does_not_have(
    tmp_path: Path,
) -> None:
    # given a layer enabling an opencode option for claude
    toml = "[layers.base.agents]\nclaude = { agents_md = true }\n"

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the option is reported along with the ones claude supports
    assert problems == [
        (
            "layers.base.agents: unknown option 'agents_md' for claude "
            "(known: auth, claude_md, config, skills)"
        )
    ]


def test_loading_a_config_rejects_an_unknown_default_agent(tmp_path: Path) -> None:
    # given a layer naming an agent ask doesn't support as its default
    toml = '[layers.base.agents]\ndefault = "hal"\n'

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the default is reported along with the supported agents
    assert problems == [
        "layers.base.agents.default: unknown agent 'hal' (known: claude, codex, oh-my-pi, opencode, pi)"
    ]


def test_loading_a_config_reads_pi_extensions(tmp_path: Path) -> None:
    # given a layer declaring extensions for pi
    toml = (
        "[layers.base.agents.pi]\n"
        'extensions = ["@foo/bar", "https://example.com/ext.git"]\n'
    )

    # when loading it
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()
    (flavors_dir / "arch.toml").write_text('distribution = "arch"\n' + toml)
    cfg = config.load(flavors_dir)

    # then the extensions are read, in order
    assert cfg.flavors["arch"].layers["base"].agents.entries["pi"].extensions == [
        "@foo/bar",
        "https://example.com/ext.git",
    ]


def test_loading_a_config_reads_pi_extensions_from_an_inline_table(
    tmp_path: Path,
) -> None:
    # given a layer declaring extensions for pi inline
    toml = '[layers.base.agents]\npi = { extensions = ["@foo/bar"] }\n'

    # when loading it
    flavors_dir = tmp_path / "flavors"
    flavors_dir.mkdir()
    (flavors_dir / "arch.toml").write_text('distribution = "arch"\n' + toml)
    cfg = config.load(flavors_dir)

    # then the extensions are read
    assert cfg.flavors["arch"].layers["base"].agents.entries["pi"].extensions == [
        "@foo/bar"
    ]


def test_loading_a_config_rejects_extensions_for_agents_that_do_not_support_them(
    tmp_path: Path,
) -> None:
    # given a layer declaring extensions for claude
    toml = '[layers.base.agents.claude]\nextensions = ["@foo/bar"]\n'

    # when loading it
    problems = _load_problems(tmp_path, toml)

    # then the problem is reported, naming the agent
    assert problems == [
        (
            "layers.base.agents: extensions are only supported for the pi and "
            "oh-my-pi agents, not 'claude'"
        )
    ]
