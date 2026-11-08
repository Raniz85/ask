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
    incus.create_container(project_dir.name, m.distribution)
    converge()


def converge() -> None:
    project_dir = Path.cwd()
    m = manifest.load(project_dir / "ask.toml")
    cfg = config.load(config.default_path())
    resolved_manifest = manifest.ResolvedManifest(m, cfg.layers)
    if not incus.is_running(project_dir.name):
        incus.start_container(project_dir.name)
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

    provision.provision_user(project_dir.name, user)
    incus.converge(project_dir.name, mounts)

    provision.provision_packages(project_dir.name, m.distribution, official_packages)
    provision.provision_aur_packages(project_dir.name, m.distribution, aur_packages)

    resolved_packages = official_packages + aur_packages
    stale = incus.stale_packages(
        incus.get_managed_packages(project_dir.name), resolved_packages
    )
    if stale:
        provision.remove_packages(project_dir.name, m.distribution, stale)
    incus.set_managed_packages(project_dir.name, resolved_packages)

    provision.fix_bind_mount_ownership(
        project_dir.name, [mount.container_path for mount in mounts], user
    )


def enter() -> None:
    project_dir = Path.cwd()
    cfg = config.load(config.default_path())
    user = config.resolve_user(cfg)
    if not incus.is_running(project_dir.name):
        incus.start_container(project_dir.name)
    returncode = incus.exec_command(
        project_dir.name,
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
    if not incus.is_running(project_dir.name):
        incus.start_container(project_dir.name)
    returncode = incus.exec_command(
        project_dir.name, user.uid, user.gid, project_dir, [resolved_agent.name]
    )
    sys.exit(returncode)


def exec(*command: str) -> None:
    project_dir = Path.cwd()
    cfg = config.load(config.default_path())
    user = config.resolve_user(cfg)
    if not incus.is_running(project_dir.name):
        incus.start_container(project_dir.name)
    returncode = incus.exec_command(
        project_dir.name, user.uid, user.gid, project_dir, list(command)
    )
    sys.exit(returncode)
