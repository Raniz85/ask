import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from ask.incus import (
    Container,
    ConvergedState,
    Fingerprint,
    InstanceSnapshot,
    IncusError,
    Mount,
    _diff_devices,
    device_name_for,
    ensure_storage_volume,
    image_for,
    known_distributions,
    stale_packages,
)


def test_image_for_known_distribution_returns_image_alias() -> None:
    # given the "arch" distribution
    # when resolving its Incus image alias
    image = image_for("arch")

    # then the known archlinux image alias is returned
    assert image == "images:archlinux/current"


def test_known_distributions_lists_every_distribution_with_an_image() -> None:
    # given the distributions ask has Incus images for
    # when listing the known distributions
    distributions = known_distributions()

    # then every distribution with an image is listed, sorted by name
    assert distributions == ["arch"]


def test_image_for_unknown_distribution_raises() -> None:
    # given a distribution with no known Incus image alias
    # when resolving its Incus image alias
    # then a clear error is raised
    with pytest.raises(ValueError, match="nonexistent"):
        image_for("nonexistent")


def test_container_create_launches_image_with_given_name_and_returns_it() -> None:
    # given a mocked subprocess.run
    with patch("ask.incus.subprocess.run") as run:
        # when creating a container for the "arch" distribution named "my-project"
        container = Container.create("my-project", "arch")

    # then incus is invoked to launch the matching image under that name, with
    # the common container configuration applied, and a Container for it is
    # returned
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
    assert container == Container("my-project")


def test_device_name_for_produces_a_stable_slug_from_the_path() -> None:
    # given a mount path
    # when deriving its device name
    # then the same path always produces the same, filesystem-path-free name,
    # prefixed "bind-" by default
    assert (
        device_name_for(Path("/home/raniz/.cache/uv")) == "bind--home-raniz--cache-uv"
    )


def test_device_name_for_uses_the_given_prefix() -> None:
    # given a mount path and a custom device-name prefix
    # when deriving its device name
    # then the slug is prefixed with the given prefix instead of "bind"
    assert (
        device_name_for(Path("/home/raniz/.wayland-socket"), prefix="gui")
        == "gui--home-raniz--wayland-socket"
    )


def _list_devices_result(*names: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout="".join(f"{n}\n" for n in names)
    )


def test_diff_devices_adds_mounts_not_yet_present() -> None:
    # given no existing devices, and two desired mounts
    to_remove, to_add = _diff_devices(
        set(), {"bind--project": Mount(host_path=Path("/project"), container_path=Path("/project")), "bind--extra": Mount(host_path=Path("/extra"), container_path=Path("/extra"))}
    )

    # then both desired devices are reported for addition, and nothing for removal
    assert to_remove == set()
    assert to_add == {
        "bind--project": Mount(host_path=Path("/project"), container_path=Path("/project")),
        "bind--extra": Mount(host_path=Path("/extra"), container_path=Path("/extra")),
    }


def test_diff_devices_does_not_re_add_an_already_present_device() -> None:
    # given a device that already exists, matching the one desired mount
    to_remove, to_add = _diff_devices(
        {"bind--project"}, {"bind--project": Mount(host_path=Path("/project"), container_path=Path("/project"))}
    )

    # then nothing is reported for addition or removal
    assert to_remove == set()
    assert to_add == {}


def test_diff_devices_removes_devices_no_longer_desired() -> None:
    # given an existing device that is no longer desired
    to_remove, to_add = _diff_devices({"bind--stale"}, {})

    # then it is reported for removal, and nothing for addition
    assert to_remove == {"bind--stale"}
    assert to_add == {}


def test_converge_adds_devices_for_mounts_not_yet_present() -> None:
    # given a container with no existing bind-mount devices, and two desired
    # mounts whose host and container paths are the same
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result()

        # when converging
        container.converge(
            [
                Mount(host_path=Path("/project"), container_path=Path("/project")),
                Mount(host_path=Path("/extra"), container_path=Path("/extra")),
            ]
        )

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


