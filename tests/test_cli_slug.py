"""Tests for slugification in CLI commands."""

from pathlib import Path
from unittest.mock import patch

import pytest
from ask import incus
from ask.cli import create, converge, _running_container
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
    with patch("ask.incus.Container.create") as mock_create, \
         patch("ask.incus.Container.snapshot", return_value=None), \
         patch("ask.cli._resolve_project") as mock_resolve, \
         patch("ask.cli._running_container", return_value=(incus.Container(slugify(mock_project_dir.name)), None)), \
         patch("ask.cli.converge"):
        mock_resolve.return_value.flavor.distribution = "arch"
        with patch("pathlib.Path.cwd", return_value=mock_project_dir):
            create()
            mock_create.assert_called_once_with("my-project-with-dots", "arch")


def test_running_container_uses_slugified_name(mock_project_dir):
    """Test that `_running_container` uses a slugified container name."""
    with patch("ask.incus.Container.snapshot", return_value=None), \
         patch("ask.cli.create"), \
         patch("ask.cli._confirm", return_value=True):
        with patch("pathlib.Path.cwd", return_value=mock_project_dir):
            container, _ = _running_container(mock_project_dir, create_missing=True)
            assert container.name == "my-project-with-dots"