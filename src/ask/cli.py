import sys
from pathlib import Path

from ask import agent as agents, config, incus, manifest, provision, shell

FAKE_SSH_ENV = {
    "SSH_CLIENT": "127.0.0.1 1 22",
    "SSH_CONNECTION": "127.0.0.1 1 127.0.0.1 22",
    "SSH_TTY": "/dev/pts/0",
}


def create() -> None:
    project_dir = Path.cwd()
    m = manifest.load(project_dir / "ask.toml")
    incus.Container.create(project_dir.name, m.distribution)
    converge()


def converge() -> None:
    project_dir = Path.cwd()
    m = manifest.load(project_dir / "ask.toml")
    cfg = config.load(config.default_path())
    resolved_manifest = manifest.ResolvedManifest(m, cfg.layers)
    container = incus.Container(project_dir.name)
    container.ensure_running()
    bind_mounts = [project_dir] + resolved_manifest.bind_mounts
    user = config.resolve_user(cfg)
    user_shell = shell.resolve(user.shell)
    packages = (
        resolved_manifest.packages
        + user_shell.packages
        + resolved_manifest.agent_packages
    )
    official_packages, aur_packages = provision.split_aur_packages(packages)

    shared_state_agents = resolved_manifest.shared_state_agents
    mounts = (
        [incus.Mount(host_path=p, container_path=p) for p in bind_mounts]
        + [
            incus.Mount(
                host_path=Path.home() / user_shell.rc_filename,
                container_path=Path(f"/home/{user.name}") / user_shell.rc_filename,
                readonly=True,
            )
        ]
        + [
            incus.Mount(
                host_path=Path.home() / state_path,
                container_path=Path(f"/home/{user.name}") / state_path,
            )
            for a in shared_state_agents
            for state_path in a.state_paths
        ]
    )

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


def enter() -> None:
    project_dir = Path.cwd()
    cfg = config.load(config.default_path())
    user = config.resolve_user(cfg)
    container = incus.Container(project_dir.name)
    container.ensure_running()
    returncode = container.exec_command(
        user.uid,
        user.gid,
        project_dir,
        [user.shell],
        env=FAKE_SSH_ENV,
    )
    sys.exit(returncode)


def agent(name: str | None = None) -> None:
    project_dir = Path.cwd()
    m = manifest.load(project_dir / "ask.toml")
    cfg = config.load(config.default_path())
    user = config.resolve_user(cfg)
    if name is None:
        agent_names = manifest.ResolvedManifest(m, cfg.layers).agent_names
        if not agent_names:
            raise ValueError("no agents configured")
        name = agent_names[0]
    resolved_agent = agents.resolve(name)
    container = incus.Container(project_dir.name)
    container.ensure_running()
    returncode = container.exec_command(
        user.uid, user.gid, project_dir, [resolved_agent.name]
    )
    sys.exit(returncode)


def exec(*command: str) -> None:
    project_dir = Path.cwd()
    cfg = config.load(config.default_path())
    user = config.resolve_user(cfg)
    container = incus.Container(project_dir.name)
    container.ensure_running()
    returncode = container.exec_command(user.uid, user.gid, project_dir, list(command))
    sys.exit(returncode)