def test_converge_adds_a_writable_device_with_differing_host_and_container_paths() -> (
    None
):
    # given a container with no existing devices, and a desired mount whose
    # host and container paths differ (e.g. agent state shared from a
    # differently-named host user)
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result()

        # when converging
        container.converge(
            [
                Mount(
                    host_path=Path("/home/raniz/.claude.json"),
                    container_path=Path("/home/other/.claude.json"),
                )
            ]
        )

    # then a shifted, writable disk device is added, named after the
    # container path
    run.assert_any_call(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "bind--home-other--claude-json",
            "disk",
            "source=/home/raniz/.claude.json",
            "path=/home/other/.claude.json",
            "shift=true",
        ],
        check=True,
    )


def test_converge_adds_a_readonly_device_when_requested() -> None:
    # given a container with no existing devices, and a desired read-only
    # mount (e.g. a shell rc file)
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result()

        # when converging
        container.converge(
            [
                Mount(
                    host_path=Path("/home/raniz/.zshrc"),
                    container_path=Path("/home/other/.zshrc"),
                    readonly=True,
                )
            ]
        )

    # then a shifted, read-only disk device is added
    run.assert_any_call(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "bind--home-other--zshrc",
            "disk",
            "source=/home/raniz/.zshrc",
            "path=/home/other/.zshrc",
            "shift=true",
            "readonly=true",
        ],
        check=True,
    )


def test_converge_does_not_re_add_an_already_present_device() -> None:
    # given a container that already has the device for the desired mount
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("bind--project")

        # when converging on that same mount
        container.converge(
            [Mount(host_path=Path("/project"), container_path=Path("/project"))]
        )

    # then no "config device add" call is made
    add_calls = [c for c in run.call_args_list if "add" in c.args[0]]
    assert add_calls == []


def test_converge_removes_bind_devices_no_longer_desired() -> None:
    # given a container with a bind-mount device for a mount that is no longer configured
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("bind--stale")

        # when converging with no desired mounts
        container.converge([])

    # then the stale device is removed
    run.assert_any_call(
        ["incus", "config", "device", "remove", "my-project", "bind--stale"], check=True
    )


def test_converge_leaves_unrelated_devices_alone() -> None:
    # given a container with devices unrelated to bind-mount management (e.g.
    # from the profile, such as "root" or "eth0")
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("root", "eth0", "shellrc")

        # when converging with no desired mounts
        container.converge([])

    # then no "config device remove" call is made for them
    remove_calls = [c for c in run.call_args_list if "remove" in c.args[0]]
    assert remove_calls == []


def test_get_managed_packages_returns_empty_list_when_unset() -> None:
    # given a container with no previously tracked packages
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="\n"
        )

        # when reading the previously managed packages
        packages = container.get_managed_packages()

    # then there are none
    assert packages == []


def test_get_managed_packages_returns_the_tracked_packages() -> None:
    # given a container with previously tracked packages
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="zsh,python\n"
        )

        # when reading the previously managed packages
        packages = container.get_managed_packages()

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
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when storing them as managed
        container.set_managed_packages(["zsh", "python"])

    # then they are stored, comma-separated, under the custom config key
    run.assert_called_once_with(
        ["incus", "config", "set", "my-project", "user.ask.packages=zsh,python"],
        check=True,
    )


def test_set_managed_packages_stores_an_empty_value_for_no_packages() -> None:
    # given no packages to track
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when storing them as managed
        container.set_managed_packages([])

    # then the custom config key is cleared
    run.assert_called_once_with(
        ["incus", "config", "set", "my-project", "user.ask.packages="],
        check=True,
    )


def test_add_gui_device_adds_a_shifted_disk_device_with_the_gui_prefix() -> None:
    # given a container and a gui mount
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when adding the gui device
        container.add_gui_device(
            Mount(
                host_path=Path("/run/user/1000/wayland-0"),
                container_path=Path("/home/raniz/.wayland-socket"),
            )
        )

    # then a shifted disk device is added, named with the "gui-" prefix
    # rather than "bind-"
    run.assert_called_once_with(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "gui--home-raniz--wayland-socket",
            "disk",
            "source=/run/user/1000/wayland-0",
            "path=/home/raniz/.wayland-socket",
            "shift=true",
        ],
        check=True,
    )


