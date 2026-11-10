"""Read a consistent snapshot of the prospective journal without creating it."""
from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import Counter
from contextlib import closing

from src.monitoring.shadow_diagnostics import POLL_CONTINUITY_SECONDS


def audit_forward(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        integrity = db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        index = db.execute("SELECT model, bar, poll FROM forward_bars").fetchall()
        bound = db.execute(
            "SELECT count(*) FROM forward_source WHERE singleton=1 AND salt IS NOT NULL AND digest IS NOT NULL"
        ).fetchone()[0] == 1
        polls = db.execute("SELECT seq, payload FROM forward_polls ORDER BY seq")
        return _summarize(polls, index, integrity, bound)


def _summarize(polls, index, integrity, bound):
    decisions = Counter()
    gaps = Counter()
    quote_blockers = Counter()
    issues = Counter()
    expected = []
    sessions = set()
    restarts = 0
    longest_poll_interval = None
    first_decision = None
    first_at = None
    last_at = None
    previous = None
    count = 0
    for seq, payload in polls:
        count += 1
        try:
            row = json.loads(payload)
        except (TypeError, ValueError):
            row = None
        clocks = ("host_utc_before", "host_utc_after", "host_monotonic")
        if (not isinstance(row, dict) or not isinstance(row.get("session"), str)
                or not isinstance(row.get("model"), str)
                or any(type(row.get(key)) not in (int, float) or not math.isfinite(row[key]) for key in clocks)
                or type(row.get("active_raw_time")) is not int
                or type(row.get("latest_completed_raw_time")) is not int
                or not isinstance(row.get("classification"), str)):
            issues["malformed_poll"] += 1
            previous = None
            continue
        if first_at is None:
            first_at = row["host_utc_before"]
        last_at = row["host_utc_after"]
        if row["host_utc_before"] > last_at:
            issues["reversed_utc_bounds"] += 1
        sessions.add(row["session"])
        if previous and previous["session"] != row["session"]:
            restarts += 1
        elif previous:
            elapsed = row["host_monotonic"] - previous["host_monotonic"]
            longest_poll_interval = max(longest_poll_interval or 0, elapsed)
            if not 0 < elapsed <= POLL_CONTINUITY_SECONDS and not row.get("gap_reason"):
                issues["unmarked_poll_gap"] += 1
        if row.get("gap_reason"):
            gaps[row["gap_reason"]] += 1
        if row.get("reason"):
            quote_blockers[row["reason"]] += 1
        bid, ask = row.get("bid"), row.get("ask")
        if (type(bid) not in (float, int) or type(ask) not in (float, int)
                or not math.isfinite(bid) or not math.isfinite(ask) or not 0 < bid <= ask):
            issues["missing_or_invalid_bid_ask"] += 1
        if (type(row.get("tick_raw_time")) is not int or type(row.get("tick_raw_time_msc")) is not int
                or row["tick_raw_time_msc"] // 1000 != row["tick_raw_time"]):
            issues["invalid_tick_timestamp_fields"] += 1
        if row.get("clock_certified") is not False:
            issues["unexpected_clock_certification"] += 1
        direction = row.get("raw_broker_hour_signal")
        if row["classification"] == "observed_rollover":
            bar = row["latest_completed_raw_time"]
            expected.append((row.get("model"), bar, seq))
            if type(direction) is int and direction in (-1, 0, 1):
                decisions[str(direction)] += 1
            else:
                issues["invalid_rollover_direction"] += 1
            if (not previous or previous["session"] != row["session"]
                    or row.get("gap_reason") or previous["active_raw_time"] != bar
                    or row["active_raw_time"] != bar + 3600):
                issues["nonadjacent_rollover"] += 1
            elif not 0 < row["host_monotonic"] - previous["host_monotonic"] <= POLL_CONTINUITY_SECONDS:
                issues["rollover_outside_poll_window"] += 1
            elif abs((row["host_utc_after"] - previous["host_utc_after"])
                     - (row["host_monotonic"] - previous["host_monotonic"])) > 2:
                issues["rollover_host_clock_jump"] += 1
            if first_decision is None:
                first_decision = {
                    "journal_poll_id": seq,
                    "previous_poll_id": previous_seq if previous else None,
                    "previous_active_raw_time": previous["active_raw_time"] if previous else None,
                    "previous_host_utc_bounds": [previous["host_utc_before"], previous["host_utc_after"]]
                    if previous else None,
                    **{field: row.get(field) for field in (
                        "schema", "source", "model", "active_raw_time", "latest_completed_raw_time",
                        "host_utc_before", "host_utc_after", "host_monotonic", "clock_certified",
                        "tick_raw_time", "tick_raw_time_msc", "bid", "ask", "reason",
                        "raw_broker_hour_signal", "completed_ohlc")},
                }
        elif direction is not None:
            issues["decision_outside_rollover"] += 1
        previous = row
        previous_seq = seq

    if set(index) != set(expected):
        issues["bar_index_mismatch"] += 1
    if len({(model, bar) for model, bar, _ in expected}) != len(expected):
        issues["duplicate_bar_decision"] += 1
    last_age = time.time() - last_at if last_at is not None else None
    return {
        "integrity_ok": integrity,
        "source_bound": bound,
        "polls": count,
        "sessions": len(sessions),
        "restart_transitions": restarts,
        "gaps": dict(gaps),
        "quote_blockers": dict(quote_blockers),
        "rollovers": len(expected),
        "decisions": dict(decisions),
        "issues": dict(issues),
        "first_observed_host_epoch": first_at,
        "last_observed_host_epoch": last_at,
        "observation_span_seconds": last_at - first_at if first_at is not None else None,
        "longest_same_session_poll_interval_seconds": longest_poll_interval,
        "last_poll_age_seconds": last_age,
        "poll_heartbeat_fresh": last_age is not None and 0 <= last_age <= POLL_CONTINUITY_SECONDS,
        "first_observed_decision": first_decision,
    }
