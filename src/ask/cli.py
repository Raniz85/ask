from pathlib import Path

from ask import config, incus, manifest, provision


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
    incus.converge(project_dir.name, bind_mounts)
    provision.provision_user(project_dir.name, user)
    provision.fix_bind_mount_ownership(project_dir.name, bind_mounts, user)