def test_remove_gui_device_removes_the_gui_prefixed_device() -> None:
    # given a container and the gui mount it currently has attached
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when removing the gui device
        container.remove_gui_device(
            Mount(
                host_path=Path("/run/user/1000/wayland-0"),
                container_path=Path("/home/raniz/.wayland-socket"),
            )
        )

    # then the "gui-" prefixed device is removed
    run.assert_called_once_with(
        [
            "incus",
            "config",
            "device",
            "remove",
            "my-project",
            "gui--home-raniz--wayland-socket",
        ],
        check=True,
    )


def test_converge_leaves_a_gui_device_alone() -> None:
    # given a container with a gui-prefixed device attached (from an active
    # --gui session), and no bind mounts desired
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("gui--home-raniz--wayland-socket")

        # when converging
        container.converge([])

    # then the gui device is left alone - converge's bind-mount
    # reconciliation only ever sees "bind-" prefixed devices
    remove_calls = [c for c in run.call_args_list if "remove" in c.args[0]]
    assert remove_calls == []


def _instances_result(*instances: dict) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(list(instances))
    )


def test_snapshot_lists_the_container_in_a_single_call() -> None:
    # given a container
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _instances_result()

        # when taking a snapshot of it
        container.snapshot()

    # then instances matching its name are listed, in the current project and
    # with their configuration, in one call
    run.assert_called_once_with(
        ["incus", "list", "my-project", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )


def test_snapshot_returns_none_for_a_container_that_does_not_exist() -> None:
    # given only a container whose name merely starts with the project's name
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _instances_result(
            {"name": "my-project-2", "status": "Running", "config": {}}
        )

        # when taking a snapshot of the project's container
        snapshot = container.snapshot()

    # then there is none
    assert snapshot is None


def test_snapshot_returns_the_status_and_config_of_the_named_container() -> None:
    # given the project's container among other containers
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _instances_result(
            {"name": "other", "status": "Running", "config": {"a": "b"}},
            {
                "name": "my-project",
                "status": "Stopped",
                "config": {"user.ask.packages": "zsh"},
            },
        )

        # when taking a snapshot of the project's container
        snapshot = container.snapshot()

    # then its own status and config are captured
    assert snapshot == InstanceSnapshot(
        status="Stopped", config={"user.ask.packages": "zsh"}
    )


def test_snapshot_is_running_for_a_running_container() -> None:
    # given a snapshot of a running container
    snapshot = InstanceSnapshot(status="Running", config={})

    # when checking whether it is running
    running = snapshot.is_running()

    # then it is
    assert running is True


def test_snapshot_is_not_running_for_a_stopped_container() -> None:
    # given a snapshot of a stopped container
    snapshot = InstanceSnapshot(status="Stopped", config={})

    # when checking whether it is running
    running = snapshot.is_running()

    # then it is not
    assert running is False


def test_converged_fingerprint_is_none_when_never_converged() -> None:
    # given a snapshot of a container without any recorded convergence
    snapshot = InstanceSnapshot(status="Running", config={})

    # when reading the fingerprint of the last convergence
    fingerprint = snapshot.converged_fingerprint()

    # then there is none
    assert fingerprint is None


def test_converged_fingerprint_is_none_when_partially_recorded() -> None:
    # given a snapshot with only the version of the last convergence recorded
    snapshot = InstanceSnapshot(
        status="Running", config={"user.ask.converged.version": "0.1.0"}
    )

    # when reading the fingerprint of the last convergence
    fingerprint = snapshot.converged_fingerprint()

    # then there is none
    assert fingerprint is None


def test_converged_fingerprint_is_the_recorded_version_and_hash() -> None:
    # given a snapshot with a recorded convergence
    snapshot = InstanceSnapshot(
        status="Running",
        config={
            "user.ask.converged.version": "0.1.0",
            "user.ask.converged.hash": "abc123",
        },
    )

    # when reading the fingerprint of the last convergence
    fingerprint = snapshot.converged_fingerprint()

    # then the recorded version and hash are returned
    assert fingerprint == Fingerprint(version="0.1.0", config_hash="abc123")


def test_set_converged_state_stores_every_part_of_the_state_at_once() -> None:
    # given the state of a convergence
    container = Container("my-project")
    state = ConvergedState(
        fingerprint=Fingerprint(version="0.1.0", config_hash="abc123"),
        configuration='{"distribution":"arch"}',
        at=datetime(2026, 11, 9, 12, 30, tzinfo=UTC),
    )
    with patch("ask.incus.subprocess.run") as run:
        # when storing it
        container.set_converged_state(state)

    # then every part is stored under its own config key in a single call
    run.assert_called_once_with(
        [
            "incus",
            "config",
            "set",
            "my-project",
            "user.ask.converged.version=0.1.0",
            "user.ask.converged.hash=abc123",
            'user.ask.converged.configuration={"distribution":"arch"}',
            "user.ask.converged.at=2026-11-09T12:30:00+00:00",
        ],
        check=True,
    )


def test_get_gui_session_count_returns_zero_when_unset() -> None:
    # given a container with no previously tracked gui session count
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="\n"
        )

        # when reading the gui session count
        count = container.get_gui_session_count()

    # then it is zero
    assert count == 0


