from __future__ import annotations

import getpass


def local_username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"

