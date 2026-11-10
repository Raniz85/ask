"""Tests for the slugify function."""

import pytest
from ask.slug import slugify


def test_slugify_basic():
    """Test slugification of basic project names."""
    assert slugify("my-project") == "my-project"
    assert slugify("MyProject") == "myproject"
    assert slugify("my_project") == "my-project"


def test_slugify_special_characters():
    """Test slugification of names with special characters."""
    assert slugify("my.project") == "my-project"
    assert slugify("my@project") == "my-project"
    assert slugify("my#project") == "my-project"
    assert slugify("my$project") == "my-project"


def test_slugify_unicode():
    """Test slugification of names with Unicode characters."""
    assert slugify("my-pröject") == "my-project"
    assert slugify("my-프로젝트") == "my"


def test_slugify_whitespace():
    """Test slugification of names with whitespace."""
    assert slugify("my project") == "my-project"
    assert slugify("my\tproject") == "my-project"
    assert slugify("my\nproject") == "my-project"


def test_slugify_leading_trailing_hyphens():
    """Test slugification of names with leading/trailing hyphens."""
    assert slugify("-my-project-") == "my-project"
    assert slugify("---my-project---") == "my-project"


def test_slugify_empty():
    """Test slugification of an empty string."""
    with pytest.raises(ValueError):
        slugify("")