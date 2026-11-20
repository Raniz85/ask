import logging
import os
import pwd
import shlex
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast

from cyclopts import Parameter
from rich.console import Console

from ask import (
    agent as agents,
)
from ask import (
    config,
    convergence,
    incus,
    manifest,
    problems,
    provision,
    shell,
    slug,
    validation,
)
from ask import gui as gui_support
from ask import (
    setup as setup_ops,
)
from ask.errors import AskError
from ask.module import Module
from ask.tool_manager import Mise
from ask.user import home_env

logger = logging.getLogger(__name__)

# How often a running Ask command refreshes the recorded invocation, so the
# in-instance idle watch keeps the instance up while Ask is using it. Must
# stay well below the idle threshold in ask.idle.
_INVOCATION_REFRESH_INTERVAL = 60

# Command-specific arguments for CLI
CreateMissing = Annotated[
    bool,
    Parameter(
        name="--create",
        negative="",
        help="Create the project's container if it does not exist, without asking.",
    ),
]
ConvergeChanged = Annotated[
    bool | None,
    Parameter(
        name="--converge",
        help="Converge the project's container if its configuration has "
        "changed since it was last converged, without asking. "
        "--no-converge never converges it.",
    ),
]

FAKE_SSH_ENV = {
    "SSH_CLIENT": "127.0.0.1 1 22",
    "SSH_CONNECTION": "127.0.0.1 1 127.0.0.1 22",
    "SSH_TTY": "/dev/pts/0",
}

CHANGED_PROMPT = (
    "Configuration has changed since the container was last converged. "
    "Converge now? [Y/n] "
)
CHANGED_WARNING = (
    "ask: warning: configuration has changed since the container was last "
    "converged; run `ask converge` to apply it"
)


def _resolve_project(project_dir: Path) -> manifest.ResolvedManifest:
    flavors_dir = config.default_dir()
    cfg = validation.load_config(flavors_dir)
    m = validation.load_manifest(project_dir / "ask.toml")
    return validation.resolve_project(flavors_dir, cfg, m, project_dir)


INIT_TEMPLATE = """\
# Ask project manifest: configures the development container for this project.
# Shared container configuration (flavours) lives in ~/.config/ask/flavors/.

# Packages to install in the container.
# Prefix with "aur:" for AUR packages, or with "-" to remove a package that a
# flavour layer added.
# packages = [
#   "uv",
#   "python",
# ]

# Host directories to mount into the container at the same path.
# "~" expands to your home directory.
# bind_mounts = [
#   "~/.cache/uv",
# ]

# Systemd units to enable, disable or mask in the container.
# [services]
# "sshd.service" = "enabled"
# "man-db.timer" = "disabled"

# Tool managers to enable for this project. Known tool managers: mise.
# tool_managers = [
#   "mise",
# ]

# Environment variables for every shell and command in the container.
# Set a variable to false to remove one that a flavour layer set.
# [env]
# EDITOR = "nvim"

# Named shell commands to run inside the container with `ask run <name>`.
# [scripts]
# test = "uv run pytest"
"""


def _active_tool_managers(
    resolved: manifest.ResolvedManifest,
) -> list[tuple[Mise, list[Path]]]:
    return [
        (manager, config_files)
        for manager in resolved.tool_managers
        if (config_files := manager.config_files(resolved.project_dir))
    ]


def _all_packages(
    resolved: manifest.ResolvedManifest,
    distribution: str,
    tool_managers: list[tuple[Mise, list[Path]]],
) -> tuple[list[str], list[str], list[str]]:
    user_shell = shell.resolve(config.resolve_user(resolved.flavor).shell)
    package_modules: list[Module] = [
        cast(Module, user_shell),
        *[agent for agent in resolved.agents if isinstance(agent, Module)],
    ]
    packages = list(resolved.packages)
    for mod in package_modules:
        packages += mod.packages_for(distribution)
    for manager, _ in tool_managers:
        packages += manager.packages_for(distribution)
    official, aur = provision.split_aur_packages(packages)
    official, npm = provision.split_npm_packages(official)
    return official, aur, npm


def _all_mounts(resolved: manifest.ResolvedManifest) -> list[incus.Mount]:
    user = config.resolve_user(resolved.flavor)
    user_shell = shell.resolve(user.shell)
    bind_mounts = [resolved.project_dir] + resolved.bind_mounts
    mounts = [incus.Mount(host_path=p, container_path=p) for p in bind_mounts]
    mounts += user_shell.mounts_for(user, resolved.flavor.shell.options)
    mounts += resolved.agent_mounts(user)
    return mounts


