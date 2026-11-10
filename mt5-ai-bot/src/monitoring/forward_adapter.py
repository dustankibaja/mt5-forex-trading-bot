"""Read-only classification of forward polls. Synthetic trust is test-only."""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass

from src.monitoring.shadow_diagnostics import POLL_CONTINUITY_SECONDS


VALIDATED = "VALIDATED FOR PAPER EXECUTION"
DIAGNOSTIC = "DIAGNOSTICS ONLY"
INVALID = "INVALID OR INCOMPLETE"


@dataclass(frozen=True)
class FixtureFreeze:
    model: str
    session: str
    after_poll_id: int
    evaluation_start_utc: float


FIELDS = (
    "model", "source", "session", "latest_completed_raw_time", "active_raw_time",
    "raw_broker_hour_signal", "host_utc_before", "host_utc_after", "host_monotonic",
    "tick_raw_time", "tick_raw_time_msc", "bid", "ask", "clock_certified",
    "gap_reason", "classification", "reason",
)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _classify(row, previous, poll_id, indexed, freeze):
    before, after = row["host_utc_before"], row["host_utc_after"]
    seconds, millis = row["tick_raw_time"], row["tick_raw_time_msc"]
    bid, ask = row["bid"], row["ask"]
    if (not all(isinstance(row[key], str) and row[key] for key in ("model", "source", "session"))
            or not all(_finite(x) for x in (before, after, row["host_monotonic"], bid, ask))
            or not 0 <= before <= after or not 0 < bid <= ask
            or type(seconds) is not int or type(millis) is not int or seconds <= 0 or millis // 1000 != seconds
            or type(row["active_raw_time"]) is not int or type(row["latest_completed_raw_time"]) is not int
            or not 0 < row["latest_completed_raw_time"] < row["active_raw_time"]
            or type(row["clock_certified"]) is not bool):
        return INVALID, "Malformed observation"
    if row["classification"] == "observed_rollover":
        direction = row["raw_broker_hour_signal"]
        bar = row["latest_completed_raw_time"]
        if (type(direction) is not int or direction not in (-1, 0, 1)
                or indexed != (row["model"], bar) or row["gap_reason"] or not previous
                or any(previous[key] != row[key] for key in ("session", "model", "source"))
                or previous["active_raw_time"] != bar or row["active_raw_time"] != bar + 3600):
            return INVALID, "Decision does not match an indexed adjacent rollover"
        elapsed = row["host_monotonic"] - previous["host_monotonic"]
        if not 0 < elapsed <= POLL_CONTINUITY_SECONDS or abs(elapsed - (after - previous["host_utc_after"])) > 2:
            return INVALID, "Decision crosses a polling or host clock gap"
    elif (row["raw_broker_hour_signal"] is not None or indexed is not None
          or row["classification"] not in ("same_active_bar", "historical_context")):
        return INVALID, "Unexpected decision or classification"

    if (freeze is None or row["source"] != "synthetic_fixture" or not row["clock_certified"]
            or (row["model"], row["session"]) != (freeze.model, freeze.session)
            or poll_id <= freeze.after_poll_id or before < freeze.evaluation_start_utc
            or row["gap_reason"] or row["classification"] == "historical_context"
            or not 0 <= before - millis / 1000 <= after - millis / 1000 <= 60):
        return DIAGNOSTIC, "No eligible certified prospective quote"
    if (previous is None or any(previous[key] != row[key] for key in ("session", "model", "source"))
            or not 0 < row["host_monotonic"] - previous["host_monotonic"] <= POLL_CONTINUITY_SECONDS
            or abs((row["host_monotonic"] - previous["host_monotonic"])
                   - (after - previous["host_utc_after"])) > 2):
        return DIAGNOSTIC, "No continuous fixture predecessor"
    return VALIDATED, "Synthetic fixture within explicit evaluation freeze"


def read_forward_events(path, *, fixture_freeze: FixtureFreeze | None = None):
    """Stream events from one SQLite snapshot without opening a write connection."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        source_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forward_source'"
        ).fetchone()
        source_bound = bool(source_table and db.execute(
            "SELECT 1 FROM forward_source WHERE singleton=1 AND length(salt)>0 AND length(digest)>0"
        ).fetchone())
        index = {}
        for model, bar, poll in db.execute("SELECT model, bar, poll FROM forward_bars"):
            index[poll] = (model, bar) if poll not in index else ()
        previous = None
        for poll_id, payload in db.execute("SELECT seq, payload FROM forward_polls ORDER BY seq"):
            try:
                parsed = json.loads(payload)
            except (TypeError, ValueError):
                parsed = None
            row = {key: parsed.get(key) if isinstance(parsed, dict) else None for key in FIELDS}
            state, reason = (_classify(row, previous, poll_id, index.get(poll_id), fixture_freeze)
                             if source_bound else (INVALID, "Missing source binding"))
            yield {"poll_id": poll_id, **row, "source_bound": source_bound,
                   "validation": state, "validation_reason": reason}
            previous = row if state != INVALID else None
