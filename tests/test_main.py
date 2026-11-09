import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ask import main, run
from ask.config import ConfigError
from ask.errors import AskError


@contextmanager
def _app_resolving_to(
    command: Mock,
    bound: inspect.BoundArguments | None = None,
    ignored: dict[str, type] | None = None,
) -> Iterator[None]:
    with patch("ask.app") as app_mock:
        app_mock.parse_args.return_value = (
            command,
            bound or inspect.Signature().bind(),
            ignored or {},
        )
        yield


def test_run_reports_config_errors_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command that fails on an invalid configuration
    error = ConfigError(Path("/cfg/config.toml"), ["shell.name: bad"])

    # when running the CLI
    with (
        _app_resolving_to(Mock(side_effect=error)),
        pytest.raises(SystemExit) as exit_info,
    ):
        run([], debug=False, create=False)

    # then the error is printed to stderr and the process exits with status 1
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "ask: invalid configuration in /cfg/config.toml\n  shell.name: bad\n"
    )


def test_run_reports_ask_errors_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command that fails with an error meant for the user
    error = AskError("something the user can fix")

    # when running the CLI
    with (
        _app_resolving_to(Mock(side_effect=error)),
        pytest.raises(SystemExit) as exit_info,
    ):
        run([], debug=False, create=False)

    # then the error is printed to stderr and the process exits with status 1
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == "ask: something the user can fix\n"


def test_run_reports_unexpected_errors_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command that fails with an error ask does not anticipate
    error = RuntimeError("boom")

    # when running the CLI without debugging enabled
    with (
        _app_resolving_to(Mock(side_effect=error)),
        pytest.raises(SystemExit) as exit_info,
    ):
        run([], debug=False, create=False)

    # then the error type and message are printed along with how to get the
    # traceback, and the process exits with status 1
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "ask: unexpected error: RuntimeError: boom\n"
        "ask: run with --debug or ASK_DEBUG=1 for the full traceback\n"
    )


def test_run_reports_interruption_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given a command interrupted by the user pressing Ctrl-C
    error = KeyboardInterrupt()

    # when running the CLI
    with (
        _app_resolving_to(Mock(side_effect=error)),
        pytest.raises(SystemExit) as exit_info,
    ):
        run([], debug=False, create=False)

    # then the interruption is reported and the process exits with status 130
    assert exit_info.value.code == 130
    assert capsys.readouterr().err == "ask: interrupted\n"


@pytest.mark.parametrize(
    "error", [AskError("user error"), RuntimeError("boom")], ids=repr
)
def test_run_reraises_errors_when_debugging(error: Exception) -> None:
    # given a command that fails

    # when running the CLI with debugging enabled
    with _app_resolving_to(Mock(side_effect=error)), pytest.raises(Exception) as raised:
        run([], debug=True, create=False)

    # then the original error propagates so Python prints its traceback
    assert raised.value is error


@pytest.mark.parametrize(
    ("tokens", "env", "expected_tokens", "expected_debug", "expected_create"),
    [
        (["converge"], {}, ("converge",), False, False),
        (["--debug", "converge"], {}, ("converge",), True, False),
        (["converge"], {"ASK_DEBUG": "1"}, ("converge",), True, False),
        (["converge"], {"ASK_DEBUG": ""}, ("converge",), False, False),
        (
            ["exec", "--", "ls", "--debug"],
            {},
            ("exec", "--", "ls", "--debug"),
            False,
            False,
        ),
        (["--create", "converge"], {}, ("converge",), False, True),
        (
            ["exec", "--", "ls", "--create"],
            {},
            ("exec", "--", "ls", "--create"),
            False,
            False,
        ),
    ],
)
def test_main_runs_the_command_with_the_global_flags(
    monkeypatch: pytest.MonkeyPatch,
    tokens: list[str],
    env: dict[str, str],
    expected_tokens: tuple[str, ...],
    expected_debug: bool,
    expected_create: bool,
) -> None:
    # given an environment that may enable debugging
    monkeypatch.delenv("ASK_DEBUG", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    # when running the CLI with the given arguments
    with patch("ask.run") as run_mock, pytest.raises(SystemExit) as exit_info:
        main(tokens)

    # then the command tokens after the global flags are run with the resolved
    # debug and create settings, and the process exits successfully
    run_mock.assert_called_once_with(
        expected_tokens, debug=expected_debug, create=expected_create
    )
    assert exit_info.value.code == 0


def _command_accepting_create_missing(
    gui: bool = False, *, create_missing: bool = False
) -> None:
    pass


def _command_without_create_missing(gui: bool = False) -> None:
    pass


def test_run_passes_create_to_commands_that_accept_it() -> None:
    # given a command that accepts whether to create a missing container
    command = Mock()
    bound = inspect.signature(_command_accepting_create_missing).bind(gui=True)
    ignored = {"create_missing": bool}

    # when running the CLI with create enabled
    with _app_resolving_to(command, bound, ignored):
        run(["enter", "--gui"], debug=False, create=True)

    # then the command is called with its parsed arguments and create enabled
    command.assert_called_once_with(True, create_missing=True)


def test_run_does_not_pass_create_to_commands_that_do_not_accept_it() -> None:
    # given a command that does not accept whether to create a missing container
    command = Mock()
    bound = inspect.signature(_command_without_create_missing).bind(gui=True)

    # when running the CLI with create enabled
    with _app_resolving_to(command, bound):
        run(["create", "--gui"], debug=False, create=True)

    # then the command is called with only its parsed arguments
    command.assert_called_once_with(True)
