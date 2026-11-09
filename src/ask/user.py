from dataclasses import dataclass


@dataclass
class ResolvedUser:
    name: str
    uid: int
    shell: str
    group_name: str
    gid: int
    extra_groups: list[str]
