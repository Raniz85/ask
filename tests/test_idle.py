import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingUnixStreamServer

import pytest

from ask import idle
from ask.incus import INVOCATION_AT_CONFIG_KEY
from ask.user import ResolvedUser

_USER = ResolvedUser(
    name="raniz",
    uid=1000,
    shell="bash",
    group_name="raniz",
    gid=1000,
    extra_groups=[],
)

_LONG_IDLE = idle.IDLE_AFTER * 2
_SHORT_IDLE = idle.IDLE_AFTER / 5

requires_script_tools = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("bash", "curl")),
    reason="the shutdown script needs bash and curl",
)


class _FakeInstance:
    """The in-instance surroundings the shutdown script observes and acts on."""

    def __init__(self, directory: Path, socket: Path) -> None:
        self.config: dict[str, str] = {}
        self.config_status: int | None = None
        self._directory = directory
        self._socket = socket
        self._bin = directory / "bin"
        self._bin.mkdir()
        self._sessions = directory / "sessions"
        self._sessions.write_text("")
        self._user_cgroups = directory / "user-cgroups"
        self._user_cgroups.write_text("")
        self._uptime = directory / "uptime"
        self.started(ago=_LONG_IDLE)
        self._systemctl_calls = directory / "systemctl-calls"
        self._systemctl_calls.write_text("")
        self._stub("who", f'cat "{self._sessions}"')
        self._stub(
            "ps",
            f'if echo " $* " | grep -q " -u {_USER.name} "; then\n'
            f'  cat "{self._user_cgroups}"\n'
            'elif [ "$*" = "-o etimes= -p 1" ]; then\n'
            f'  cat "{self._uptime}"\n'
            "fi",
        )
        self._stub("systemctl", f'echo "$@" >> "{self._systemctl_calls}"')

    def _stub(self, name: str, body: str) -> None:
        path = self._bin / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    def record_invocation(self, ago: timedelta) -> None:
        at = datetime.now(UTC) - ago
        self.config[INVOCATION_AT_CONFIG_KEY] = at.isoformat()

    def started(self, ago: timedelta) -> None:
        self._uptime.write_text(f"{int(ago.total_seconds()):>8}\n")

    def log_in(self, name: str) -> None:
        self._sessions.write_text(
            f"{name}    pts/0        2026-11-11 10:00 (192.168.1.2)\n"
        )

    def run_program(self) -> None:
        self._add_user_process("0::/.lxc")

    def run_user_manager(self) -> None:
        manager = f"0::/user.slice/user-{_USER.uid}.slice/user@{_USER.uid}.service"
        self._add_user_process(f"{manager}/init.scope")
        self._add_user_process(f"{manager}/app.slice/dbus-broker.service")

    def _add_user_process(self, cgroup: str) -> None:
        with self._user_cgroups.open("a") as cgroups:
            cgroups.write(f"{cgroup}\n")

    def run_watchdog(self) -> subprocess.CompletedProcess[str]:
        script = self._directory / "ask-idle-shutdown"
        script.write_text(idle.shutdown_script(_USER, socket=self._socket))
        return subprocess.run(
            ["bash", str(script)],
            check=False,
            env={"PATH": f"{self._bin}:/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )

    def powered_off(self) -> bool:
        return "poweroff" in self._systemctl_calls.read_text().splitlines()


def _serve_instance_config(
    socket: Path, instance: _FakeInstance
) -> ThreadingUnixStreamServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            prefix = "/1.0/config/"
            if instance.config_status is not None:
                self.send_error(instance.config_status)
                return
            if not self.path.startswith(prefix):
                self.send_error(404)
                return
            key = self.path[len(prefix) :]
            if key not in instance.config:
                self.send_error(404)
                return
            body = instance.config[key].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def address_string(self) -> str:
            return "incus"

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingUnixStreamServer(str(socket), Handler)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    return server


@pytest.fixture
def instance(tmp_path: Path) -> Iterator[_FakeInstance]:
    # Unix socket paths are limited to ~108 bytes, which pytest's tmp_path can exceed.
    with tempfile.TemporaryDirectory() as socket_directory:
        socket = Path(socket_directory) / "sock"
        fake = _FakeInstance(tmp_path, socket)
        server = _serve_instance_config(socket, fake)
        try:
            yield fake
        finally:
            server.shutdown()
            server.server_close()


@pytest.fixture
def unreachable_instance(tmp_path: Path) -> _FakeInstance:
    return _FakeInstance(tmp_path, tmp_path / "missing-sock")


@requires_script_tools
def test_powers_off_once_idle_since_the_last_invocation(
    instance: _FakeInstance,
) -> None:
    # given an instance whose last Ask invocation is well past the idle threshold,
    # with no login session and no program running as the user
    instance.record_invocation(ago=_LONG_IDLE)

    # when the watchdog runs
    result = instance.run_watchdog()

    # then it powers the instance off
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", True)


@requires_script_tools
def test_stays_up_after_a_recent_invocation(instance: _FakeInstance) -> None:
    # given an instance whose last Ask invocation is within the idle threshold
    instance.record_invocation(ago=_SHORT_IDLE)

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance stays up
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", False)


@requires_script_tools
def test_stays_up_while_the_user_is_logged_in(instance: _FakeInstance) -> None:
    # given an idle instance where the user has a login session
    instance.record_invocation(ago=_LONG_IDLE)
    instance.log_in(_USER.name)

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance stays up
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", False)


@requires_script_tools
def test_powers_off_when_only_another_user_is_logged_in(
    instance: _FakeInstance,
) -> None:
    # given an idle instance where someone other than the user is logged in
    instance.record_invocation(ago=_LONG_IDLE)
    instance.log_in(f"{_USER.name}2")

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance is powered off
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", True)


@requires_script_tools
def test_stays_up_while_a_program_runs_as_the_user(instance: _FakeInstance) -> None:
    # given an idle instance where a program is running as the user
    instance.record_invocation(ago=_LONG_IDLE)
    instance.run_program()

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance stays up
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", False)


@requires_script_tools
def test_powers_off_when_only_the_users_systemd_manager_runs(
    instance: _FakeInstance,
) -> None:
    # given an idle instance where only the user's lingering systemd manager
    # and the services it runs are running as the user
    instance.record_invocation(ago=_LONG_IDLE)
    instance.run_user_manager()

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance is powered off
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", True)


@requires_script_tools
def test_stays_up_while_a_program_runs_alongside_the_users_systemd_manager(
    instance: _FakeInstance,
) -> None:
    # given an idle instance where the user's systemd manager runs, and a
    # program started outside it is running as the user
    instance.record_invocation(ago=_LONG_IDLE)
    instance.run_user_manager()
    instance.run_program()

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance stays up
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", False)


@requires_script_tools
def test_stays_up_when_the_invocation_time_cannot_be_parsed(
    instance: _FakeInstance,
) -> None:
    # given an instance whose recorded invocation time is not a timestamp
    instance.config[INVOCATION_AT_CONFIG_KEY] = "not a timestamp"

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance stays up
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", False)


@requires_script_tools
def test_powers_off_once_idle_since_start_without_any_invocation(
    instance: _FakeInstance,
) -> None:
    # given an instance that started well past the idle threshold ago and has
    # never had an Ask invocation recorded
    instance.started(ago=_LONG_IDLE)

    # when the watchdog runs
    result = instance.run_watchdog()

    # then it powers the instance off
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", True)


@requires_script_tools
def test_stays_up_after_a_recent_start_without_any_invocation(
    instance: _FakeInstance,
) -> None:
    # given an instance that started within the idle threshold and has never
    # had an Ask invocation recorded
    instance.started(ago=_SHORT_IDLE)

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance stays up
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", False)


@requires_script_tools
def test_stays_up_when_the_instance_config_cannot_be_read(
    unreachable_instance: _FakeInstance,
) -> None:
    # given an idle instance whose Incus socket cannot be reached
    # when the watchdog runs
    result = unreachable_instance.run_watchdog()

    # then the instance stays up
    assert (result.returncode, unreachable_instance.powered_off()) == (0, False)


@requires_script_tools
def test_stays_up_when_the_config_endpoint_returns_an_error(
    instance: _FakeInstance,
) -> None:
    # given an idle instance whose config endpoint answers with an error
    # other than "not found"
    instance.record_invocation(ago=_LONG_IDLE)
    instance.config_status = 500

    # when the watchdog runs
    result = instance.run_watchdog()

    # then the instance stays up
    assert (result.returncode, result.stderr, instance.powered_off()) == (0, "", False)


def test_service_unit_runs_the_script_once_per_trigger() -> None:
    # given the idle shutdown watchdog
    # when generating its systemd service unit
    # then the unit runs the installed script as a oneshot
    assert idle.service_unit() == (
        "[Unit]\n"
        "Description=Shut down the Ask instance once it has been idle for a "
        "while\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=/usr/local/bin/ask-idle-shutdown\n"
    )


def test_timer_unit_triggers_the_check_every_minute() -> None:
    # given the idle shutdown watchdog
    # when generating its systemd timer unit
    # then the check runs every minute, from shortly after boot onwards
    assert idle.timer_unit() == (
        "[Unit]\n"
        "Description=Run the Ask idle shutdown check every 60 seconds\n"
        "\n"
        "[Timer]\n"
        "OnBootSec=60s\n"
        "OnUnitActiveSec=60s\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