def _items(items: list[str]) -> str:
    return ", ".join(items) if items else "(none)"


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _print_mounts(console: Console, mounts: list[incus.Mount], indent: str) -> None:
    if not mounts:
        console.print(f"{indent}(none)")
        return
    for mount in mounts:
        readonly = " (readonly)" if mount.readonly else ""
        console.print(f"{indent}{mount.host_path} -> {mount.container_path}{readonly}")


def _print_pairs(console: Console, mapping: dict[str, str], indent: str) -> None:
    if not mapping:
        console.print(f"{indent}(none)")
        return
    for name, value in mapping.items():
        console.print(f"{indent}{name}: {value}")


def _print_env(console: Console, env: dict[str, str], indent: str) -> None:
    if not env:
        console.print(f"{indent}(none)")
        return
    for name, value in env.items():
        console.print(f"{indent}{name}={value}")


def _print_resolved(resolved: manifest.ResolvedManifest) -> None:
    flavor = resolved.flavor
    user = config.resolve_user(flavor)
    tool_managers = _active_tool_managers(resolved)
    official, aur, npm = _all_packages(resolved, flavor.distribution, tool_managers)
    console = Console()

    console.print(f"project: {resolved.project_dir}")
    console.print(f"distribution: {flavor.distribution}")
    console.print("layers:")
    matches = resolved.layer_matches
    if not matches:
        console.print("  (none)")
    for name, matched in matches.items():
        reason = "always" if matched is None else f"matched: {_items(matched)}"
        console.print(f"  {name} ({reason})")
    shell_options = ", ".join(
        f"{key}: {_bool(value)}" for key, value in flavor.shell.options.items()
    )
    console.print(f"shell: {flavor.shell.name} (options: {shell_options or '(none)'})")
    console.print(
        f"user: {user.name} (uid: {user.uid}, gid: {user.gid}, "
        f"group: {user.group_name}, shell: {user.shell}, "
        f"extra groups: {_items(user.extra_groups)})"
    )

    console.print("\npackages:")
    console.print(f"  official: {_items(official)}")
    console.print(f"  aur: {_items(aur)}")
    console.print(f"  npm: {_items(npm)}")

    console.print("\nbind mounts:")
    _print_mounts(console, _all_mounts(resolved), "  ")

    console.print("\nservices:")
    _print_pairs(console, resolved.services, "  ")

    console.print("\nenvironment:")
    _print_env(console, resolved.instance_env, "  ")

    console.print("\nscripts:")
    _print_pairs(console, resolved.scripts, "  ")

    console.print("\nagents:")
    entries = resolved.merged_agents()
    if not entries:
        console.print("  (none)")
    for entry in entries:
        resolved_agent = agents.resolve(entry.name)
        console.print(f"  {entry.name}")
        effective_options = {
            key: entry.options.get(key, True)
            for key in sorted(resolved_agent.option_keys())
        }
        options = ", ".join(
            f"{key}: {_bool(value)}" for key, value in effective_options.items()
        )
        console.print(f"    options: {options or '(none)'}")
        console.print(f"    extensions: {_items(entry.extensions)}")
        console.print(
            f"    packages: {_items(resolved_agent.packages_for(flavor.distribution))}"
        )
        console.print("    environment:")
        _print_env(console, resolved.agent_env(entry.name), "      ")
        console.print("    mounts:")
        candidate_mounts = resolved_agent.candidate_mounts(user, entry.options)
        if not candidate_mounts:
            console.print("      (none)")
        for mount in candidate_mounts:
            readonly = " (readonly)" if mount.readonly else ""
            missing = "" if mount.host_path.exists() else " (missing on host)"
            console.print(
                f"      {mount.host_path} -> {mount.container_path}{readonly}{missing}"
            )

    console.print("\ntool managers:")
    if not resolved.tool_managers:
        console.print("  (none)")
    for manager in resolved.tool_managers:
        console.print(f"  {manager.name}")
        config_files = [str(f) for f in manager.config_files(resolved.project_dir)]
        console.print(f"    config files: {_items(config_files)}")


