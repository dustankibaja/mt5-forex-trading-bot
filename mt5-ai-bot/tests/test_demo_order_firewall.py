"""Synthetic MT5 broker: no real account and no live trading APIs."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.execution.demo_order_firewall import (
    DemoSafetyError, execute_one_demo_smoke, initialize_broker_pin,
)

NOW = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)


class FakeDemoMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    SYMBOL_TRADE_MODE_FULL = 4
    ORDER_TYPE_BUY = 0
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010

    def __init__(self):
        self.mode = self.ACCOUNT_TRADE_MODE_DEMO
        self.connected = True
        self.login = 12345
        self.server = "FakeDemo"
        self.exposures = ()
        self.pending = ()
        self.trade_allowed = True
        self.quote_age = 0
        self.spread = 1.0
        self.lot_min = .01
        self.equity = 10_000.0
        self.sent = []
        self.result = SimpleNamespace(retcode=self.TRADE_RETCODE_DONE)
        self.fail_check = False
        self.exception_on_send = False
        self.switch_to_live_during_check = False

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected,
                               trade_allowed=self.trade_allowed)

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode,
                               trade_allowed=self.trade_allowed, trade_expert=True,
                               login=self.login, server=self.server,
                               equity=self.equity, margin_free=self.equity * .9)

    def symbol_info(self, symbol):
        return SimpleNamespace(
            visible=True, trade_mode=self.SYMBOL_TRADE_MODE_FULL,
            digits=5, point=.00001, volume_min=self.lot_min,
            volume_step=.01, volume_max=100, trade_stops_level=10,
        )

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(ask=1.14000 + self.spread * .0001,
                               bid=1.14000,
                               time=NOW.timestamp()-self.quote_age)

    def positions_get(self, symbol):
        return self.exposures

    def orders_get(self, symbol):
        return self.pending

    def order_calc_profit(self, side, symbol, volume, entry, stop):
        return (stop - entry) * 100000 * volume

    def order_calc_margin(self, side, symbol, volume, entry):
        return volume * 1000

    def order_check(self, request):
        if self.switch_to_live_during_check:
            self.mode = self.ACCOUNT_TRADE_MODE_REAL
        if self.fail_check:
            return SimpleNamespace(retcode=10013)
        return SimpleNamespace(retcode=0)

    def order_send(self, request):
        self.sent.append(request)
        if self.exception_on_send:
            raise RuntimeError("Broker timeout after receipt")
        return self.result


def _setup(tmp_path, broker):
    pin = tmp_path / "pin.json"
    ledger = tmp_path / "ledger.sqlite"
    initialize_broker_pin(broker, pin)
    kwargs = {
        "pin_path": pin, "ledger_path": ledger,
        "manual_kill_switch": tmp_path / "KILL_SWITCH",
        "remote_pause_path": tmp_path / "remote_pause.flag",
        "utcnow": NOW,
    }
    return kwargs


def test_demo_smoke_requires_explicit_execute_flag(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    result = execute_one_demo_smoke(api, **kw)
    assert result.attempted is False
    assert api.sent == []


def test_demo_smoke_sends_exactly_once_with_protective_orders(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    result = execute_one_demo_smoke(api, execute=True, **kw)
    assert result.status == "DEMO_ORDER_FILLED"
    assert len(api.sent) == 1
    request = api.sent[0]
    assert request["symbol"] == "EURUSD"
    assert request["sl"] < request["price"] < request["tp"]
    assert request["volume"] == .01
    assert result.public_report()["live_trading_enabled"] is False
    with pytest.raises(DemoSafetyError, match="quota"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert len(api.sent) == 1
    con = sqlite3.connect(kw["ledger_path"])
    assert con.execute("select status from smoke_intents").fetchone() == ("DEMO_ORDER_FILLED",)
    con.close()


def test_funded_account_never_sends_even_with_execute_flag(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    api.mode = api.ACCOUNT_TRADE_MODE_REAL
    with pytest.raises(DemoSafetyError, match="DEMO"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert api.sent == []


def test_same_type_demo_account_switch_is_detected(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    api.login = 22222
    with pytest.raises(DemoSafetyError, match="pin mismatch"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert api.sent == []


def test_switch_during_order_check_cannot_send(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    api.switch_to_live_during_check = True
    with pytest.raises(DemoSafetyError, match="DEMO"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert api.sent == []


@pytest.mark.parametrize("reason, mutate", [
    ("pause", lambda a, kw: kw["remote_pause_path"].write_text("paused")),
    ("kill", lambda a, kw: kw["manual_kill_switch"].write_text("paused")),
    ("stale", lambda a, kw: setattr(a, "quote_age", 180)),
    ("spread", lambda a, kw: setattr(a, "spread", 6.0)),
    ("min-risk", lambda a, kw: setattr(a, "lot_min", 0.20)),
    ("exposure", lambda a, kw: setattr(a, "exposures", (object(),))),
    ("pending", lambda a, kw: setattr(a, "pending", (object(),))),
    ("not-connected", lambda a, kw: setattr(a, "connected", False)),
    ("check-failure", lambda a, kw: setattr(a, "fail_check", True)),
])
def test_failure_modes_fail_closed_without_any_order(tmp_path, reason, mutate):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    mutate(api, kw)
    with pytest.raises(DemoSafetyError):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert api.sent == [], reason


def test_unknown_broker_outcome_never_retries(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    api.exception_on_send = True
    with pytest.raises(DemoSafetyError, match="Unknown broker outcome"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert len(api.sent) == 1
    api.exception_on_send = False
    with pytest.raises(DemoSafetyError, match="quota"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert len(api.sent) == 1
    con = sqlite3.connect(kw["ledger_path"])
    assert con.execute("select status from smoke_intents").fetchone()[0] == "UNKNOWN_BROKER_OUTCOME"
    con.close()


def test_unknown_result_never_retries_after_restart(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    api.result = None
    with pytest.raises(DemoSafetyError, match="No broker result"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert len(api.sent) == 1
    with pytest.raises(DemoSafetyError, match="quota"):
        execute_one_demo_smoke(api, execute=True, **kw)


def test_refuses_silent_repin_even_same_account(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    with pytest.raises(DemoSafetyError, match="already pinned"):
        initialize_broker_pin(api, kw["pin_path"])
