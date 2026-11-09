from pathlib import Path
from unittest.mock import patch

import pytest

from ask import main
from ask.config import ConfigError


def test_main_reports_config_errors_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command that fails on an invalid configuration
    error = ConfigError(Path("/cfg/config.toml"), ["shell.name: bad"])

    # when running the CLI
    with patch("ask.app", side_effect=error), pytest.raises(SystemExit) as exit_info:
        main()

    # then the error is printed to stderr and the process exits with status 1
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "ask: invalid configuration in /cfg/config.toml\n  shell.name: bad\n"
    )
