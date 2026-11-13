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
from ask.user import home_env

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

# Named shell commands to run inside the container with `ask run <name>`.
# [scripts]
# test = "uv run pytest"
"""


def init() -> None:
    path = Path.cwd() / "ask.toml"
    if path.exists():
        raise AskError(f"{path} already exists; not overwriting it.")
    path.write_text(INIT_TEMPLATE)


def setup() -> None:
    user = pwd.getpwuid(os.getuid())
    setup_ops.run_setup(setup_ops.config_dir(), user.pw_name, user.pw_uid, _confirm)


def create() -> None:
    project_dir = Path.cwd()
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
    project_dir = Path.cwd()
    resolved = _resolve_project(project_dir)
    distribution = resolved.flavor.distribution
    slug.slugify(project_dir.name)
    container, _ = _running_container(project_dir, create_missing)
    with _keep_invocation_fresh(container):
        _converge_container(container, project_dir, resolved, distribution)


def _converge_container(
    container: incus.Container,
    project_dir: Path,
    resolved: manifest.ResolvedManifest,
    distribution: str,
) -> None:
    bind_mounts = [project_dir] + resolved.bind_mounts
    user = config.resolve_user(resolved.flavor)
    user_shell = shell.resolve(user.shell)

    tool_managers = [
        (tool_manager, config_files)
        for tool_manager in resolved.tool_managers
        if (config_files := tool_manager.config_files(project_dir))
    ]

    package_modules: list[Module] = [
        cast(Module, user_shell),
        *[agent for agent in resolved.agents if isinstance(agent, Module)],
    ]
    packages = resolved.packages
    for mod in package_modules:
        packages += mod.packages_for(distribution)
    for tool_manager, _ in tool_managers:
        packages += tool_manager.packages_for(distribution)
    official_packages, aur_packages = provision.split_aur_packages(packages)

    mounts = [incus.Mount(host_path=p, container_path=p) for p in bind_mounts]
    mounts += user_shell.mounts_for(user, resolved.flavor.shell.options)
    mounts += resolved.agent_mounts(user)

    provisioner = provision.Provisioner(container)
    aur_builder = provision.AurBuilder(container)

    provisioner.provision_user(user)
    container.converge(mounts)

    provisioner.provision_packages(distribution, official_packages)
    aur_builder.install_packages(distribution, aur_packages)

    # Provision systemd services
    services = resolved.services
    if services:
        provisioner.provision_services(services)

    provisioner.provision_instance_env(resolved.instance_env)
    provisioner.provision_idle_shutdown(distribution, user)

    resolved_packages = official_packages + aur_packages
    stale = incus.stale_packages(container.get_managed_packages(), resolved_packages)
    if stale:
        provisioner.remove_packages(distribution, stale)
    container.set_managed_packages(resolved_packages)

    provisioner.fix_bind_mount_ownership(
        [mount.container_path for mount in mounts], user
    )

    mise_provisioner = provision.MiseProvisioner(container)
    path_entries: list[Path] = []
    for tool_manager, config_files in tool_managers:
        mise_provisioner.trust(project_dir, user, config_files)
        mise_provisioner.install(project_dir, user)
        path_entries += tool_manager.path_entries(user)
    container.set_path_prefix(path_entries)

    configuration = convergence.effective_configuration(resolved)
    container.set_converged_state(
        incus.ConvergedState(
            fingerprint=convergence.fingerprint(configuration),
            configuration=configuration,
            at=datetime.now(UTC),
        )
    )


def enter(
    gui: bool = False,
    *,
    create_missing: CreateMissing = False,
    converge_changed: ConvergeChanged = None,
) -> None:
    project_dir = Path.cwd()
    resolved = _resolve_project(project_dir)
    user = config.resolve_user(resolved.flavor)
    container = _converged_container(
        project_dir, resolved, create_missing, converge_changed
    )
    _record_invocation(container)
    with gui_support.session(container, user, enabled=gui) as gui_env:
        returncode = container.exec_command(
            user.uid,
            user.gid,
            project_dir,
            [user.shell],
            env=home_env(user) | FAKE_SSH_ENV | gui_env,
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
    project_dir = Path.cwd()
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
        gui,
        create_missing,
        converge_changed,
    )


def resolve_shortcut(name: str) -> str:
    resolved = _resolve_project(Path.cwd())
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
    project_dir = Path.cwd()
    resolved = _resolve_project(project_dir)
    if name not in resolved.scripts:
        raise AskError(f"Script '{name}' is not defined in ask.toml.")
    command = shlex.split(resolved.scripts[name]) + list(args)
    _exec_in_container(
        project_dir, resolved, command, gui, create_missing, converge_changed
    )


def exec(
    *command: str,
    gui: bool = False,
    create_missing: CreateMissing = False,
    converge_changed: ConvergeChanged = None,
) -> None:
    project_dir = Path.cwd()
    resolved = _resolve_project(project_dir)
    _exec_in_container(
        project_dir, resolved, list(command), gui, create_missing, converge_changed
    )


def destroy() -> None:
    project_dir = Path.cwd()
    container = incus.Container(project_dir.name)
    snapshot = container.snapshot()
    if snapshot is None:
        raise incus.ContainerNotFoundError(f"No container named {project_dir.name!r}.")
    if snapshot.is_running():
        container.stop()
    container.delete()


def stop() -> None:
    project_dir = Path.cwd()
    container = incus.Container(project_dir.name)
    snapshot = container.snapshot()
    if snapshot is None:
        raise incus.ContainerNotFoundError(
            f"No container named {project_dir.name!r}. Run `ask create` first."
        )
    if snapshot.is_running():
        container.stop()


def restart() -> None:
    project_dir = Path.cwd()
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
        create()
        return container, None
    if not snapshot.is_running():
        container.start()
    _record_invocation(container)
    return container, snapshot


def _configuration_changed(
    snapshot: incus.InstanceSnapshot, resolved: manifest.ResolvedManifest
) -> bool:
    if snapshot is None:
        return False
    configuration = convergence.effective_configuration(resolved)
    return snapshot.converged_fingerprint() != convergence.fingerprint(configuration)


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
            if _configuration_changed(snapshot, resolved) and _should_converge(
                converge_changed
            ):
                converge()
    return container


def _exec_in_container(
    project_dir: Path,
    resolved: manifest.ResolvedManifest,
    command: list[str],
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
            user.uid, user.gid, project_dir, command, env=home_env(user) | gui_env
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
