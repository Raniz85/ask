import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ask.incus import (
    converge,
    converge_shell_rc,
    create_container,
    device_name_for,
    exec_command,
    get_managed_packages,
    image_for,
    set_managed_packages,
)


def test_image_for_known_distribution_returns_image_alias() -> None:
    # given the "arch" distribution
    # when resolving its Incus image alias
    image = image_for("arch")

    # then the known archlinux image alias is returned
    assert image == "images:archlinux/current"


def test_image_for_unknown_distribution_raises() -> None:
    # given a distribution with no known Incus image alias
    # when resolving its Incus image alias
    # then a clear error is raised
    with pytest.raises(ValueError, match="nonexistent"):
        image_for("nonexistent")


def test_create_container_launches_image_with_given_name() -> None:
    # given a mocked subprocess.run
    with patch("ask.incus.subprocess.run") as run:
        # when creating a container for the "arch" distribution named "my-project"
        create_container("my-project", "arch")

    # then incus is invoked to launch the matching image under that name, with the
    # common container configuration applied
    run.assert_called_once_with(
        [
            "incus",
            "launch",
            "images:archlinux/current",
            "my-project",
            "--config",
            "security.nesting=true",
            "--config",
            "security.privileged=false",
        ],
        check=True,
    )


def test_device_name_for_produces_a_stable_slug_from_the_path() -> None:
    # given a mount path
    # when deriving its device name
    # then the same path always produces the same, filesystem-path-free name
    assert (
        device_name_for(Path("/home/raniz/.cache/uv")) == "bind--home-raniz--cache-uv"
    )


def _list_devices_result(*names: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout="".join(f"{n}\n" for n in names)
    )


def test_converge_adds_devices_for_mounts_not_yet_present() -> None:
    # given a container with no existing bind-mount devices, and two desired mounts
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result()

        # when converging
        converge("my-project", [Path("/project"), Path("/extra")])

    # then a shifted disk device is added for each desired mount
    run.assert_any_call(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "bind--project",
            "disk",
            "source=/project",
            "path=/project",
            "shift=true",
        ],
        check=True,
    )
    run.assert_any_call(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "bind--extra",
            "disk",
            "source=/extra",
            "path=/extra",
            "shift=true",
        ],
        check=True,
    )


def test_converge_does_not_re_add_an_already_present_device() -> None:
    # given a container that already has the device for the desired mount
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("bind--project")

        # when converging on that same mount
        converge("my-project", [Path("/project")])

    # then no "config device add" call is made
    add_calls = [c for c in run.call_args_list if "add" in c.args[0]]
    assert add_calls == []


def test_converge_removes_bind_devices_no_longer_desired() -> None:
    # given a container with a bind-mount device for a mount that is no longer configured
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("bind--stale")

        # when converging with no desired mounts
        converge("my-project", [])

    # then the stale device is removed
    run.assert_any_call(
        ["incus", "config", "device", "remove", "my-project", "bind--stale"], check=True
    )


def test_converge_shell_rc_adds_a_readonly_device_when_none_exists() -> None:
    # given a container with no existing "shellrc" device
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result()

        # when converging the shell rc mount
        converge_shell_rc(
            "my-project", Path("/home/raniz/.bashrc"), Path("/home/raniz/.bashrc")
        )

    # then a read-only disk device is added for the rc file, under a fixed name
    run.assert_any_call(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "shellrc",
            "disk",
            "source=/home/raniz/.bashrc",
            "path=/home/raniz/.bashrc",
            "readonly=true",
        ],
        check=True,
    )


def test_converge_shell_rc_replaces_an_existing_device() -> None:
    # given a container that already has a "shellrc" device, e.g. from a
    # previously configured shell
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("shellrc")

        # when converging the shell rc mount again
        converge_shell_rc(
            "my-project", Path("/home/raniz/.zshrc"), Path("/home/raniz/.zshrc")
        )

    # then the existing device is removed before the new one is added
    run.assert_any_call(
        ["incus", "config", "device", "remove", "my-project", "shellrc"], check=True
    )
    run.assert_any_call(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "shellrc",
            "disk",
            "source=/home/raniz/.zshrc",
            "path=/home/raniz/.zshrc",
            "readonly=true",
        ],
        check=True,
    )


def test_get_managed_packages_returns_empty_list_when_unset() -> None:
    # given a container with no previously tracked packages
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="\n"
        )

        # when reading the previously managed packages
        packages = get_managed_packages("my-project")

    # then there are none
    assert packages == []


def test_get_managed_packages_returns_the_tracked_packages() -> None:
    # given a container with previously tracked packages
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="zsh,python\n"
        )

        # when reading the previously managed packages
        packages = get_managed_packages("my-project")

    # then the tracked packages are returned
    assert packages == ["zsh", "python"]
    run.assert_called_once_with(
        ["incus", "config", "get", "my-project", "user.ask.packages"],
        check=True,
        capture_output=True,
        text=True,
    )


def test_set_managed_packages_stores_the_given_packages() -> None:
    # given a list of packages to track
    with patch("ask.incus.subprocess.run") as run:
        # when storing them as managed
        set_managed_packages("my-project", ["zsh", "python"])

    # then they are stored, comma-separated, under the custom config key
    run.assert_called_once_with(
        ["incus", "config", "set", "my-project", "user.ask.packages", "zsh,python"],
        check=True,
    )


def test_set_managed_packages_stores_an_empty_value_for_no_packages() -> None:
    # given no packages to track
    with patch("ask.incus.subprocess.run") as run:
        # when storing them as managed
        set_managed_packages("my-project", [])

    # then the custom config key is cleared
    run.assert_called_once_with(
        ["incus", "config", "set", "my-project", "user.ask.packages", ""],
        check=True,
    )


def test_exec_command_runs_the_command_as_the_given_user_and_cwd() -> None:
    # given a command to run inside the container, as a specific uid/gid and
    # working directory
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        # when executing it
        exec_command(
            "my-project", 1000, 1000, Path("/home/raniz/src/ask"), ["ls", "-la"]
        )

    # then incus exec is invoked targeting that user, group and working
    # directory, with the command passed through after "--"
    run.assert_called_once_with(
        [
            "incus",
            "exec",
            "my-project",
            "--user",
            "1000",
            "--group",
            "1000",
            "--cwd",
            "/home/raniz/src/ask",
            "--",
            "ls",
            "-la",
        ]
    )


def test_exec_command_does_not_capture_or_check_the_result() -> None:
    # given a command to run inside the container
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        # when executing it
        exec_command("my-project", 1000, 1000, Path("/project"), ["true"])

    # then stdio is left to inherit the caller's (no output capturing), and
    # a non-zero exit is not treated as an error (no check=True)
    _, kwargs = run.call_args
    assert "check" not in kwargs
    assert "capture_output" not in kwargs
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs
    assert "stdin" not in kwargs


def test_exec_command_returns_the_commands_exit_code() -> None:
    # given a command that exits non-zero inside the container
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=7)

        # when executing it
        returncode = exec_command("my-project", 1000, 1000, Path("/project"), ["false"])

    # then the command's exit code is returned, without raising
    assert returncode == 7


def test_converge_leaves_unrelated_devices_alone() -> None:
    # given a container with devices unrelated to bind-mount management (e.g. from the
    # profile, such as "root" or "eth0"), and the dedicated "shellrc" device
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("root", "eth0", "shellrc")

        # when converging with no desired mounts
        converge("my-project", [])

    # then no "config device remove" call is made for them
    remove_calls = [c for c in run.call_args_list if "remove" in c.args[0]]
    assert remove_calls == []
