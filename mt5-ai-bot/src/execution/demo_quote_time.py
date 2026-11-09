"""Strict timestamp gate shared by DEMO readiness and execution."""
from __future__ import annotations

import math

MAX_TICK_AGE_SECONDS = 60


def quote_time_blocker(tick, now_s: float) -> str | None:
    seconds = getattr(tick, "time", None)
    milliseconds = getattr(tick, "time_msc", None)
    if (type(seconds) is not int or seconds <= 0
            or type(milliseconds) is not int or milliseconds <= 0
            or not math.isfinite(now_s)):
        return "Broker tick timestamp is missing or invalid"
    if milliseconds // 1000 != seconds:
        return "Broker tick timestamp fields disagree"
    age = now_s - milliseconds / 1000
    if age < 0:
        return "Broker tick is future-dated against UTC"
    if now_s - seconds > MAX_TICK_AGE_SECONDS:
        return "Broker tick is stale"
    return None
