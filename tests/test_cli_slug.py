"""Tests for slugification in CLI commands."""

from unittest.mock import call, patch

import pytest

from ask import incus
from ask.cli import _running_container, create, destroy, restart, stop
from ask.incus import InstanceSnapshot
from ask.slug import slugify


@pytest.fixture
def mock_project_dir(tmp_path):
    """Fixture to create a temporary project directory with a special name."""
    project_dir = tmp_path / "my.project.with.dots"
    project_dir.mkdir()
    (project_dir / "ask.toml").write_text("""
[tool.ask]
flavors = ["default"]

[tool.ask.flavors.default]
distribution = "arch"
""")
    return project_dir


def test_create_uses_slugified_name(mock_project_dir):
    """Test that `create` uses a slugified container name."""
    with (
        patch("ask.incus.Container.create") as mock_create,
        patch("ask.incus.Container.snapshot", return_value=None),
        patch("ask.cli._resolve_project") as mock_resolve,
        patch(
            "ask.cli._running_container",
            return_value=(incus.Container(slugify(mock_project_dir.name)), None),
        ),
        patch("ask.cli.converge"),
    ):
        mock_resolve.return_value.flavor.distribution = "arch"
        with patch("pathlib.Path.cwd", return_value=mock_project_dir):
            create()
            mock_create.assert_called_once_with("my-project-with-dots", "arch")


def test_running_container_uses_slugified_name(mock_project_dir):
    """Test that `_running_container` uses a slugified container name."""
    with (
        patch("ask.incus.Container.snapshot", return_value=None),
        patch("ask.cli.create"),
        patch("ask.cli._confirm", return_value=True),
        patch("pathlib.Path.cwd", return_value=mock_project_dir),
    ):
        container, _ = _running_container(mock_project_dir, create_missing=True)
        assert container.name == "my-project-with-dots"


def test_stop_uses_slugified_name(mock_project_dir):
    """Test that `stop` targets the slugified container, like `create` does."""
    with (
        patch("ask.cli.Path.cwd", return_value=mock_project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Running", config={})

        stop()

    container_cls.assert_called_once_with("my-project-with-dots")
    assert container.method_calls == [call.snapshot(), call.stop()]


def test_restart_uses_slugified_name(mock_project_dir):
    """Test that `restart` targets the slugified container, like `create` does."""
    with (
        patch("ask.cli.Path.cwd", return_value=mock_project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Running", config={})

        restart()

    container_cls.assert_called_once_with("my-project-with-dots")
    assert container.method_calls == [call.snapshot(), call.restart()]


def test_destroy_uses_slugified_name(mock_project_dir):
    """Test that `destroy` targets the slugified container, like `create` does."""
    with (
        patch("ask.cli.Path.cwd", return_value=mock_project_dir),
        patch("ask.cli.incus.Container") as container_cls,
    ):
        container = container_cls.return_value
        container.snapshot.return_value = InstanceSnapshot(status="Stopped", config={})

        destroy()

    container_cls.assert_called_once_with("my-project-with-dots")
    assert container.method_calls == [call.snapshot(), call.delete()]