def dump() -> None:
    project_dir = validation.find_project_dir(Path.cwd())
    resolved = _resolve_project(project_dir)
    _print_resolved(resolved)


def init() -> None:
    path = Path.cwd() / "ask.toml"
    if path.exists():
        raise AskError(f"{path} already exists; not overwriting it.")
    path.write_text(INIT_TEMPLATE)


def setup() -> None:
    user = pwd.getpwuid(os.getuid())
    setup_ops.run_setup(setup_ops.config_dir(), user.pw_name, user.pw_uid, _confirm)


def create() -> None:
    project_dir = validation.find_project_dir(Path.cwd())
    resolved = _resolve_project(project_dir)
    container_name = slug.slugify(project_dir.name)
    if incus.Container(container_name).snapshot() is not None:
        raise incus.ContainerExistsError(
            f"Container {container_name!r} already exists. "
            "Run `ask converge` to update it."
        )
    incus.Container.create(container_name, resolved.flavor.distribution)
    converge()


def converge(
    *,
    create_missing: CreateMissing = False,
) -> None:
    project_dir = validation.find_project_dir(Path.cwd())
    resolved = _resolve_project(project_dir)
    distribution = resolved.flavor.distribution
    slug.slugify(project_dir.name)
    container, _ = _running_container(project_dir, create_missing)
    with _keep_invocation_fresh(container):
        logger.debug("converging container %r", container.name)
        _converge_container(container, project_dir, resolved, distribution)


def _converge_container(
    container: incus.Container,
    project_dir: Path,
    resolved: manifest.ResolvedManifest,
    distribution: str,
) -> None:
    user = config.resolve_user(resolved.flavor)

    tool_managers = _active_tool_managers(resolved)

    official_packages, aur_packages, npm_packages = _all_packages(
        resolved, distribution, tool_managers
    )
    mounts = _all_mounts(resolved)

    provisioner = provision.Provisioner(container)
    aur_builder = provision.AurBuilder(container)

    provisioner.provision_user(user)
    container.converge(mounts)
    provisioner.fix_bind_mount_ownership(
        [mount.container_path for mount in mounts], user
    )

    # vendor apt repositories must be registered before the packages they
    # provide are installed
    for agent in resolved.agents:
        for repository in agent.apt_repositories_for(distribution):
            provisioner.provision_apt_repository(repository)

    provisioner.provision_packages(distribution, official_packages)
    aur_builder.install_packages(distribution, aur_packages)
    if npm_packages:
        provisioner.provision_npm_packages(npm_packages)

    # Debian has no pi or mise packages; install their standalone binaries
    if agents.EXTENSIONS_AGENT in resolved.agent_names and distribution == "debian":
        provisioner.provision_pi()
    if tool_managers and distribution == "debian":
        provisioner.provision_mise()

    # Provision pi extensions once pi is installed
    pi_extensions = resolved.pi_extensions
    if pi_extensions:
        provisioner.provision_pi_extensions(user, pi_extensions)

    # Provision systemd services
    services = resolved.services
    if services:
        provisioner.provision_services(services)

    provisioner.provision_instance_env(resolved.instance_env)
    provisioner.provision_idle_shutdown(distribution, user)

    resolved_packages = official_packages + aur_packages + npm_packages
    stale = incus.stale_packages(container.get_managed_packages(), resolved_packages)
    if stale:
        stale_distro, stale_npm = provision.split_npm_packages(stale)
        provisioner.remove_npm_packages(stale_npm)
        if stale_distro:
            provisioner.remove_packages(distribution, stale_distro)
    container.set_managed_packages(resolved_packages)

    mise_provisioner = provision.MiseProvisioner(container)
    path_entries: list[Path] = []
    for manager, config_files in tool_managers:
        mise_provisioner.trust(project_dir, user, config_files)
        mise_provisioner.install(project_dir, user)
        path_entries += manager.path_entries(user)
    container.set_path_prefix(path_entries)

    configuration = convergence.effective_configuration(resolved)
    fingerprint = convergence.fingerprint(configuration)
    container.set_converged_state(
        incus.ConvergedState(
            fingerprint=fingerprint,
            configuration=configuration,
            at=datetime.now(UTC),
        )
    )
    logger.debug(
        "container %r converged (config hash %s)",
        container.name,
        fingerprint.config_hash,
    )


