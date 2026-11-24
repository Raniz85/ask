from ask.user import ResolvedUser
from ask.user_session import env

_USER = ResolvedUser(
    name="raniz",
    uid=1000,
    shell="bash",
    group_name="raniz",
    gid=1000,
    extra_groups=[],
)


def test_env_points_at_the_users_runtime_directory_and_session_bus() -> None:
    # given a resolved user
    # when computing the environment of their systemd session
    session_env = env(_USER)

    # then it names their runtime directory and session bus
    assert session_env == {
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    }
