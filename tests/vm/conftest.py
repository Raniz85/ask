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
# ASK_E2E_VM=0 runs the tests in a plain container instead of a VM, for
# hosts without nested virtualization (e.g. CI runners)
IN_VM = os.environ.get("ASK_E2E_VM", "1") == "1"
IMAGE = "images:archlinux/current/cloud" if IN_VM else "images:archlinux/current"
USER = "tester"
HOME = Path("/home") / USER
ASK = HOME / ".local" / "bin" / "ask"
BOOT_TIMEOUT_SECONDS = 300

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
    instance_args = (
        ["--vm", "--config", "security.secureboot=false"]
        if IN_VM
        # nesting lets the container run its own Incus for the tests
        else ["--config", "security.nesting=true"]
    )
    _incus(
        "launch",
        IMAGE,
        VM_NAME,
        *instance_args,
        "--config",
        "limits.cpu=4",
        "--config",
        "limits.memory=4GiB",
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
