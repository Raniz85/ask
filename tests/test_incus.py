from pathlib import Path
from unittest.mock import patch

import pytest

from ask.incus import create_container, image_for


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
    # given a mocked subprocess.run and a project directory to bind mount
    project_dir = Path("/home/raniz/src/my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when creating a container for the "arch" distribution named "my-project"
        create_container("my-project", "arch", project_dir)

    # then incus is invoked to launch the matching image under that name, with the
    # common container configuration applied
    run.assert_any_call(
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


def test_create_container_adds_shifted_bind_mount_of_project_dir() -> None:
    # given a mocked subprocess.run and a project directory to bind mount
    project_dir = Path("/home/raniz/src/my-project")
    with patch("ask.incus.subprocess.run") as run:
        # when creating a container for the "arch" distribution named "my-project"
        create_container("my-project", "arch", project_dir)

    # then a shifted disk device bind-mounting the project directory at the same
    # path is added to the container
    run.assert_any_call(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "project",
            "disk",
            "source=/home/raniz/src/my-project",
            "path=/home/raniz/src/my-project",
            "shift=true",
        ],
        check=True,
    )


def test_create_container_adds_shifted_bind_mount_for_each_configured_mount() -> None:
    # given a mocked subprocess.run and two configured bind mounts
    project_dir = Path("/home/raniz/src/my-project")
    bind_mounts = [Path("/home/raniz/.config/foo"), Path("/home/raniz/.cache/bar")]
    with patch("ask.incus.subprocess.run") as run:
        # when creating a container with those bind mounts configured
        create_container("my-project", "arch", project_dir, bind_mounts=bind_mounts)

    # then a shifted disk device is added for each configured mount, at the same
    # path inside the container
    run.assert_any_call(
        [
            "incus",
            "config",
            "device",
            "add",
            "my-project",
            "bind-0",
            "disk",
            "source=/home/raniz/.config/foo",
            "path=/home/raniz/.config/foo",
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
            "bind-1",
            "disk",
            "source=/home/raniz/.cache/bar",
            "path=/home/raniz/.cache/bar",
            "shift=true",
        ],
        check=True,
    )
