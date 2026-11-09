from dataclasses import dataclass


@dataclass
class ResolvedUser:
    name: str
    uid: int
    shell: str
    group_name: str
    gid: int
    extra_groups: list[str]


def home_env(user: ResolvedUser) -> dict[str, str]:
    return {"HOME": f"/home/{user.name}"}
