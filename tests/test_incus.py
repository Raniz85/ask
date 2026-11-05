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
    # common container configuration and a shifted bind mount of the project directory
    # at the same path inside the container
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
            "--device",
            "project,type=disk,source=/home/raniz/src/my-project,"
            "path=/home/raniz/src/my-project,shift=true",
        ],
        check=True,
    )