def test_get_gui_session_count_returns_the_tracked_count() -> None:
    # given a container with a previously tracked gui session count
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="2\n"
        )

        # when reading the gui session count
        count = container.get_gui_session_count()

    # then the tracked count is returned
    assert count == 2
    run.assert_called_once_with(
        ["incus", "config", "get", "my-project", "user.ask.gui_sessions"],
        check=True,
        capture_output=True,
        text=True,
    )


def test_set_gui_session_count_stores_the_given_count() -> None:
    # given a gui session count to track
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when storing it
        container.set_gui_session_count(1)

    # then it is stored under the custom config key
    run.assert_called_once_with(
        ["incus", "config", "set", "my-project", "user.ask.gui_sessions=1"],
        check=True,
    )


def test_exec_command_runs_the_command_as_the_given_user_and_cwd() -> None:
    # given a command to run inside the container, as a specific uid/gid and
    # working directory
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        # when executing it
        container.exec_command(1000, 1000, Path("/home/raniz/src/ask"), ["ls", "-la"])

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


def test_exec_command_passes_extra_environment_variables() -> None:
    # given a command to run inside the container, with extra environment
    # variables to set for it
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        # when executing it
        container.exec_command(
            1000,
            1000,
            Path("/project"),
            ["ls"],
            env={"SSH_TTY": "/dev/pts/0", "SSH_CLIENT": "127.0.0.1 1 22"},
        )

    # then each variable is passed to incus exec as a "--env" flag, before
    # the "--" separating the command
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
            "/project",
            "--env",
            "SSH_TTY=/dev/pts/0",
            "--env",
            "SSH_CLIENT=127.0.0.1 1 22",
            "--",
            "ls",
        ]
    )


def test_exec_command_does_not_capture_or_check_the_result() -> None:
    # given a command to run inside the container
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        # when executing it
        container.exec_command(1000, 1000, Path("/project"), ["true"])

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
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=7)

        # when executing it
        returncode = container.exec_command(1000, 1000, Path("/project"), ["false"])

    # then the command's exit code is returned, without raising
    assert returncode == 7


def test_start_starts_the_named_container() -> None:
    # given a container to start
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when starting it
        container.start()

    # then incus is invoked to start the named container
    run.assert_called_once_with(["incus", "start", "my-project"], check=True)


def test_restart_restarts_the_named_container() -> None:
    # given a container to restart
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when restarting it
        container.restart()

    # then incus is invoked to restart the named container
    run.assert_called_once_with(["incus", "restart", "my-project"], check=True)


def test_stale_packages_returns_managed_packages_no_longer_desired() -> None:
    # given a set of previously managed packages, some no longer desired
    # when computing which are stale
    stale = stale_packages(["project-pkg", "bash", "old-pkg"], ["project-pkg", "bash"])

    # then the undesired ones are returned
    assert stale == ["old-pkg"]


