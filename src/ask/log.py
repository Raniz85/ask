import logging
import sys

logger = logging.getLogger("ask")

_HANDLER_NAME = "ask-debug"


def configure_debug() -> None:
    if any(handler.get_name() == _HANDLER_NAME for handler in logger.handlers):
        logger.setLevel(logging.DEBUG)
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
