from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ask.config import ResolvedUser
from ask.gui import acquire, env, release, session, wayland_mount
from ask.incus import Container, Mount

_USER = ResolvedUser(
    name="raniz",
    uid=1000,
    shell="bash",
    group_name="raniz",
    gid=1000,
    extra_groups=[],
)


def test_wayland_mount_returns_none_when_wayland_display_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a host with no WAYLAND_DISPLAY set
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")

    # when computing the wayland mount
    mount = wayland_mount(_USER)

    # then there is none
    assert mount is None


def test_wayland_mount_returns_none_when_xdg_runtime_dir_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a host with no XDG_RUNTIME_DIR set
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    # when computing the wayland mount
    mount = wayland_mount(_USER)

    # then there is none
    assert mount is None


def test_wayland_mount_returns_none_when_the_socket_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # given a host with both env vars set, but no socket file at that path
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    # when computing the wayland mount
    mount = wayland_mount(_USER)

    # then there is none
    assert mount is None


def test_wayland_mount_returns_the_mount_when_the_socket_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # given a host with both env vars set, and a socket file at that path
    socket_path = tmp_path / "wayland-0"
    socket_path.touch()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    # when computing the wayland mount
    mount = wayland_mount(_USER)

    # then the mount targets the resolved user's fixed, in-home socket path
    assert mount == Mount(
        host_path=socket_path,
        container_path=Path("/home/raniz/.wayland-socket"),
    )


def test_env_points_wayland_display_at_the_fixed_container_socket_path() -> None:
    # given the resolved user
    # when computing the gui environment variables
    # then WAYLAND_DISPLAY is the fixed, absolute, in-home socket path, and
    # nothing else is set (no XDG_RUNTIME_DIR, no DISPLAY)
    assert env(_USER) == {"WAYLAND_DISPLAY": "/home/raniz/.wayland-socket"}


_MOUNT = Mount(
    host_path=Path("/run/user/1000/wayland-0"),
    container_path=Path("/home/raniz/.wayland-socket"),
)


def _mock_container(session_count: int) -> MagicMock:
    container = MagicMock(spec=Container)
    container.name = "my-project"
    container.get_gui_session_count.return_value = session_count
    return container


def test_acquire_adds_the_device_and_sets_the_count_when_none_are_active(
    tmp_path: Path,
) -> None:
    # given a container with no active gui sessions
    container = _mock_container(0)

    # when acquiring a gui session
    with patch("ask.gui._lock_path", return_value=tmp_path / "lock"):
        acquire(container, _MOUNT)

    # then the device is added, and the session count becomes one
    container.add_gui_device.assert_called_once_with(_MOUNT)
    container.set_gui_session_count.assert_called_once_with(1)


def test_acquire_leaves_the_device_alone_when_a_session_is_already_active(
    tmp_path: Path,
) -> None:
    # given a container with one already-active gui session
    container = _mock_container(1)

    # when acquiring another gui session
    with patch("ask.gui._lock_path", return_value=tmp_path / "lock"):
        acquire(container, _MOUNT)

    # then the device is not added again, but the session count is
    # incremented
    container.add_gui_device.assert_not_called()
    container.set_gui_session_count.assert_called_once_with(2)


def test_release_removes_the_device_when_it_was_the_last_session(
    tmp_path: Path,
) -> None:
    # given a container with exactly one active gui session
    container = _mock_container(1)

    # when releasing that session
    with patch("ask.gui._lock_path", return_value=tmp_path / "lock"):
        release(container, _MOUNT)

    # then the device is removed, and the session count becomes zero
    container.remove_gui_device.assert_called_once_with(_MOUNT)
    container.set_gui_session_count.assert_called_once_with(0)


def test_release_leaves_the_device_attached_when_other_sessions_remain(
    tmp_path: Path,
) -> None:
    # given a container with two active gui sessions
    container = _mock_container(2)

    # when releasing one of them
    with patch("ask.gui._lock_path", return_value=tmp_path / "lock"):
        release(container, _MOUNT)

    # then the device is left attached, and the session count is decremented
    container.remove_gui_device.assert_not_called()
    container.set_gui_session_count.assert_called_once_with(1)


def test_session_yields_no_env_and_skips_acquire_release_when_disabled() -> None:
    # given gui support is not requested
    container = _mock_container(0)

    # when running a command under the gui session context manager
    with (
        patch("ask.gui.acquire") as acquire_mock,
        patch("ask.gui.release") as release_mock,
        session(container, _USER, enabled=False) as gui_env,
    ):
        pass

    # then no environment variables are added, and no session is
    # acquired/released
    assert gui_env == {}
    acquire_mock.assert_not_called()
    release_mock.assert_not_called()


def test_session_yields_no_env_and_skips_acquire_release_when_no_wayland_session() -> (
    None
):
    # given gui support is requested, but the host has no live wayland session
    container = _mock_container(0)

    # when running a command under the gui session context manager
    with (
        patch("ask.gui.wayland_mount", return_value=None),
        patch("ask.gui.acquire") as acquire_mock,
        patch("ask.gui.release") as release_mock,
        session(container, _USER, enabled=True) as gui_env,
    ):
        pass

    # then no environment variables are added, and no session is
    # acquired/released
    assert gui_env == {}
    acquire_mock.assert_not_called()
    release_mock.assert_not_called()


def test_session_acquires_before_and_releases_after_the_body_when_available() -> None:
    # given gui support is requested, and the host has a live wayland session
    container = _mock_container(0)
    call_order: list[str] = []

    # when running a command under the gui session context manager
    with (
        patch("ask.gui.wayland_mount", return_value=_MOUNT),
        patch("ask.gui.acquire", side_effect=lambda *a: call_order.append("acquire")),
        patch("ask.gui.release", side_effect=lambda *a: call_order.append("release")),
        session(container, _USER, enabled=True) as gui_env,
    ):
        call_order.append("body")

    # then the session is acquired before, and released after, the body runs,
    # and the gui environment variables are yielded for use in it
    assert call_order == ["acquire", "body", "release"]
    assert gui_env == {"WAYLAND_DISPLAY": "/home/raniz/.wayland-socket"}


def test_session_releases_even_when_the_body_raises() -> None:
    # given gui support is requested, and the host has a live wayland session
    container = _mock_container(0)

    # when the command run under the gui session context manager raises
    with (
        patch("ask.gui.wayland_mount", return_value=_MOUNT),
        patch("ask.gui.acquire"),
        patch("ask.gui.release") as release_mock,
        pytest.raises(ValueError, match="boom"),
        session(container, _USER, enabled=True),
    ):
        raise ValueError("boom")

    # then the session is still released
    release_mock.assert_called_once_with(container, _MOUNT)
