from pathlib import Path

from ask import docgen


def test_docs_are_up_to_date() -> None:
    root = Path(__file__).parent.parent
    for name, generated in (
        ("config.md", docgen.sections()),
        ("commands.md", docgen._cli_section()),
    ):
        doc = (root / "docs" / name).read_text()
        assert docgen.update(doc, generated) == doc, (
            f"docs/{name} is stale, run `just docs`"
        )
