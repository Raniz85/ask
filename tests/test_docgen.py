from pathlib import Path

from ask import docgen


def test_docs_are_up_to_date() -> None:
    doc = (Path(__file__).parent.parent / "docs" / "config.md").read_text()
    assert docgen.update(doc) == doc, "docs/config.md is stale, run `just docs`"
