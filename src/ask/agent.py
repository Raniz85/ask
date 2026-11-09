from dataclasses import dataclass, field
from pathlib import Path

from ask.config import ResolvedUser
from ask.incus import Mount
from ask.module import resolve_packages


@dataclass(frozen=True)
class Agent:
    name: str
    packages: dict[str, list[str]] = field(default_factory=dict)
    agent_instructions_key: str = "agents_md"
    agent_instructions_path: str | None = None
    auth_paths: list[str] = field(default_factory=list)
    skills_paths: list[str] = field(default_factory=list)
    config_paths: list[str] = field(default_factory=list)

    def packages_for(self, distribution: str) -> list[str]:
        return resolve_packages(self.packages, distribution)

    def mounts_for(
        self, user: ResolvedUser, options: dict[str, bool] | None = None
    ) -> list[Mount]:
        options = options or {}
        state_paths: list[str] = []
        if self.agent_instructions_path is not None and options.get(
            self.agent_instructions_key, True
        ):
            state_paths.append(self.agent_instructions_path)
        if options.get("auth", True):
            state_paths += self.auth_paths
        if options.get("skills", True):
            state_paths += self.skills_paths
        if options.get("config", True):
            state_paths += self.config_paths
        return [
            Mount(
                host_path=Path.home() / state_path,
                container_path=Path(f"/home/{user.name}") / state_path,
            )
            for state_path in state_paths
            if (Path.home() / state_path).exists()
        ]


@dataclass(frozen=True)
class Claude(Agent):
    name: str = "claude"
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {"arch": ["aur:claude-code"]}
    )
    agent_instructions_key: str = "claude_md"
    agent_instructions_path: str = ".claude/CLAUDE.md"
    auth_paths: list[str] = field(default_factory=lambda: [".claude/.credentials.json"])
    skills_paths: list[str] = field(default_factory=lambda: [".claude/skills"])
    config_paths: list[str] = field(
        default_factory=lambda: [".claude.json", ".claude/settings.json"]
    )


@dataclass(frozen=True)
class OpenCode(Agent):
    name: str = "opencode"
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {"arch": ["opencode"]}
    )
    agent_instructions_key: str = "agents_md"
    agent_instructions_path: str = ".config/opencode/AGENTS.md"
    auth_paths: list[str] = field(
        default_factory=lambda: [".local/share/opencode/auth.json"]
    )
    skills_paths: list[str] = field(default_factory=lambda: [".config/opencode/skills"])
    config_paths: list[str] = field(
        default_factory=lambda: [
            ".config/opencode/opencode.jsonc",
            ".config/opencode/cli.json",
        ]
    )


@dataclass(frozen=True)
class Codex(Agent):
    name: str = "codex"
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {"arch": ["openai-codex"]}
    )
    agent_instructions_key: str = "agents_md"
    agent_instructions_path: str = ".codex/AGENTS.md"
    auth_paths: list[str] = field(default_factory=lambda: [".codex/auth.json"])
    skills_paths: list[str] = field(default_factory=lambda: [".codex/skills"])
    config_paths: list[str] = field(default_factory=lambda: [".codex/config.toml"])


@dataclass(frozen=True)
class Pi(Agent):
    name: str = "pi"
    packages: dict[str, list[str]] = field(default_factory=lambda: {"arch": ["aur:pi"]})
    agent_instructions_key: str = "system_md"
    agent_instructions_path: str = ".pi/agent/SYSTEM.md"
    auth_paths: list[str] = field(default_factory=lambda: [".pi/agent/auth.json"])
    skills_paths: list[str] = field(default_factory=lambda: [".pi/agent/skills"])
    config_paths: list[str] = field(
        default_factory=lambda: [
            ".pi/agent/settings.json",
            ".pi/agent/mcp.json",
            ".pi/agent/models.json",
        ]
    )


_AGENTS: dict[str, Agent] = {
    "claude": Claude(),
    "opencode": OpenCode(),
    "codex": Codex(),
    "pi": Pi(),
}


def resolve(name: str) -> Agent:
    try:
        return _AGENTS[name]
    except KeyError:
        raise ValueError(f"no known agent named {name!r}") from None
