import re
from collections.abc import Iterable, Mapping
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, StrictStr
from pydantic_core import PydanticCustomError

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _check_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise PydanticCustomError(
            "env_name",
            "invalid environment variable name '{name}'",
            {"name": name},
        )
    return name


def _check_value(value: object) -> object:
    if isinstance(value, str) or value is False:
        return value
    raise PydanticCustomError("env_value", "Input should be a valid string or false")


type Value = str | Literal[False]

Env = dict[
    Annotated[StrictStr, AfterValidator(_check_name)],
    Annotated[StrictStr | Literal[False], BeforeValidator(_check_value)],
]


def merge(envs: Iterable[Mapping[str, Value]]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for env in envs:
        for name, value in env.items():
            if value is False:
                merged.pop(name, None)
            else:
                merged[name] = value
    return merged
