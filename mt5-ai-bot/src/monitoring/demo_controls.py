"""Demo-only remote PAUSE/RESUME state for signal simulation.

Not an order interface. Does not call MetaTrader 5. Remote pause never
removes the separate manual KILL_SWITCH; pause is safe and idempotent.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PAUSE_PATH = Path("runtime/remote_pause.flag")


def demo_paused(path: str | Path = DEFAULT_PAUSE_PATH) -> bool:
    return Path(path).is_file()


def pause_demo(path: str | Path = DEFAULT_PAUSE_PATH) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic creation; a concurrent pause command must never truncate data.
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(datetime.now(timezone.utc).isoformat() + "\n")


def resume_demo(path: str | Path = DEFAULT_PAUSE_PATH) -> None:
    # This clears ONLY the phone-controlled pause, never the manual safety
    # kill switch. It never calls mt5.order_send or any trade function.
    Path(path).unlink(missing_ok=True)
