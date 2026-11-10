"""Read a consistent snapshot of the prospective journal without creating it."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing

from src.monitoring.shadow_diagnostics import POLL_CONTINUITY_SECONDS


def audit_forward(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        integrity = db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        polls = [(seq, json.loads(payload)) for seq, payload in db.execute(
            "SELECT seq, payload FROM forward_polls ORDER BY seq")]
        index = db.execute("SELECT model, bar, poll FROM forward_bars").fetchall()
        bound = db.execute(
            "SELECT count(*) FROM forward_source WHERE singleton=1 AND salt IS NOT NULL AND digest IS NOT NULL"
        ).fetchone()[0] == 1

    decisions = Counter()
    gaps = Counter()
    quote_blockers = Counter()
    issues = Counter()
    expected = []
    sessions = set()
    restarts = 0
    previous = None
    for seq, row in polls:
        sessions.add(row["session"])
        if previous and previous["session"] != row["session"]:
            restarts += 1
        if row.get("gap_reason"):
            gaps[row["gap_reason"]] += 1
        if row.get("reason"):
            quote_blockers[row["reason"]] += 1
        if row["bid"] is None or row["ask"] is None:
            issues["missing_or_invalid_bid_ask"] += 1
        if (type(row["tick_raw_time"]) is not int or type(row["tick_raw_time_msc"]) is not int
                or row["tick_raw_time_msc"] // 1000 != row["tick_raw_time"]):
            issues["invalid_tick_timestamp_fields"] += 1
        if row.get("clock_certified") is not False:
            issues["unexpected_clock_certification"] += 1
        direction = row["raw_broker_hour_signal"]
        if row["classification"] == "observed_rollover":
            bar = row["latest_completed_raw_time"]
            expected.append((row["model"], bar, seq))
            if type(direction) is int and direction in (-1, 0, 1):
                decisions[str(direction)] += 1
            else:
                issues["invalid_rollover_direction"] += 1
            if (not previous or previous["session"] != row["session"]
                    or row["gap_reason"] or previous["active_raw_time"] != bar
                    or row["active_raw_time"] != bar + 3600):
                issues["nonadjacent_rollover"] += 1
            elif not 0 < row["host_monotonic"] - previous["host_monotonic"] <= POLL_CONTINUITY_SECONDS:
                issues["rollover_outside_poll_window"] += 1
            elif abs((row["host_utc_after"] - previous["host_utc_after"])
                     - (row["host_monotonic"] - previous["host_monotonic"])) > 2:
                issues["rollover_host_clock_jump"] += 1
        elif direction is not None:
            issues["decision_outside_rollover"] += 1
        previous = row

    if set(index) != set(expected):
        issues["bar_index_mismatch"] += 1
    if len({(model, bar) for model, bar, _ in expected}) != len(expected):
        issues["duplicate_bar_decision"] += 1
    return {
        "integrity_ok": integrity,
        "source_bound": bound,
        "polls": len(polls),
        "sessions": len(sessions),
        "restart_transitions": restarts,
        "gaps": dict(gaps),
        "quote_blockers": dict(quote_blockers),
        "rollovers": len(expected),
        "decisions": dict(decisions),
        "issues": dict(issues),
        "last_observed_host_epoch": previous["host_utc_after"] if previous else None,
    }