def enter(
    gui: bool = False,
    *,
    root: bool = False,
    create_missing: CreateMissing = False,
    converge_changed: ConvergeChanged = None,
) -> None:
    cwd = Path.cwd()
    project_dir = validation.find_project_dir(cwd)
    resolved = _resolve_project(project_dir)
    user = config.resolve_user(resolved.flavor)
    container = _converged_container(
        project_dir, resolved, create_missing, converge_changed
    )
    uid, gid = (0, 0) if root else (user.uid, user.gid)
    home = {"HOME": "/root"} if root else home_env(user)
    _record_invocation(container)
    with gui_support.session(container, user, enabled=gui) as gui_env:
        returncode = container.exec_command(
            uid,
            gid,
            cwd,
            [user.shell],
            env=resolved.instance_env | home | FAKE_SSH_ENV | gui_env,
        )
    _record_invocation(container)
    sys.exit(returncode)


def agent(
    name: str | None = None,
    *args: str,
    gui: bool = False,
    create_missing: CreateMissing = False,
    converge_changed: ConvergeChanged = None,
) -> None:
    cwd = Path.cwd()
    project_dir = validation.find_project_dir(cwd)
    resolved = _resolve_project(project_dir)
    if name is not None and name.startswith("-"):
        args = (name, *args)
        name = None
    if name is None:
        name = resolved.default_agent
        if name is None:
            raise agents.AgentError(
                "No agents configured in the flavour layers that apply to this project."
            )
    if name not in agents.known_names():
        raise agents.AgentError(
            f"Unknown agent {name!r} {problems.known(agents.known_names())}."
        )
    resolved_agent = agents.resolve(name)
    _exec_in_container(
        project_dir,
        resolved,
        [resolved_agent.name, *args],
        cwd,
        resolved.agent_env(resolved_agent.name),
        gui,
        create_missing,
        converge_changed,
    )


