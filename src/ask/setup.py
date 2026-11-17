import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ask.errors import AskError

# Large enough for rootless Podman inside the containers, which allocates
# subordinate ranges per nested container.
SUBID_START = 100000
SUBID_COUNT = 1_000_000
SUBID_RANGE = f"{SUBID_START}-{SUBID_START + SUBID_COUNT - 1}"

EXAMPLE_FLAVOR = """\
# Example Ask flavour: the base container configuration for new projects.
# Add more flavours as <name>.toml in this directory and select between them
# with `default = true` or [when] path patterns.

distribution = "arch"
default = true

[layers.base]
packages = [
  "git",
  "uv",
]

# Environment variables for every shell and command in the container.
# [layers.base.env]
# EDITOR = "nvim"

# Agents keyed by name: true enables an agent, false removes one a lower layer
# enabled, and a table sets its options and environment variables. env applies
# to every agent and default names the agent `ask agent` runs.
# [layers.base.agents]
# default = "claude"
# env = { GIT_AUTHOR_NAME = "Agent" }
# claude = true
# codex = { auth = false, env = { RUST_LOG = "info" } }
"""


class SetupError(AskError):
    pass


@dataclass(frozen=True)
class SetupStep:
    description: str
    command: list[str]
    done: Callable[[], bool]


def project_name(uid: int) -> str:
    return f"user-{uid}"


def config_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "ask"


def example_config_path(base: Path) -> Path:
    return base / "flavors" / "default.toml"


def _command_succeeds(command: list[str]) -> bool:
    try:
        return subprocess.run(command, check=False, capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def _host_distribution(path: Path = Path("/etc/os-release")) -> str:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return ""
    for line in lines:
        if line.startswith("ID="):
            return line.removeprefix("ID=").strip('"')
    return ""


def _command_output(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _has_sufficient_subid_range(path: Path, name: str) -> bool:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        fields = line.split(":")
        if len(fields) >= 3 and fields[0] == name:
            try:
                return int(fields[2]) >= SUBID_COUNT
            except ValueError:
                return False
    return False


def incus_install_steps(distribution: str) -> list[SetupStep]:
    if distribution != "arch":
        return []
    return [
        SetupStep(
            description="Install Incus with pacman.",
            command=["sudo", "pacman", "-S", "--needed", "--noconfirm", "incus"],
            done=lambda: shutil.which("incus") is not None,
        ),
        SetupStep(
            description="Initialise Incus on this machine.",
            command=["sudo", "incus", "admin", "init"],
            done=lambda: _command_succeeds(["incus", "list"]),
        ),
    ]


def incus_steps(username: str, uid: int) -> list[SetupStep]:
    project = project_name(uid)
    return [
        SetupStep(
            description=f"Create the Incus project {project!r} that holds Ask containers.",
            command=["sudo", "incus", "project", "create", project],
            done=lambda: _command_succeeds(["incus", "project", "show", project]),
        ),
        SetupStep(
            description=f"Use the Incus project {project!r} by default.",
            command=["incus", "config", "set", "default.project", project],
            done=lambda: (
                _command_output(["incus", "config", "get", "default.project"])
                == project
            ),
        ),
        SetupStep(
            description=f"Map subordinate UIDs for {username!r} in /etc/subuid, "
            "so the rootless Incus daemon can shift bind-mounted files into containers.",
            command=["sudo", "usermod", "-v", SUBID_RANGE, username],
            done=lambda: _has_sufficient_subid_range(Path("/etc/subuid"), username),
        ),
        SetupStep(
            description=f"Map subordinate GIDs for {username!r} in /etc/subgid, "
            "so the rootless Incus daemon can shift bind-mounted files into containers.",
            command=["sudo", "usermod", "-w", SUBID_RANGE, username],
            done=lambda: _has_sufficient_subid_range(Path("/etc/subgid"), username),
        ),
    ]


def run_step(step: SetupStep, confirm: Callable[[str], bool]) -> bool:
    if step.done():
        print(f"Already done: {step.description}")
        return False
    print(step.description)
    print(f"  $ {shlex.join(step.command)}")
    if not confirm("Run this command? [Y/n] "):
        print("Skipped.")
        return False
    try:
        subprocess.run(step.command, check=True)
    except FileNotFoundError as error:
        raise SetupError(
            f"Command {step.command[0]!r} not found. Is it installed?"
        ) from error
    except subprocess.CalledProcessError as error:
        raise SetupError(
            f"`{shlex.join(step.command)}` failed with exit status {error.returncode}."
        ) from error
    return True


def _ensure_example_config(base: Path, confirm: Callable[[str], bool]) -> bool:
    path = example_config_path(base)
    if path.exists():
        print(f"Already done: example configuration exists at {path}")
        return False
    print(f"Create an example configuration at {path}?")
    print(EXAMPLE_FLAVOR.rstrip())
    if not confirm("Write this file? [Y/n] "):
        print("Skipped.")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE_FLAVOR)
    return True


def run_setup(
    config_dir: Path,
    username: str,
    uid: int,
    confirm: Callable[[str], bool],
) -> None:
    _ensure_example_config(config_dir, confirm)
    distribution = _host_distribution()
    install_steps = incus_install_steps(distribution)
    if distribution and not install_steps:
        print(f"Ask does not know how to install Incus on {distribution!r}; skipping.")
    for step in [*install_steps, *incus_steps(username, uid)]:
        run_step(step, confirm)