def test_stale_packages_returns_nothing_when_all_are_still_desired() -> None:
    # given a set of previously managed packages that are all still desired
    # when computing which are stale
    stale = stale_packages(["project-pkg", "bash"], ["project-pkg", "bash"])

    # then nothing is stale
    assert stale == []


def test_stale_packages_returns_everything_when_none_are_still_desired() -> None:
    # given a set of previously managed packages, none of which are desired
    # anymore
    # when computing which are stale
    stale = stale_packages(["old-pkg", "other-old-pkg"], [])

    # then all of them are stale, sorted
    assert stale == ["old-pkg", "other-old-pkg"]


def test_stale_packages_returns_nothing_for_empty_inputs() -> None:
    # given no previously managed packages and nothing desired
    # when computing which are stale
    stale = stale_packages([], [])

    # then nothing is stale
    assert stale == []


def test_run_command_runs_the_given_command_capturing_output() -> None:
    # given a command to run inside the container
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="hello\n", stderr=""
        )

        # when running it
        result = container.run_command(["pacman", "-Qq", "paru"])

    # then incus exec is invoked with the command, capturing output rather
    # than inheriting the caller's stdio
    run.assert_called_once_with(
        ["incus", "exec", "my-project", "--", "pacman", "-Qq", "paru"],
        capture_output=True,
        text=True,
    )
    assert result.stdout == "hello\n"


def test_run_command_does_not_raise_on_a_non_zero_exit() -> None:
    # given a command that exits non-zero inside the container
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )

        # when running it
        result = container.run_command(["pacman", "-Qq", "missing"])

    # then the non-zero exit is returned rather than raised
    assert result.returncode == 1


def test_incus_commands_report_a_missing_incus_binary() -> None:
    # given a system without the incus command
    container = Container("my-project")
    with (
        patch("ask.incus.subprocess.run", side_effect=FileNotFoundError("incus")),
        pytest.raises(IncusError) as error,
    ):
        # when running an incus command
        container.start()

    # then the error says incus could not be found
    assert str(error.value) == (
        "The incus command was not found. Is Incus installed and on PATH?"
    )


def test_failing_incus_commands_report_the_command_and_exit_status() -> None:
    # given an incus command that fails, with its output shown on the terminal
    container = Container("my-project")
    failure = subprocess.CalledProcessError(1, ["incus", "start", "my-project"])
    with (
        patch("ask.incus.subprocess.run", side_effect=failure),
        pytest.raises(IncusError) as error,
    ):
        # when running it
        container.start()

    # then the error names the command and its exit status
    assert str(error.value) == "`incus start my-project` failed with exit status 1."


def test_failing_captured_incus_commands_include_the_captured_error_output() -> None:
    # given an incus command whose output is captured that fails
    container = Container("my-project")
    failure = subprocess.CalledProcessError(
        1,
        ["incus", "config", "get", "my-project", "user.ask.packages"],
        stderr="Error: Instance not found\n",
    )
    with (
        patch("ask.incus.subprocess.run", side_effect=failure),
        pytest.raises(IncusError) as error,
    ):
        # when running it
        container.get_managed_packages()

    # then the error names the command and its exit status, followed by what
    # incus printed on stderr
    assert str(error.value) == (
        "`incus config get my-project user.ask.packages` failed with exit status 1"
        ": Error: Instance not found"
    )


def _list_volumes_result(*names: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout="".join(f"{n}\n" for n in names)
    )


def test_ensure_storage_volume_creates_a_missing_custom_volume() -> None:
    # given a storage pool without the named custom volume
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_volumes_result("other-volume")

        # when ensuring the volume exists
        ensure_storage_volume("default", "ask-paru")

    # then the custom volumes in the pool are listed, and the volume is created
    assert [c.args[0] for c in run.call_args_list] == [
        [
            "incus",
            "storage",
            "volume",
            "list",
            "default",
            "type=custom",
            "--format",
            "csv",
            "--columns",
            "n",
        ],
        ["incus", "storage", "volume", "create", "default", "ask-paru"],
    ]