def resolve_shortcut(name: str) -> str | None:
    resolved = _resolve_project(validation.find_project_dir(Path.cwd()))
    matches = [
        command
        for command, matched in (
            ("agent", name in agents.known_names()),
            ("run", name in resolved.scripts),
        )
        if matched
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return None
    raise AskError(
        f"Ambigous command {name!r}; use `ask agent {name}` or `ask run {name}`."
    )


def run(
    name: str,
    *args: str,
    gui: bool = False,
    create_missing: CreateMissing = False,
    converge_changed: ConvergeChanged = None,
) -> None:
    cwd = Path.cwd()
    project_dir = validation.find_project_dir(cwd)
    resolved = _resolve_project(project_dir)
    if name not in resolved.scripts:
        raise AskError(f"Script '{name}' is not defined in ask.toml.")
    command = shlex.split(resolved.scripts[name]) + list(args)
    _exec_in_container(
        project_dir,
        resolved,
        command,
        cwd,
        resolved.instance_env,
        gui,
        create_missing,
        converge_changed,
    )


def exec(
    *command: str,
    gui: bool = False,
    create_missing: CreateMissing = False,
    converge_changed: ConvergeChanged = None,
) -> None:
    cwd = Path.cwd()
    project_dir = validation.find_project_dir(cwd)
    resolved = _resolve_project(project_dir)
    _exec_in_container(
        project_dir,
        resolved,
        list(command),
        cwd,
        resolved.instance_env,
        gui,
        create_missing,
        converge_changed,
    )


def destroy() -> None:
    project_dir = validation.find_project_dir(Path.cwd())
    container = incus.Container(project_dir.name)
    snapshot = container.snapshot()
    if snapshot is None:
        raise incus.ContainerNotFoundError(f"No container named {project_dir.name!r}.")
    if snapshot.is_running():
        container.stop()
    container.delete()


def stop() -> None:
    project_dir = validation.find_project_dir(Path.cwd())
    container = incus.Container(project_dir.name)
    snapshot = container.snapshot()
    if snapshot is None:
        raise incus.ContainerNotFoundError(
            f"No container named {project_dir.name!r}. Run `ask create` first."
        )
    if snapshot.is_running():
        container.stop()


def restart() -> None:
    project_dir = validation.find_project_dir(Path.cwd())
    container = incus.Container(project_dir.name)
    snapshot = container.snapshot()
    if snapshot is None:
        raise incus.ContainerNotFoundError(
            f"No container named {project_dir.name!r}. Run `ask create` first."
        )
    if snapshot.is_running():
        container.restart()
    else:
        container.start()


def rename(old: str, new: str) -> None:
    cwd = Path.cwd()
    old_dir = cwd / old
    new_dir = cwd / new
    old_exists = old_dir.exists()
    new_exists = new_dir.exists()
    if not old_exists and not new_exists:
        raise AskError(f"Neither {old_dir} nor {new_dir} exists.")
    if old_exists and new_exists:
        raise AskError(f"Cannot rename {old_dir} to {new_dir}: target already exists.")
    if old_exists:
        old_dir.rename(new_dir)
    old_container = incus.Container(slug.slugify(old))
    snapshot = old_container.snapshot()
    if snapshot is None:
        raise incus.ContainerNotFoundError(f"No container named {slug.slugify(old)!r}.")
    if snapshot.is_running():
        old_container.stop()
    old_container.rename(slug.slugify(new))
    incus.Container(slug.slugify(new)).move_bind_mount(old_dir, new_dir)


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("", "y", "yes")


def _running_container(
    project_dir: Path, create_missing: bool
) -> tuple[incus.Container, incus.InstanceSnapshot | None]:
    container_name = slug.slugify(project_dir.name)
    container = incus.Container(container_name)
    snapshot = container.snapshot()
    if snapshot is None:
        if not create_missing and not _confirm(
            f"No container named {container_name!r} exists. Create it now? [Y/n] "
        ):
            raise incus.ContainerNotFoundError(
                f"No container named {container_name!r}. Run `ask create` first."
            )
        logger.debug("container %r does not exist; creating it", container_name)
        create()
        return container, None
    if not snapshot.is_running():
        logger.debug("starting stopped container %r", container_name)
        container.start()
    else:
        logger.debug("container %r is already running", container_name)
    _record_invocation(container)
    return container, snapshot


def _configuration_changed(
    snapshot: incus.InstanceSnapshot, resolved: manifest.ResolvedManifest
) -> bool:
    if snapshot is None:
        return False
    configuration = convergence.effective_configuration(resolved)
    current = convergence.fingerprint(configuration)
    converged = snapshot.converged_fingerprint()
    changed = converged != current
    logger.debug(
        "container converged fingerprint %s, current %s: configuration %s",
        converged,
        current,
        "changed" if changed else "unchanged",
    )
    return changed


def _should_converge(converge_changed: bool | None) -> bool:
    if converge_changed is not None:
        return converge_changed
    if not sys.stdin.isatty():
        print(CHANGED_WARNING, file=sys.stderr)
        return False
    return _confirm(CHANGED_PROMPT)


def _converged_container(
    project_dir: Path,
    resolved: manifest.ResolvedManifest,
    create_missing: bool,
    converge_changed: bool | None,
) -> incus.Container:
    container, snapshot = _running_container(project_dir, create_missing)
    with _keep_invocation_fresh(container):
        freshly_created = snapshot is None
        if not freshly_created:
            assert snapshot is not None
            if _configuration_changed(snapshot, resolved):
                if _should_converge(converge_changed):
                    logger.debug("converging container %r", container.name)
                    converge()
                else:
                    logger.debug("skipping convergence of container %r", container.name)
    return container


def _exec_in_container(
    project_dir: Path,
    resolved: manifest.ResolvedManifest,
    command: list[str],
    cwd: Path,
    variables: dict[str, str],
    gui: bool,
    create_missing: bool,
    converge_changed: bool | None,
) -> None:
    user = config.resolve_user(resolved.flavor)
    container = _converged_container(
        project_dir, resolved, create_missing, converge_changed
    )
    _record_invocation(container)
    with gui_support.session(container, user, enabled=gui) as gui_env:
        returncode = container.exec_command(
            user.uid,
            user.gid,
            cwd,
            command,
            env=variables | home_env(user) | gui_env,
        )
    _record_invocation(container)
    sys.exit(returncode)


def _record_invocation(container: incus.Container) -> None:
    container.set_invocation_at(datetime.now(UTC))


def _refresh_invocations(container: incus.Container, stop: threading.Event) -> None:
    while not stop.wait(_INVOCATION_REFRESH_INTERVAL):
        try:
            _record_invocation(container)
        except AskError:
            return


@contextmanager
def _keep_invocation_fresh(container: incus.Container) -> Iterator[None]:
    stop = threading.Event()
    thread = threading.Thread(
        target=_refresh_invocations, args=(container, stop), daemon=True
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
