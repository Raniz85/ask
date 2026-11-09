import sys
from pathlib import Path

from ask import (
    agent as agents,
    config,
    gui as gui_support,
    incus,
    manifest,
    problems,
    provision,
    shell,
    validation,
)
from ask.module import Module

FAKE_SSH_ENV = {
    "SSH_CLIENT": "127.0.0.1 1 22",
    "SSH_CONNECTION": "127.0.0.1 1 127.0.0.1 22",
    "SSH_TTY": "/dev/pts/0",
}


def create() -> None:
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    m = validation.load_manifest(project_dir / "ask.toml", cfg)
    if incus.Container(project_dir.name).exists():
        raise incus.ContainerExistsError(
            f"container {project_dir.name!r} already exists; "
            "run `ask converge` to update it"
        )
    incus.Container.create(project_dir.name, m.distribution)
    converge()


def converge() -> None:
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    m = validation.load_manifest(project_dir / "ask.toml", cfg)
    resolved_manifest = manifest.ResolvedManifest(m, cfg.layers)
    container = incus.Container(project_dir.name)
    container.ensure_running()
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
    mounts += resolved_manifest.shared_state_mounts(user)

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


def enter(gui: bool = False) -> None:
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    validation.load_manifest(project_dir / "ask.toml", cfg)
    user = config.resolve_user(cfg)
    container = incus.Container(project_dir.name)
    container.ensure_running()
    with gui_support.session(container, user, enabled=gui) as gui_env:
        returncode = container.exec_command(
            user.uid,
            user.gid,
            project_dir,
            [user.shell],
            env=FAKE_SSH_ENV | gui_env,
        )
    sys.exit(returncode)


def agent(name: str | None = None, *args: str, gui: bool = False) -> None:
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
    _exec_in_container(project_dir, cfg, [resolved_agent.name, *args], gui)


def exec(*command: str, gui: bool = False) -> None:
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    validation.load_manifest(project_dir / "ask.toml", cfg)
    _exec_in_container(project_dir, cfg, list(command), gui)


def _exec_in_container(
    project_dir: Path, cfg: config.Config, command: list[str], gui: bool
) -> None:
    user = config.resolve_user(cfg)
    container = incus.Container(project_dir.name)
    container.ensure_running()
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
