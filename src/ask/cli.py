from pathlib import Path

from ask import config, incus


def create() -> None:
    project_dir = Path.cwd()
    cfg = config.load(project_dir / "ask.toml")
    incus.create_container(
        project_dir.name, cfg.distribution, project_dir, bind_mounts=cfg.bind_mounts
    )
