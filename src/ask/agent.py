from dataclasses import dataclass, field
from pathlib import Path

from ask.config import ResolvedUser
from ask.incus import Mount
from ask.module import resolve_packages


@dataclass(frozen=True)
class Agent:
    name: str
    packages: dict[str, list[str]] = field(default_factory=dict)
    state_paths: list[str] = field(default_factory=list)

    def packages_for(self, distribution: str) -> list[str]:
        return resolve_packages(self.packages, distribution)

    def mounts_for(self, user: ResolvedUser) -> list[Mount]:
        return [
            Mount(
                host_path=Path.home() / state_path,
                container_path=Path(f"/home/{user.name}") / state_path,
            )
            for state_path in self.state_paths
        ]


@dataclass(frozen=True)
class Claude(Agent):
    name: str = "claude"
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {"arch": ["aur:claude-code"]}
    )
    state_paths: list[str] = field(
        default_factory=lambda: [
            ".claude.json",
            ".claude/.credentials.json",
            ".claude/settings.json",
            ".claude/skills",
            ".claude/CLAUDE.md",
        ]
    )


@dataclass(frozen=True)
class OpenCode(Agent):
    name: str = "opencode"
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {"arch": ["opencode"]}
    )
    state_paths: list[str] = field(
        default_factory=lambda: [
            ".config/opencode/opencode.jsonc",
            ".config/opencode/cli.json",
            ".local/share/opencode/auth.json",
        ]
    )


@dataclass(frozen=True)
class Codex(Agent):
    name: str = "codex"
    packages: dict[str, list[str]] = field(
        default_factory=lambda: {"arch": ["openai-codex"]}
    )
    state_paths: list[str] = field(
        default_factory=lambda: [
            ".codex/config.toml",
            ".codex/auth.json",
        ]
    )


@dataclass(frozen=True)
class Pi(Agent):
    name: str = "pi"
    packages: dict[str, list[str]] = field(default_factory=lambda: {"arch": ["aur:pi"]})
    state_paths: list[str] = field(
        default_factory=lambda: [
            ".pi/agent/auth.json",
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
