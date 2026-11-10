from types import SimpleNamespace

import numpy as np
import pytest

from src.monitoring.shadow_diagnostics import ProspectiveJournal, export, export_forward, observe
from src.monitoring.forward_audit import audit_forward


class DemoFeed:
    ACCOUNT_TRADE_MODE_DEMO = 0
    TIMEFRAME_H1 = 16385

    def __init__(self):
        self.mode = 0

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode, login=1, server="demo")

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        assert (symbol, timeframe, start, count) == ("EURUSD", self.TIMEFRAME_H1, 1, 512)
        return np.array([(1_700_000_000 + i * 3600, 1., 1.1, .9, 1.)
                         for i in range(220)],
                        dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"),
                               ("low", "f8"), ("close", "f8")])

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=1_800_007_200, time_msc=1_800_007_200_000)


def test_restart_preserves_one_diagnostic_per_completed_bar(tmp_path, monkeypatch):
    monkeypatch.setattr("src.monitoring.shadow_diagnostics.time.time", lambda: 1_800_000_000)
    journal = tmp_path / "forward.sqlite3"
    observe(DemoFeed(), journal)
    observe(DemoFeed(), journal)
    row, = export(journal)
    assert row["mode"] == "diagnostics_only"
    assert row["raw_broker_hour_signal"] == 0
    assert row["quote_blocker"] == "Broker tick is future-dated against UTC"


def test_funded_session_creates_no_journal(tmp_path):
    api = DemoFeed()
    api.mode = 2
    journal = tmp_path / "forward.sqlite3"
    with pytest.raises(RuntimeError, match="Connected DEMO"):
        observe(api, journal)
    assert not journal.exists()


class ForwardFeed(DemoFeed):
    offset = 0
    connected = True
    login = 1

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode, login=self.login, server="demo")

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        assert (symbol, timeframe, start, count) == ("EURUSD", self.TIMEFRAME_H1, 0, 513)
        rates = super().copy_rates_from_pos(symbol, timeframe, 1, 512)
        rates["time"] += self.offset * 3600
        return rates

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=1_800_007_200, time_msc=1_800_007_200_000,
                               bid=1.10001, ask=1.10003)


def test_observed_rollover_and_restart_gap(tmp_path, monkeypatch):
    now = [100]
    monkeypatch.setattr("src.monitoring.shadow_diagnostics.time.monotonic", lambda: now[0])
    monkeypatch.setattr("src.monitoring.shadow_diagnostics.time.time", lambda: 1_800_000_000 + now[0])
    path = tmp_path / "forward.sqlite3"
    feed = ForwardFeed()
    journal = ProspectiveJournal(path)
    assert journal.poll(feed)["raw_broker_hour_signal"] is None
    feed.offset = 1
    now[0] += 15
    assert journal.poll(feed)["raw_broker_hour_signal"] == 0
    feed.offset = 4
    now[0] += 15
    missed = ProspectiveJournal(path).poll(feed)
    assert missed["gap_reason"] == "restart_or_poll_gap"
    assert missed["unobserved_raw_hours"] == 3
    assert missed["raw_broker_hour_signal"] is None
    assert missed["bid"] == 1.10001
    assert missed["clock_certified"] is False
    assert len(export_forward(path)["forward"]) == 3


def test_disconnected_poll_and_corrupt_file_fail_closed(tmp_path):
    path = tmp_path / "forward.sqlite3"
    feed = ForwardFeed()
    feed.connected = False
    with pytest.raises(RuntimeError, match="Connected DEMO"):
        ProspectiveJournal(path).poll(feed)
    assert not path.exists()
    original = b"invalid sqlite"
    path.write_bytes(original)
    feed.connected = True
    import sqlite3
    with pytest.raises(sqlite3.DatabaseError):
        ProspectiveJournal(path).poll(feed)
    assert path.read_bytes() == original


def test_restarted_journal_rejects_different_demo_identity(tmp_path):
    path = tmp_path / "forward.sqlite3"
    feed = ForwardFeed()
    ProspectiveJournal(path).poll(feed)
    feed.login = 2
    with pytest.raises(RuntimeError, match="different DEMO source"):
        ProspectiveJournal(path).poll(feed)
    assert len(export_forward(path)["forward"]) == 1


def test_audit_counts_zero_once_after_restart_and_long_gap(tmp_path, monkeypatch):
    now = [100]
    monkeypatch.setattr("src.monitoring.shadow_diagnostics.time.monotonic", lambda: now[0])
    monkeypatch.setattr("src.monitoring.shadow_diagnostics.time.time", lambda: 1_800_000_000 + now[0])
    path = tmp_path / "forward.sqlite3"
    feed = ForwardFeed()
    journal = ProspectiveJournal(path)
    journal.poll(feed)
    now[0] += 15
    feed.offset = 1
    journal.poll(feed)
    journal = ProspectiveJournal(path)
    now[0] += 15
    feed.offset = 0
    journal.poll(feed)
    now[0] += 15
    feed.offset = 1
    journal.poll(feed)
    now[0] += 90
    feed.offset = 2
    journal.poll(feed)

    result = audit_forward(path)
    assert result["integrity_ok"] and result["source_bound"]
    assert result["polls"] == 5
    assert result["rollovers"] == 1
    assert result["decisions"] == {"0": 1}
    evidence = result["first_observed_decision"]
    assert evidence["journal_poll_id"] == 2
    assert evidence["previous_poll_id"] == 1
    assert evidence["previous_active_raw_time"] == evidence["latest_completed_raw_time"]
    assert evidence["raw_broker_hour_signal"] == 0
    assert evidence["clock_certified"] is False
    assert result["restart_transitions"] == 1
    assert result["gaps"] == {"restart_or_poll_gap": 2}
    assert result["issues"] == {}


def test_audit_flags_missing_bar_index_even_when_sqlite_is_healthy(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing

    now = [100]
    monkeypatch.setattr("src.monitoring.shadow_diagnostics.time.monotonic", lambda: now[0])
    monkeypatch.setattr("src.monitoring.shadow_diagnostics.time.time", lambda: 1_800_000_000 + now[0])
    path = tmp_path / "forward.sqlite3"
    feed = ForwardFeed()
    journal = ProspectiveJournal(path)
    journal.poll(feed)
    now[0] += 15
    feed.offset = 1
    journal.poll(feed)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM forward_bars")
    result = audit_forward(path)
    assert result["integrity_ok"]
    assert result["issues"] == {"bar_index_mismatch": 1}


def test_audit_flags_malformed_poll_without_inventing_a_heartbeat(tmp_path):
    import sqlite3
    from contextlib import closing

    path = tmp_path / "forward.sqlite3"
    ProspectiveJournal(path).poll(ForwardFeed())
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE forward_polls SET payload = 'invalid JSON'")
    result = audit_forward(path)
    assert result["integrity_ok"]
    assert result["issues"] == {"malformed_poll": 1}
    assert result["first_observed_decision"] is None
    assert result["poll_heartbeat_fresh"] is False
