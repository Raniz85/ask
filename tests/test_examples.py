import glob
from pathlib import Path

import pytest

from ask.config import Flavor, load_as
from ask.manifest import load as load_manifest
from ask.tool_manager import Mise

EXAMPLES = Path(__file__).parent.parent / "examples"

FLAVOUR_EXAMPLES = glob.glob("*.toml", root_dir=EXAMPLES / "flavors")
MANIFEST_EXAMPLES = glob.glob("ask*.toml", root_dir=EXAMPLES / "flavors")


@pytest.mark.parametrize("name", FLAVOUR_EXAMPLES)
def test_flavour_example_loads(name: str) -> None:
    # when loading the example flavour
    flavor = load_as(EXAMPLES / "flavors" / name, Flavor)

    # then it is a valid flavour with a known distribution
    assert flavor.distribution in ("arch", "debian")


@pytest.mark.parametrize("name", MANIFEST_EXAMPLES)
def test_manifest_example_loads(name: str) -> None:
    # when loading the example manifest
    manifest = load_manifest(EXAMPLES / name)

    # then it is a valid manifest
    assert manifest is not None


def test_mise_example_is_a_recognized_mise_config() -> None:
    # when discovering mise config files in the examples directory
    found = Mise().config_files(EXAMPLES)

    # then the example mise.toml is among them
    assert Path("mise.toml") in found
