from pydantic_core import PydanticCustomError


def known(names: list[str] | set[str]) -> str:
    return f"(known: {', '.join(sorted(names)) or 'none'})"


def unknown_name(kind: str, name: str, names: list[str]) -> PydanticCustomError:
    return PydanticCustomError(
        f"unknown_{kind}",
        "unknown {kind} {name} {known}",
        {"kind": kind, "name": repr(name), "known": known(names)},
    )


def unknown_options(
    kind: str, owner: str, unknown: list[str], option_keys: set[str]
) -> PydanticCustomError:
    return PydanticCustomError(
        f"unknown_{kind}_option",
        "unknown {noun} {unknown} for {owner} {known}",
        {
            "noun": "option" if len(unknown) == 1 else "options",
            "unknown": ", ".join(repr(key) for key in unknown),
            "owner": owner,
            "known": known(option_keys),
        },
    )
