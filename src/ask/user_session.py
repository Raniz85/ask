from pathlib import Path

from ask.user import ResolvedUser


def runtime_dir(user: ResolvedUser) -> Path:
    return Path("/run/user") / str(user.uid)


def env(user: ResolvedUser) -> dict[str, str]:
    return {
        "XDG_RUNTIME_DIR": str(runtime_dir(user)),
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir(user) / 'bus'}",
    }
