import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from cyclopts import Parameter

from ask import (
    agent as agents,
    config,
    convergence,
    gui as gui_support,
    incus,
    manifest,
    problems,
    provision,
    shell,
    validation,
)
from ask.module import Module

CreateMissing = Annotated[bool, Parameter(parse=False)]
ConvergeChanged = Annotated[bool | None, Parameter(parse=False)]

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


def create() -> None:
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    m = validation.load_manifest(project_dir / "ask.toml", cfg)
    if incus.Container(project_dir.name).snapshot() is not None:
        raise incus.ContainerExistsError(
            f"container {project_dir.name!r} already exists; "
            "run `ask converge` to update it"
        )
    incus.Container.create(project_dir.name, m.distribution)
    converge()


def converge(*, create_missing: CreateMissing = False) -> None:
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    m = validation.load_manifest(project_dir / "ask.toml", cfg)
    resolved_manifest = manifest.ResolvedManifest(m, cfg.layers)
    container, _ = _running_container(project_dir, create_missing)
    bind_mounts = [project_dir] + resolved_manifest.bind_mounts
    user = config.resolve_user(cfg)
    user_shell = shell.resolve(user.shell)

    package_modules: list[Module] = [user_shell, *resolved_manifest.agents]
    packages = resolved_manifest.packages
    for mod in package_modules:
        packages += mod.packages_for(m.distribution)
    official_packages, aur_packages = provision.split_aur_packages(packages)

    mounts = [incus.Mount(host_path=p, container_path=p) for p in bind_mounts]
    mounts += user_shell.mounts_for(user, cfg.shell.options)
    mounts += resolved_manifest.agent_mounts(user)

    provisioner = provision.Provisioner(container)
    aur_builder = provision.AurBuilder(container)

    provisioner.provision_user(user)
    container.converge(mounts)

    provisioner.provision_packages(m.distribution, official_packages)
    aur_builder.install_packages(m.distribution, aur_packages)

    resolved_packages = official_packages + aur_packages
    stale = incus.stale_packages(container.get_managed_packages(), resolved_packages)
    if stale:
        provisioner.remove_packages(m.distribution, stale)
    container.set_managed_packages(resolved_packages)

    provisioner.fix_bind_mount_ownership(
        [mount.container_path for mount in mounts], user
    )

    configuration = convergence.effective_configuration(m, cfg)
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
    cfg = validation.load_config(config.default_path())
    m = validation.load_manifest(project_dir / "ask.toml", cfg)
    user = config.resolve_user(cfg)
    container = _converged_container(
        project_dir, m, cfg, create_missing, converge_changed
    )
    with gui_support.session(container, user, enabled=gui) as gui_env:
        returncode = container.exec_command(
            user.uid,
            user.gid,
            project_dir,
            [user.shell],
            env=FAKE_SSH_ENV | gui_env,
        )
    sys.exit(returncode)


def agent(
    name: str | None = None,
    *args: str,
    gui: bool = False,
    create_missing: CreateMissing = False,
    converge_changed: ConvergeChanged = None,
) -> None:
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    m = validation.load_manifest(project_dir / "ask.toml", cfg)
    if name is not None and name.startswith("-"):
        args = (name, *args)
        name = None
    if name is None:
        agent_names = manifest.ResolvedManifest(m, cfg.layers).agent_names
        if not agent_names:
            raise agents.AgentError("no agents configured in ask.toml or its layers")
        name = agent_names[0]
    if name not in agents.known_names():
        raise agents.AgentError(
            f"unknown agent {name!r} {problems.known(agents.known_names())}"
        )
    resolved_agent = agents.resolve(name)
    _exec_in_container(
        project_dir,
        m,
        cfg,
        [resolved_agent.name, *args],
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
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    m = validation.load_manifest(project_dir / "ask.toml", cfg)
    _exec_in_container(
        project_dir, m, cfg, list(command), gui, create_missing, converge_changed
    )


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
    container = incus.Container(project_dir.name)
    snapshot = container.snapshot()
    if snapshot is None:
        if not create_missing and not _confirm(
            f"No container named {project_dir.name!r} exists. Create it now? [Y/n] "
        ):
            raise incus.ContainerNotFoundError(
                f"no container named {project_dir.name!r}; run `ask create` first"
            )
        create()
        return container, None
    if not snapshot.is_running():
        container.start()
    return container, snapshot


def _configuration_changed(
    snapshot: incus.InstanceSnapshot, m: manifest.Manifest, cfg: config.Config
) -> bool:
    configuration = convergence.effective_configuration(m, cfg)
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
    m: manifest.Manifest,
    cfg: config.Config,
    create_missing: bool,
    converge_changed: bool | None,
) -> incus.Container:
    container, snapshot = _running_container(project_dir, create_missing)
    freshly_created = snapshot is None
    if (
        not freshly_created
        and _configuration_changed(snapshot, m, cfg)
        and _should_converge(converge_changed)
    ):
        converge()
    return container


def _exec_in_container(
    project_dir: Path,
    m: manifest.Manifest,
    cfg: config.Config,
    command: list[str],
    gui: bool,
    create_missing: bool,
    converge_changed: bool | None,
) -> None:
    user = config.resolve_user(cfg)
    container = _converged_container(
        project_dir, m, cfg, create_missing, converge_changed
    )
    with gui_support.session(container, user, enabled=gui) as gui_env:
        if gui_env:
            returncode = container.exec_command(
                user.uid, user.gid, project_dir, command, env=gui_env
            )
        else:
            returncode = container.exec_command(
                user.uid, user.gid, project_dir, command
            )
    sys.exit(returncode)
