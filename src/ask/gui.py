import fcntl
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ask.incus import Container, Mount
from ask.user import ResolvedUser

logger = logging.getLogger(__name__)

_X11_DISPLAY = ":0"
_X11_SOCKET = "/tmp/.X11-unix/X0"
_SATELLITE = "xwayland-satellite"
_SATELLITE_COMMAND = f"{_SATELLITE} {_X11_DISPLAY}"
# setsid -f detaches the bridge from `incus exec` so it outlives this call;
# then wait for its socket so clients started right after can connect
_SATELLITE_START_SCRIPT = (
    f"setsid -f {_SATELLITE_COMMAND} </dev/null >/dev/null 2>&1; "
    f"for _ in $(seq 50); do [ -S {_X11_SOCKET} ] && exit 0; sleep 0.1; done; "
    "exit 1"
)


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


def env(user: ResolvedUser, x11: bool) -> dict[str, str]:
    wayland = {"WAYLAND_DISPLAY": f"/home/{user.name}/.wayland-socket"}
    return wayland | {"DISPLAY": _X11_DISPLAY} if x11 else wayland


def _lock_path(container_name: str) -> Path:
    return Path("/tmp") / f"ask-gui-{container_name}.lock"


def _satellite_installed(container: Container) -> bool:
    command = ["sh", "-c", f"command -v {_SATELLITE}"]
    return container.run_command(command).returncode == 0


def _start_satellite(container: Container, user: ResolvedUser) -> None:
    home = f"/home/{user.name}"
    returncode = container.exec_command(
        user.uid,
        user.gid,
        Path(home),
        ["sh", "-c", _SATELLITE_START_SCRIPT],
        env=env(user, x11=False) | {"HOME": home},
    )
    if returncode != 0:
        logger.warning(
            "%s did not start in container %r; X11 applications will not work",
            _SATELLITE,
            container.name,
        )


def _x11_running(container: Container) -> bool:
    return container.run_command(["test", "-S", _X11_SOCKET]).returncode == 0


def _stop_satellite(container: Container) -> None:
    container.run_command(["pkill", "-x", "-f", _SATELLITE_COMMAND])


def acquire(container: Container, mount: Mount, user: ResolvedUser) -> bool:
    with _lock_path(container.name).open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            count = container.get_gui_session_count()
            if count == 0:
                container.add_gui_device(mount)
                if _satellite_installed(container):
                    _start_satellite(container, user)
            container.set_gui_session_count(count + 1)
            return _x11_running(container)
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
    x11 = acquire(container, mount, user)
    try:
        yield env(user, x11)
    finally:
        release(container, mount)


def release(container: Container, mount: Mount) -> None:
    with _lock_path(container.name).open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            count = max(container.get_gui_session_count() - 1, 0)
            container.set_gui_session_count(count)
            if count == 0:
                _stop_satellite(container)
                container.remove_gui_device(mount)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
