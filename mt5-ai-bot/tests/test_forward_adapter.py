import json
import sqlite3
from contextlib import closing

from src.monitoring.forward_adapter import DIAGNOSTIC, INVALID, VALIDATED, FixtureFreeze, read_forward_events


def journal(path, *, source="synthetic_fixture", trusted=True, gap=None, indexed=True):
    first = {
        "model": "frozen-model", "source": source, "session": "fixture-session",
        "latest_completed_raw_time": 3600, "active_raw_time": 7200,
        "raw_broker_hour_signal": None, "host_utc_before": 8000, "host_utc_after": 8000.01,
        "host_monotonic": 10, "tick_raw_time": 7999, "tick_raw_time_msc": 7999500,
        "bid": 1.1, "ask": 1.1002, "clock_certified": trusted,
        "gap_reason": None, "classification": "historical_context",
    }
    second = {**first, "latest_completed_raw_time": 7200, "active_raw_time": 10800,
              "raw_broker_hour_signal": 0, "host_utc_before": 8015, "host_utc_after": 8015.01,
              "host_monotonic": 25, "tick_raw_time": 8014, "tick_raw_time_msc": 8014500,
              "gap_reason": gap, "classification": "observed_rollover"}
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE forward_polls (seq INTEGER PRIMARY KEY, payload TEXT)")
        db.execute("CREATE TABLE forward_bars (model TEXT, bar INTEGER, poll INTEGER)")
        db.execute("CREATE TABLE forward_source (singleton INTEGER PRIMARY KEY, salt TEXT, digest TEXT)")
        db.execute("INSERT INTO forward_source VALUES (1,'fixture-salt','fixture-digest')")
        db.executemany("INSERT INTO forward_polls VALUES (?, ?)",
                       [(1, json.dumps(first)), (2, json.dumps(second))])
        if indexed:
            db.execute("INSERT INTO forward_bars VALUES ('frozen-model',7200,2)")


FREEZE = FixtureFreeze("frozen-model", "fixture-session", 1, 8014)


def test_only_frozen_trusted_fixture_can_be_classified_as_validated(tmp_path):
    for name, source, trusted, freeze, expected in (
        ("fixture", "synthetic_fixture", True, FREEZE, VALIDATED),
        ("no-freeze", "synthetic_fixture", True, None, DIAGNOSTIC),
        ("uncertified", "synthetic_fixture", False, FREEZE, DIAGNOSTIC),
        ("canonical", "mt5_demo_eurusd_h1_chart_bid", True, FREEZE, DIAGNOSTIC),
        ("old", "synthetic_fixture", True,
         FixtureFreeze("frozen-model", "fixture-session", 2, 8014), DIAGNOSTIC),
    ):
        path = tmp_path / name
        journal(path, source=source, trusted=trusted)
        original = path.read_bytes()
        first, event = read_forward_events(path, fixture_freeze=freeze)
        assert first["validation"] == DIAGNOSTIC
        assert event["validation"] == expected
        assert event["poll_id"] == 2 and event["raw_broker_hour_signal"] == 0
        assert event["latest_completed_raw_time"] == 7200
        assert event["tick_raw_time_msc"] == 8014500
        assert path.read_bytes() == original


def test_invalid_rollover_and_corrupt_poll_cannot_be_validated(tmp_path):
    path = tmp_path / "missing-index"
    journal(path, indexed=False)
    assert list(read_forward_events(path, fixture_freeze=FREEZE))[-1]["validation"] == INVALID
    path = tmp_path / "gap"
    journal(path, gap="restart_or_poll_gap")
    assert list(read_forward_events(path, fixture_freeze=FREEZE))[-1]["validation"] == INVALID
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE forward_polls SET payload='bad JSON' WHERE seq=1")
    assert [event["validation"] for event in read_forward_events(path)] == [INVALID, INVALID]