def test_ensure_storage_volume_does_not_recreate_an_existing_volume() -> None:
    # given a storage pool that already has the named custom volume
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_volumes_result("ask-paru")

        # when ensuring the volume exists
        ensure_storage_volume("default", "ask-paru")

    # then no "storage volume create" call is made
    create_calls = [c for c in run.call_args_list if "create" in c.args[0]]
    assert create_calls == []


def test_attach_volume_attaches_the_volume_under_the_given_device_name() -> None:
    # given a container without the volume's device
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("root", "eth0")

        # when attaching a custom volume at a path
        container.attach_volume(
            "default", "ask-paru", "paru-cache", Path("/home/aur/.cache/paru")
        )

    # then the volume is attached at that path under the given device name
    run.assert_called_with(
        [
            "incus",
            "storage",
            "volume",
            "attach",
            "default",
            "ask-paru",
            "my-project",
            "paru-cache",
            "/home/aur/.cache/paru",
        ],
        check=True,
    )


def test_attach_volume_does_not_reattach_an_already_attached_volume() -> None:
    # given a container that already has the volume's device
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = _list_devices_result("root", "paru-cache")

        # when attaching the custom volume again
        container.attach_volume(
            "default", "ask-paru", "paru-cache", Path("/home/aur/.cache/paru")
        )

    # then no "storage volume attach" call is made
    attach_calls = [c for c in run.call_args_list if "attach" in c.args[0]]
    assert attach_calls == []


def test_get_trusted_config_digest_returns_none_when_unset() -> None:
    # given a container on which no mise config was ever trusted
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="\n"
        )

        # when reading the trusted mise config digest
        digest = container.get_trusted_config_digest("mise")

    # then there is none
    assert digest is None


def test_get_trusted_config_digest_returns_the_recorded_digest() -> None:
    # given a container on which a mise config was trusted
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="abc123\n"
        )

        # when reading the trusted mise config digest
        digest = container.get_trusted_config_digest("mise")

    # then the recorded digest is read from the tool manager's config key
    assert digest == "abc123"
    run.assert_called_once_with(
        ["incus", "config", "get", "my-project", "user.ask.mise.trusted"],
        check=True,
        capture_output=True,
        text=True,
    )


def test_set_trusted_config_digest_stores_the_digest() -> None:
    # given a digest of trusted mise config files
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when recording it
        container.set_trusted_config_digest("mise", "abc123")

    # then it is stored under the tool manager's config key
    run.assert_called_once_with(
        ["incus", "config", "set", "my-project", "user.ask.mise.trusted=abc123"],
        check=True,
    )


def test_set_path_prefix_puts_the_entries_before_the_default_path() -> None:
    # given directories to put on the PATH of commands run in the container
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when setting them as the PATH prefix
        container.set_path_prefix([Path("/home/raniz/.local/share/mise/shims")])

    # then the container's PATH is those directories followed by incus' default
    run.assert_called_once_with(
        [
            "incus",
            "config",
            "set",
            "my-project",
            "environment.PATH=/home/raniz/.local/share/mise/shims:"
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        ],
        check=True,
    )


def test_set_path_prefix_restores_the_default_path_without_entries() -> None:
    # given no directories to put on the PATH
    container = Container("my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when setting them as the PATH prefix
        container.set_path_prefix([])

    # then the container's PATH is incus' default
    run.assert_called_once_with(
        [
            "incus",
            "config",
            "set",
            "my-project",
            "environment.PATH="
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        ],
        check=True,
    )


def test_set_invocation_at_stores_the_timestamp_under_a_user_key() -> None:
    # given a container and a point in time
    container = Container("my-project")
    at = datetime(2026, 11, 9, 12, 30, tzinfo=UTC)
    with patch("ask.incus.subprocess.run") as run:
        # when recording an invocation at that time
        container.set_invocation_at(at)

    # then the timestamp is stored as ISO 8601 under a user.* config key,
    # like the other Ask metadata on the container
    run.assert_called_once_with(
        [
            "incus",
            "config",
            "set",
            "my-project",
            "user.ask.invocation.at=2026-11-09T12:30:00+00:00",
        ],
        check=True,
    )
