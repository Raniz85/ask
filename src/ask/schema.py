from pydantic import ConfigDict

FORBID_UNKNOWN_KEYS = ConfigDict(extra="forbid")
