"""Utility functions for slugifying project names."""

import re
import unicodedata


def slugify(name: str) -> str:
    """
    Convert a project name into a safe, URL-friendly slug.

    Args:
        name: The project name to slugify.

    Returns:
        A slugified version of the project name, safe for use in Incus container names.
    """
    # Normalize Unicode characters (e.g., convert "é" to "e")
    slug = unicodedata.normalize('NFKD', name)
    # Encode to ASCII bytes and decode to string, ignoring non-ASCII characters
    slug = slug.encode('ascii', 'ignore').decode('ascii')
    # Replace any non-alphanumeric character with a hyphen
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    # Convert to lowercase
    slug = slug.lower()
    # Ensure the slug is not empty
    if not slug:
        raise ValueError("Slugified project name cannot be empty.")
    return slug