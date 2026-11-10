from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from ask import app, main, run
from ask.config import ConfigError
from ask.errors import AskError


@contextmanager
def _app_raising(error: BaseException) -> Iterator[None]:
    with patch("ask.app", side_effect=error):
        yield


@pytest.fixture(autouse=True)
def _terminal_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "60")


def test_run_reports_config_errors_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command that fails on an invalid configuration
    error = ConfigError(Path("/cfg/config.toml"), ["shell.name: bad"])

    # when running the CLI
    with _app_raising(error), pytest.raises(SystemExit) as exit_info:
        run([], debug=False)

    # then the error is printed to stderr and the process exits with status 1
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "╭─ Error ──────────────────────────────────────────────────╮\n"
        "│ Invalid configuration in /cfg/config.toml:               │\n"
        "│   shell.name: bad                                        │\n"
        "╰──────────────────────────────────────────────────────────╯\n"
    )


def test_run_reports_ask_errors_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command that fails with an error meant for the user
    error = AskError("something the user can fix")

    # when running the CLI
    with _app_raising(error), pytest.raises(SystemExit) as exit_info:
        run([], debug=False)

    # then the error is printed to stderr and the process exits with status 1
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "╭─ Error ──────────────────────────────────────────────────╮\n"
        "│ something the user can fix                               │\n"
        "╰──────────────────────────────────────────────────────────╯\n"
    )


def test_run_reports_unexpected_errors_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command that fails with an error ask does not anticipate
    error = RuntimeError("boom")

    # when running the CLI without debugging enabled
    with _app_raising(error), pytest.raises(SystemExit) as exit_info:
        run([], debug=False)

    # then the error type and message are printed along with how to get the
    # traceback, and the process exits with status 1
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "╭─ Error ──────────────────────────────────────────────────╮\n"
        "│ Unexpected error: RuntimeError: boom                     │\n"
        "│ Run with --debug or ASK_DEBUG=1 for the full traceback.  │\n"
        "╰──────────────────────────────────────────────────────────╯\n"
    )


def test_run_reports_interruption_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command interrupted by the user pressing Ctrl-C
    error = KeyboardInterrupt()

    # when running the CLI
    with _app_raising(error), pytest.raises(SystemExit) as exit_info:
        run([], debug=False)

    # then the interruption is reported and the process exits with status 130
    assert exit_info.value.code == 130
    assert capsys.readouterr().err == (
        "╭─ Error ──────────────────────────────────────────────────╮\n"
        "│ Interrupted.                                             │\n"
        "╰──────────────────────────────────────────────────────────╯\n"
    )


@pytest.mark.parametrize(
    "error", [AskError("user error"), RuntimeError("boom")], ids=repr
)
def test_run_reraises_errors_when_debugging(error: Exception) -> None:
    # given a command that fails

    # when running the CLI with debugging enabled
    with _app_raising(error), pytest.raises(Exception) as raised:
        run([], debug=True)

    # then the original error propagates so Python prints its traceback
    assert raised.value is error


@pytest.mark.parametrize(
    ("tokens", "env", "expected_tokens", "expected_debug"),
    [
        (["converge"], {}, ("converge",), False),
        (["--debug", "converge"], {}, ("converge",), True),
        (["converge"], {"ASK_DEBUG": "1"}, ("converge",), True),
        (["converge"], {"ASK_DEBUG": ""}, ("converge",), False),
        (["exec", "--", "ls", "--debug"], {}, ("exec", "--", "ls", "--debug"), False),
    ],
)
def test_main_runs_the_command_with_the_resolved_debug_setting(
    monkeypatch: pytest.MonkeyPatch,
    tokens: list[str],
    env: dict[str, str],
    expected_tokens: tuple[str, ...],
    expected_debug: bool,
) -> None:
    # given an environment that may enable debugging
    monkeypatch.delenv("ASK_DEBUG", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    # when running the CLI with the given arguments
    with patch("ask.run") as run_mock, pytest.raises(SystemExit) as exit_info:
        main(tokens)

    # then the command tokens after --debug are run with the resolved debug
    # setting, and the process exits successfully
    run_mock.assert_called_once_with(expected_tokens, debug=expected_debug)
    assert exit_info.value.code == 0


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (
            ["enter", "--create", "--converge"],
            {"create_missing": True, "converge_changed": True},
        ),
        (["exec", "--no-converge", "true"], {"converge_changed": False}),
        (["converge", "--create"], {"create_missing": True}),
        (["exec", "--", "ls", "--create"], {}),
    ],
)
def test_commands_accept_create_and_converge_flags(
    tokens: list[str], expected: dict[str, bool]
) -> None:
    # given the ask CLI app

    # when parsing a command with create and converge flags
    _, bound, _ = app.parse_args(tokens)

    # then the flags are bound to the command's keyword arguments
    assert bound.kwargs == expected


@pytest.mark.parametrize("command", ["restart", "create"])
def test_create_and_converge_flags_do_not_appear_in_help_for_commands_that_do_not_accept_them(
    capsys: pytest.CaptureFixture[str], command: str
) -> None:
    # given a command that does not accept --create or --converge

    # when getting the help for the command
    with pytest.raises(SystemExit):
        app.meta([command, "--help"])

    # then the help output does not contain --create or --converge
    help_output = capsys.readouterr().out
    assert "--create" not in help_output
    assert "--converge" not in help_output
