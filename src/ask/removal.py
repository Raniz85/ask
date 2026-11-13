REMOVAL_PREFIX = "-"


def is_removal(name: str) -> bool:
    return name.startswith(REMOVAL_PREFIX)


def removals(names: list[str]) -> set[str]:
    return {name.removeprefix(REMOVAL_PREFIX) for name in names if is_removal(name)}
