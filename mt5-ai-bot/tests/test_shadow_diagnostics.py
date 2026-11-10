from types import SimpleNamespace

import numpy as np
import pytest

from src.monitoring.shadow_diagnostics import export, observe


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
