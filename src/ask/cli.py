from pathlib import Path

from ask import config, incus, manifest, provision, shell


def create() -> None:
    project_dir = Path.cwd()
    m = manifest.load(project_dir / "ask.toml")
    incus.create_container(project_dir.name, m.distribution)
    converge()


def converge() -> None:
    project_dir = Path.cwd()
    m = manifest.load(project_dir / "ask.toml")
    cfg = config.load(config.default_path())
    bind_mounts = [project_dir] + manifest.resolve_bind_mounts(m, cfg)
    user = config.resolve_user(cfg)
    user_shell = shell.resolve(user.shell)
    packages = manifest.resolve_packages(m, cfg) + user_shell.packages
    incus.converge(project_dir.name, bind_mounts)
    incus.converge_shell_rc(
        project_dir.name,
        Path.home() / user_shell.rc_filename,
        Path(f"/home/{user.name}") / user_shell.rc_filename,
    )
    provision.provision_user(project_dir.name, user)
    provision.provision_packages(project_dir.name, m.distribution, packages)
    provision.fix_bind_mount_ownership(project_dir.name, bind_mounts, user)
