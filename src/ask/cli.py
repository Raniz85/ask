import sys
from pathlib import Path

from ask import config, incus, manifest, provision, shell

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
    if not incus.is_running(project_dir.name):
        incus.start_container(project_dir.name)
    bind_mounts = [project_dir] + manifest.resolve_bind_mounts(m, cfg.layers)
    user = config.resolve_user(cfg)
    user_shell = shell.resolve(user.shell)
    packages = manifest.resolve_packages(m, cfg.layers) + user_shell.packages
    official_packages, aur_packages = provision.split_aur_packages(packages)
    incus.converge(project_dir.name, bind_mounts)
    incus.converge_shell_rc(
        project_dir.name,
        Path.home() / user_shell.rc_filename,
        Path(f"/home/{user.name}") / user_shell.rc_filename,
    )
    provision.provision_user(project_dir.name, user)
    provision.provision_packages(project_dir.name, m.distribution, official_packages)
    provision.provision_aur_packages(project_dir.name, m.distribution, aur_packages)

    resolved_packages = official_packages + aur_packages
    stale = incus.stale_packages(
        incus.get_managed_packages(project_dir.name), resolved_packages
    )
    if stale:
        provision.remove_packages(project_dir.name, m.distribution, stale)
    incus.set_managed_packages(project_dir.name, resolved_packages)

    provision.fix_bind_mount_ownership(project_dir.name, bind_mounts, user)


def enter() -> None:
    project_dir = Path.cwd()
    cfg = config.load(config.default_path())
    user = config.resolve_user(cfg)
    if not incus.is_running(project_dir.name):
        incus.start_container(project_dir.name)
    returncode = incus.exec_command(
        project_dir.name, user.uid, user.gid, project_dir, [user.shell], env=FAKE_SSH_ENV
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
