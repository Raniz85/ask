from dataclasses import dataclass, field


@dataclass(frozen=True)
class Agent:
    name: str
    packages: dict[str, list[str]] = field(default_factory=dict)
    state_paths: list[str] = field(default_factory=list)


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


_AGENTS: dict[str, Agent] = {"claude": Claude()}


def resolve(name: str) -> Agent:
    try:
        return _AGENTS[name]
    except KeyError:
        raise ValueError(f"no known agent named {name!r}") from None
