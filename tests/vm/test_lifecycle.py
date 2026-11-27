import json
import re

import pytest
from conftest import HOME, USER, Vm

from ask.cli import INIT_TEMPLATE

pytestmark = pytest.mark.vm

PROJECT = "my-project"
PROJECT_DIR = HOME / PROJECT
FLAVOR = HOME / ".config" / "ask" / "flavors" / "default.toml"
AGENTS = """
[layers.base.agents]
default = "opencode"
opencode = true
"""
MANIFEST = """\
packages = ["aur:pfetch"]

[env]
ASK_E2E = "hello"
"""
VERSION = re.compile(r"\d+\.\d+\.\d+")


def test_setup_configures_incus_and_writes_a_default_flavor(vm: Vm) -> None:
    # given a user without any Ask configuration
    uid = vm.run(["id", "-u"]).stdout.strip()

    # when running ask setup with --assume-yes, accepting every step without
    # a terminal; the host incus is already initialised by the fixture
    result = vm.ask("--assume-yes", "setup", cwd=HOME)

    # then the default flavour is written, Incus uses the user's project by
    assert (
        result.returncode,
        vm.run(["test", "-f", str(FLAVOR)]).returncode,
        json.loads(vm.run(["incus", "remote", "list", "--format", "json"]).stdout)[
            "local"
        ]["Project"],
        vm.run(
            ["grep", "-e", f"^{USER}:100000:1000000$", "/etc/subuid", "/etc/subgid"]
        ).stdout,
    ) == (
        0,
        0,
        f"user-{uid}",
        f"/etc/subuid:{USER}:100000:1000000\n/etc/subgid:{USER}:100000:1000000\n",
    )


def test_init_writes_the_manifest_template(vm: Vm) -> None:
    # given an empty project directory
    vm.run(["mkdir", str(PROJECT_DIR)]).check_returncode()

    # when running ask init in it
    result = vm.ask("init", cwd=PROJECT_DIR)

    # then the manifest template is written
    assert (result.returncode, vm.read_file(PROJECT_DIR / "ask.toml")) == (
        0,
        INIT_TEMPLATE,
    )


def test_create_launches_and_converges_the_container(vm: Vm) -> None:
    # given a flavour with an agent and a manifest with an AUR package and an
    # environment variable
    vm.write_file(FLAVOR, vm.read_file(FLAVOR) + AGENTS)
    vm.write_file(PROJECT_DIR / "ask.toml", MANIFEST)

    # when running ask create with --assume-yes, so converging AUR packages
    # skips the paru-bin PKGBUILD review without a terminal
    result = vm.ask("--assume-yes", "create", cwd=PROJECT_DIR)
    assert result.returncode == 0, result.stdout + result.stderr

    # then the container is running, recorded as converged and has the AUR
    # package installed
    [instance] = vm.instances(PROJECT)
    assert (
        result.returncode,
        instance["status"],
        "user.ask.converged.hash" in instance["config"],
        vm.ask("exec", "pacman", "-Q", "pfetch", cwd=PROJECT_DIR).returncode,
    ) == (0, "Running", True, 0)


def test_enter_opens_a_shell_in_the_container(vm: Vm) -> None:
    # when entering the container and running a command in its shell
    result = vm.ask(
        "enter",
        cwd=PROJECT_DIR,
        input="uname -n | tr a-z A-Z\nexit\n",
        terminal=True,
    )

    # then the command ran inside the container
    assert (result.returncode, PROJECT.upper() in result.stdout) == (0, True)


def test_exec_runs_a_command_in_the_project_directory(vm: Vm) -> None:
    # when running a command in the container
    result = vm.ask("exec", "pwd", cwd=PROJECT_DIR)

    # then it runs in the bind-mounted project directory
    assert (result.returncode, result.stdout) == (0, f"{PROJECT_DIR}\n")


def test_exec_runs_a_command_with_the_configured_environment(vm: Vm) -> None:
    # when printing an environment variable from the manifest
    result = vm.ask("exec", "printenv", "ASK_E2E", cwd=PROJECT_DIR)

    # then its configured value is printed
    assert (result.returncode, result.stdout) == (0, "hello\n")


def test_agent_runs_the_configured_agent(vm: Vm) -> None:
    # when asking the configured default agent for its version
    result = vm.ask("agent", "--version", cwd=PROJECT_DIR)

    # then the agent prints it
    assert result.returncode == 0, result.stdout + result.stderr
    assert VERSION.search(result.stdout)


def test_stop_stops_the_container(vm: Vm) -> None:
    # when stopping the container
    result = vm.ask("stop", cwd=PROJECT_DIR)

    # then it is stopped
    [instance] = vm.instances(PROJECT)
    assert (result.returncode, instance["status"]) == (0, "Stopped")


def test_destroy_deletes_the_container(vm: Vm) -> None:
    # when destroying the container
    result = vm.ask("destroy", cwd=PROJECT_DIR)

    # then it no longer exists
    assert (result.returncode, vm.instances(PROJECT)) == (0, [])
