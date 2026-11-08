from typing import Protocol, runtime_checkable

from ask.config import ResolvedUser
from ask.incus import Mount


def resolve_packages(packages: dict[str, list[str]], distribution: str) -> list[str]:
    return packages.get("common", []) + packages.get(distribution, [])


@runtime_checkable
class Module(Protocol):
    name: str

    def packages_for(self, distribution: str) -> list[str]: ...
    def mounts_for(self, user: ResolvedUser) -> list[Mount]: ...
