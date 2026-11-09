import sys
from pathlib import Path

from ask import (
    agent as agents,
    config,
    gui as gui_support,
    incus,
    manifest,
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
            raise ValueError("no agents configured")
        name = agent_names[0]
    resolved_agent = agents.resolve(name)
    exec(resolved_agent.name, *args, gui=gui)


def exec(*command: str, gui: bool = False) -> None:
    project_dir = Path.cwd()
    cfg = validation.load_config(config.default_path())
    user = config.resolve_user(cfg)
    container = incus.Container(project_dir.name)
    container.ensure_running()
    with gui_support.session(container, user, enabled=gui) as gui_env:
        if gui_env:
            returncode = container.exec_command(
                user.uid, user.gid, project_dir, list(command), env=gui_env
            )
        else:
            returncode = container.exec_command(
                user.uid, user.gid, project_dir, list(command)
            )
    sys.exit(returncode)
