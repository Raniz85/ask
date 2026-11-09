import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ask.incus import Container, Mount
from ask.user import ResolvedUser


def wayland_mount(user: ResolvedUser) -> Mount | None:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    display = os.environ.get("WAYLAND_DISPLAY")
    if not runtime_dir or not display:
        return None
    host_path = Path(runtime_dir) / display
    if not host_path.exists():
        return None
    return Mount(
        host_path=host_path,
        container_path=Path(f"/home/{user.name}/.wayland-socket"),
    )


def env(user: ResolvedUser) -> dict[str, str]:
    return {"WAYLAND_DISPLAY": f"/home/{user.name}/.wayland-socket"}


def _lock_path(container_name: str) -> Path:
    return Path("/tmp") / f"ask-gui-{container_name}.lock"


def acquire(container: Container, mount: Mount) -> None:
    with _lock_path(container.name).open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            count = container.get_gui_session_count()
            if count == 0:
                container.add_gui_device(mount)
            container.set_gui_session_count(count + 1)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


@contextmanager
def session(
    container: Container, user: ResolvedUser, enabled: bool
) -> Iterator[dict[str, str]]:
    mount = wayland_mount(user) if enabled else None
    if mount is None:
        yield {}
        return
    acquire(container, mount)
    try:
        yield env(user)
    finally:
        release(container, mount)


def release(container: Container, mount: Mount) -> None:
    with _lock_path(container.name).open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            count = max(container.get_gui_session_count() - 1, 0)
            container.set_gui_session_count(count)
            if count == 0:
                container.remove_gui_device(mount)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
