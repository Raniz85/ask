from pathlib import Path

from ask import config, incus, manifest


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
    incus.converge(project_dir.name, bind_mounts)
