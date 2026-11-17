import logging
from collections.abc import Iterator

import pytest

from ask import log


@pytest.fixture(autouse=True)
def _isolate_ask_logger() -> Iterator[None]:
    logger = logging.getLogger("ask")
    level = logger.level
    handlers = logger.handlers[:]
    logger.setLevel(logging.NOTSET)
    logger.handlers = []
    yield
    logger.setLevel(level)
    logger.handlers = handlers


def test_configure_debug_sets_the_ask_logger_to_debug_level() -> None:
    # given the ask logger at its default level
    logger = logging.getLogger("ask")

    # when debug logging is configured
    log.configure_debug()

    # then the ask logger accepts DEBUG records
    assert logger.level == logging.DEBUG
    assert logger.isEnabledFor(logging.DEBUG)


def test_configure_debug_emits_records_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given debug logging configured
    log.configure_debug()

    # when a debug record is emitted on the ask logger
    logging.getLogger("ask").debug("hello debug")

    # then the record is written to stderr with the logger name as prefix
    assert capsys.readouterr().err == "ask: hello debug\n"


def test_configure_debug_emits_records_from_child_loggers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given debug logging configured
    log.configure_debug()

    # when a child module logger emits a debug record
    logging.getLogger("ask.incus").debug("incus list")

    # then the record is written to stderr prefixed with the child logger name
    assert capsys.readouterr().err == "ask.incus: incus list\n"


def test_configure_debug_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    # given debug logging configured twice
    log.configure_debug()
    log.configure_debug()

    # when a debug record is emitted
    logging.getLogger("ask").debug("once")

    # then it is written exactly once
    assert capsys.readouterr().err == "ask: once\n"


def test_without_configure_debug_records_are_not_emitted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given debug logging not configured
    # when a debug record is emitted on the ask logger
    logging.getLogger("ask").debug("silent")

    # then nothing is written to stderr
    assert capsys.readouterr().err == ""
