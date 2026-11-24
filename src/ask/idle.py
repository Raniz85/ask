from datetime import timedelta
from pathlib import Path

from ask.incus import INVOCATION_AT_CONFIG_KEY
from ask.user import ResolvedUser

IDLE_AFTER = timedelta(minutes=5)
CHECK_INTERVAL = timedelta(minutes=1)

SOCKET_PATH = Path("/dev/incus/sock")
SCRIPT_PATH = Path("/usr/local/bin/ask-idle-shutdown")
SERVICE_UNIT_PATH = Path("/etc/systemd/system/ask-idle-shutdown.service")
TIMER_UNIT_PATH = Path("/etc/systemd/system/ask-idle-shutdown.timer")
TIMER_NAME = "ask-idle-shutdown.timer"

# Packages the watchdog script needs inside the instance.
WATCH_PACKAGES = ["curl"]


def shutdown_script(user: ResolvedUser, socket: Path = SOCKET_PATH) -> str:
    interval = int(IDLE_AFTER.total_seconds())
    return f"""#!/usr/bin/env bash
# Shut the instance down once Ask activity has been idle for a while.
set -euo pipefail

user='{user.name}'
idle_after_seconds={interval}
socket='{socket}'
invocation_key='{INVOCATION_AT_CONFIG_KEY}'

now=$(date +%s)

# The last Ask invocation is recorded on this instance's own user.*
# config, readable through the in-instance Incus socket at
# /1.0/config/<key>. If the config cannot be read, stay up rather than
# risk shutting down a busy instance.
if ! last_invocation=$(curl -fs --unix-socket "$socket" \\
    "http://localhost/1.0/config/$invocation_key"); then
    # A 404 just means no Ask invocation has been recorded yet; any
    # other failure means the config is unreadable and we stay up.
    status=$(curl -sS -o /dev/null -w '%{{http_code}}' --unix-socket "$socket" \\
        "http://localhost/1.0/config/$invocation_key") || exit 0
    [ "$status" = 404 ] || exit 0
    last_invocation=""
fi

if [ -n "$last_invocation" ]; then
    last_activity=$(date -d "$last_invocation" +%s 2>/dev/null) || exit 0
else
    # No Ask invocation recorded yet: count idleness from instance start.
    last_activity=$((now - $(ps -o etimes= -p 1 | tr -d '[:space:]')))
fi

# A login session for the user keeps the instance up.
if who | awk '{{print $1}}' | grep -qx "$user"; then
    exit 0
fi

# Any program running as the user keeps the instance up, except those of
# the user's lingering systemd manager, which always runs.
user_programs=$(ps -ww -u "$user" -o cgroup= \\
    | grep -cv "/user@{user.uid}\\.service/") || true
if (( user_programs > 0 )); then
    exit 0
fi

if (( now - last_activity >= idle_after_seconds )); then
    systemctl poweroff
fi
"""


def service_unit() -> str:
    return f"""[Unit]
Description=Shut down the Ask instance once it has been idle for a while

[Service]
Type=oneshot
ExecStart={SCRIPT_PATH}
"""


def timer_unit() -> str:
    interval = int(CHECK_INTERVAL.total_seconds())
    return f"""[Unit]
Description=Run the Ask idle shutdown check every {interval} seconds

[Timer]
OnBootSec={interval}s
OnUnitActiveSec={interval}s

[Install]
WantedBy=timers.target
"""
