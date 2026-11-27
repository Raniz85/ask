import json
import os
import shlex
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

VM_NAME = "ask-e2e"
IMAGE = "images:archlinux/current/cloud"
USER = "tester"
HOME = Path("/home") / USER
ASK = HOME / ".local" / "bin" / "ask"
BOOT_TIMEOUT_SECONDS = 300

# ASK_E2E_HOST=1 runs the tests directly on the host instead of in a
# dedicated VM, for ephemeral machines that are already throwaway (CI runners)
ON_HOST = os.environ.get("ASK_E2E_HOST") == "1"

# Provisioning for host mode, run as root: the workflow installs Incus and
# uv itself, so only the test user and the rootless Incus setup remain
HOST_PROVISION = f"""\
useradd --create-home --groups incus {USER} 2>/dev/null || true
echo '{USER} ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/{USER}
systemctl enable --now incus.socket incus-user.socket
incus admin init --minimal
incus network create incusbr0 2>/dev/null || true
incus profile device remove default eth0 2>/dev/null || true
incus profile device add default eth0 nic nictype=bridged parent=incusbr0
sysctl -w net.ipv4.ip_forward=1
# Incus's own NAT rules are missing on CI runners, so add them by hand
subnet=$(ip -4 addr show incusbr0 | awk '/inet /{{print $2; exit}}')
iptables -t nat -C POSTROUTING -s "$subnet" ! -o incusbr0 -j MASQUERADE 2>/dev/null \\
  || iptables -t nat -A POSTROUTING -s "$subnet" ! -o incusbr0 -j MASQUERADE
iptables -C FORWARD -i incusbr0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i incusbr0 -j ACCEPT
iptables -C FORWARD -o incusbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \\
  || iptables -A FORWARD -o incusbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
"""

PROVISION = f"""\
# Slow mirrors must not abort the 380 MiB download; pacman's default
# download timeout kills any mirror slower than ~1 byte/sec for 10s.
pacman -Syu --noconfirm --needed --disable-download-timeout incus uv sudo
# incus 7.6.0 opens two concurrent connections to incus-user on every CLI
# call, whose racing user setups poison the project and break all further
# unprivileged access (lxc/incus#4297, fixed for 7.7). Downgrade until Arch
# ships a fixed release.
pacman -U --noconfirm --disable-download-timeout https://archive.archlinux.org/packages/i/incus/incus-7.5.1-1-x86_64.pkg.tar.zst
grep -q '^root:' /etc/subuid || echo root:1000000:1000000000 >> /etc/subuid
grep -q '^root:' /etc/subgid || echo root:1000000:1000000000 >> /etc/subgid
systemctl enable incus.socket incus-user.socket
useradd --create-home --groups incus {USER}
echo '{USER} ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/{USER}
"""


@dataclass(frozen=True)
class Vm:
    name: str

    def run_as_root(
        self, command: list[str], input: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["incus", "exec", self.name, "--", *command],
            check=False,
            input=input,
            capture_output=True,
            text=True,
        )

    def run(
        self,
        command: list[str],
        cwd: Path = HOME,
        input: str | None = None,
        terminal: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        shell_command = f"cd {shlex.quote(str(cwd))} && {shlex.join(command)}"
        if terminal:
            shell_command = shlex.join(["script", "-qec", shell_command, "/dev/null"])
        return self.run_as_root(
            ["runuser", "--login", USER, "--command", shell_command], input=input
        )

    def ask(
        self,
        *args: str,
        cwd: Path,
        input: str | None = None,
        terminal: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return self.run([str(ASK), *args], cwd=cwd, input=input, terminal=terminal)

    def write_file(self, path: Path, content: str) -> None:
        self.run(["tee", str(path)], input=content).check_returncode()

    def read_file(self, path: Path) -> str:
        return self.run(["cat", str(path)]).stdout

    def instances(self, name: str) -> list[dict]:
        result = self.run(["incus", "list", name, "--format", "json"])
        result.check_returncode()
        return [i for i in json.loads(result.stdout) if i["name"] == name]


@dataclass(frozen=True)
class Host(Vm):
    """The test machine is the host itself (host mode): run as root via sudo."""

    def run_as_root(
        self, command: list[str], input: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sudo", *command],
            check=False,
            input=input,
            capture_output=True,
            text=True,
        )


def _incus(*args: str) -> None:
    subprocess.run(["incus", *args], check=True)


def _wait_until_ready(vm: Vm) -> None:
    deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
    while vm.run_as_root(["true"]).returncode:
        if time.monotonic() > deadline:
            raise TimeoutError(f"VM {vm.name!r} did not boot in time.")
        time.sleep(2)
    vm.run_as_root(["systemctl", "is-system-running", "--wait"])


def _provision(vm: Vm, wheel: Path) -> None:
    result = vm.run_as_root(["bash", "-euxc", PROVISION])
    assert result.returncode == 0, result.stdout + result.stderr
    _incus("restart", vm.name)
    _wait_until_ready(vm)
    vm.run_as_root(["incus", "admin", "init", "--minimal"]).check_returncode()
    _incus("file", "push", str(wheel), f"{vm.name}/tmp/", "--mode", "0644")
    vm.run(["uv", "tool", "install", f"/tmp/{wheel.name}"]).check_returncode()


def _build_wheel(out_dir: Path) -> Path:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        check=True,
        cwd=Path(__file__).parents[2],
    )
    return next(out_dir.glob("*.whl"))


@pytest.fixture(scope="session")
def vm(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Vm]:
    wheel = _build_wheel(tmp_path_factory.mktemp("dist"))
    if ON_HOST:
        host = Host("localhost")
        result = host.run_as_root(["bash", "-euxc", HOST_PROVISION])
        assert result.returncode == 0, result.stdout + result.stderr
        # pytest's tmp dir is only readable by the invoking user; stage the
        # wheel where the test user can read it
        host.run_as_root(
            ["install", "-m", "0644", str(wheel), f"/tmp/{wheel.name}"]
        ).check_returncode()
        host.run(["uv", "tool", "install", f"/tmp/{wheel.name}"]).check_returncode()
        yield host
        return
    _incus(
        "launch",
        IMAGE,
        VM_NAME,
        "--vm",
        "--config",
        "limits.cpu=4",
        "--config",
        "limits.memory=4GiB",
        "--config",
        "security.secureboot=false",
        "--device",
        "root,size=30GiB",
    )
    instance = Vm(VM_NAME)
    try:
        _wait_until_ready(instance)
        _provision(instance, wheel)
        yield instance
    finally:
        if not os.environ.get("ASK_E2E_KEEP_VM"):
            _incus("delete", "--force", VM_NAME)
