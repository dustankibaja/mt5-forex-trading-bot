"""Synthetic MT5 broker: no real account and no live trading APIs."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.execution.demo_order_firewall import (
    DemoSafetyError, execute_one_demo_smoke, initialize_broker_pin,
)
from src.execution.demo_reconciliation import audit_demo_smoke
from src.execution import demo_order_firewall

NOW = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)


def test_future_quote_after_durable_reservation_blocks_send(tmp_path, monkeypatch):
    api = FakeDemoMT5()
    kwargs = _setup(tmp_path, api)
    reserve = demo_order_firewall._reserve_intent

    def reserve_then_change_clock(*args):
        reserve(*args)
        api.quote_age = -7200

    monkeypatch.setattr(demo_order_firewall, "_reserve_intent", reserve_then_change_clock)
    with pytest.raises(DemoSafetyError, match="future-dated"):
        execute_one_demo_smoke(api, execute=True, **kwargs)
    assert api.sent == []
    with sqlite3.connect(kwargs["ledger_path"]) as connection:
        assert connection.execute("SELECT status FROM smoke_intents").fetchone() == (
            "ATTEMPT_RESERVED",
        )


def test_failed_sqlite_commit_cannot_send(tmp_path, monkeypatch):
    api = FakeDemoMT5()
    kwargs = _setup(tmp_path, api)
    connect = sqlite3.connect

    class FailingCommit(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql == "COMMIT":
                raise sqlite3.OperationalError("simulated SQLite commit failure")
            return super().execute(sql, parameters)

    monkeypatch.setattr(
        demo_order_firewall.sqlite3, "connect",
        lambda *args, **opts: connect(*args, **opts, factory=FailingCommit),
    )
    with pytest.raises(sqlite3.OperationalError, match="simulated SQLite commit"):
        execute_one_demo_smoke(api, execute=True, **kwargs)
    assert api.sent == []
    with connect(kwargs["ledger_path"]) as connection:
        assert connection.execute("SELECT count(*) FROM smoke_intents").fetchone() == (0,)


@pytest.mark.parametrize("scenario, expected", [
    ("closed", "CLOSURE_EVIDENCE"),
    ("open", "OPEN_EXPOSURE"),
    ("pending", "PENDING_EXPOSURE"),
    ("missing_close", "UNVERIFIED"),
    ("wrong_magic", "UNVERIFIED"),
    ("working_order", "UNVERIFIED"),
])
def test_audit_matches_receipt_and_keeps_ledger_locked(tmp_path, scenario, expected):
    api = FakeDemoMT5()
    kwargs = _setup(tmp_path, api)
    api.result = SimpleNamespace(retcode=api.TRADE_RETCODE_DONE, order=10, deal=11)
    execute_one_demo_smoke(api, execute=True, **kwargs)
    api.DEAL_ENTRY_IN, api.DEAL_ENTRY_OUT = 0, 1
    api.DEAL_TYPE_BUY, api.DEAL_TYPE_SELL = 0, 1
    api.ORDER_STATE_FILLED, api.ORDER_STATE_CANCELED, api.ORDER_STATE_EXPIRED = 4, 2, 6
    order = SimpleNamespace(ticket=10, symbol="EURUSD", magic=830117, state=4)
    fill = SimpleNamespace(ticket=11, order=10, position_id=12, symbol="EURUSD",
                           magic=830117, entry=0, type=0, volume=0.01)
    close = SimpleNamespace(ticket=13, position_id=12, symbol="EURUSD",
                            entry=1, type=1, volume=0.01)
    api.history_orders_get = lambda ticket: (order,) if ticket == 10 else ()
    api.history_deals_get = lambda ticket=None, position=None: (
        (fill,) if ticket == 10 or scenario == "missing_close"
        else (fill, close) if position == 12 else ()
    )
    if scenario == "open":
        api.exposures = (SimpleNamespace(identifier=12),)
    if scenario == "pending":
        api.pending = (SimpleNamespace(ticket=10, position_id=12),)
    if scenario == "wrong_magic":
        order.magic = 0
    if scenario == "working_order":
        order.state = 1
    ledger = kwargs["ledger_path"]
    before = ledger.read_bytes()
    result = audit_demo_smoke(api, pin_path=kwargs["pin_path"], ledger_path=ledger)
    assert result["status"] == expected
    assert result["execution_locked"] is True
    assert ledger.read_bytes() == before
    assert len(api.sent) == 1


def test_ledger_blocks_a_new_process_on_a_later_day(tmp_path):
    api = FakeDemoMT5()
    kwargs = _setup(tmp_path, api)
    execute_one_demo_smoke(api, execute=True, **kwargs)
    child = subprocess.run(
        [sys.executable, "-c", """
from pathlib import Path
import sys
from src.execution.demo_order_firewall import DemoSafetyError, _reserve_intent
try:
    _reserve_intent(Path(sys.argv[1]), "different-digest", "2026-11-06",
                    "2026-11-06T14:00:00+00:00")
except DemoSafetyError as exc:
    if "requires verified broker reconciliation" not in str(exc):
        raise
else:
    raise SystemExit("Durable guard allowed a second reservation")
""", str(kwargs["ledger_path"])],
        capture_output=True, text=True, timeout=20,
    )
    assert child.returncode == 0, child.stderr


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
        self.other_symbol_exposures = ()
        self.other_symbol_pending = ()
        self.exposure_appears_during_check = False
        self.trade_allowed = True
        self.quote_age = 0
        self.tick_epoch = NOW.timestamp()
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
                               time=int(self.tick_epoch-self.quote_age),
                               time_msc=int((self.tick_epoch-self.quote_age)*1000))

    def positions_get(self, symbol=None):
        if symbol == "EURUSD":
            return self.exposures
        assert symbol is None, "Safety check must use account-wide MT5 read"
        return self.exposures + self.other_symbol_exposures

    def orders_get(self, symbol=None):
        if symbol == "EURUSD":
            return self.pending
        assert symbol is None, "Safety check must use account-wide MT5 read"
        return self.pending + self.other_symbol_pending

    def order_calc_profit(self, side, symbol, volume, entry, stop):
        return (stop - entry) * 100000 * volume

    def order_calc_margin(self, side, symbol, volume, entry):
        return volume * 1000

    def order_check(self, request):
        if self.exposure_appears_during_check:
            self.other_symbol_pending = (object(),)
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
    with pytest.raises(DemoSafetyError, match="reconciliation"):
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
    with pytest.raises(DemoSafetyError, match="reconciliation"):
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
    with pytest.raises(DemoSafetyError, match="reconciliation"):
        execute_one_demo_smoke(api, execute=True, **kw)


def test_refuses_silent_repin_even_same_account(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    with pytest.raises(DemoSafetyError, match="already pinned"):
        initialize_broker_pin(api, kw["pin_path"])


@pytest.mark.parametrize("status", [
    "ATTEMPT_RESERVED",
    "UNKNOWN_BROKER_OUTCOME",
    "DEMO_PARTIAL_FILL_RECONCILE",
    "DEMO_ORDER_OUTCOME_RECONCILE",
    "DEMO_ORDER_FILLED",
])
def test_previous_unreconciled_attempt_stops_next_day(tmp_path, status):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    con = sqlite3.connect(kw["ledger_path"])
    con.execute(
        "CREATE TABLE smoke_intents ("
        "account_digest TEXT NOT NULL, day_utc TEXT NOT NULL,"
        "symbol TEXT NOT NULL, sent_at TEXT NOT NULL, status TEXT NOT NULL,"
        "retcode INTEGER, PRIMARY KEY(account_digest,day_utc,symbol))"
    )
    con.execute(
        "INSERT INTO smoke_intents VALUES (?, ?, ?, ?, ?, ?)",
        ("old-digest", "2026-11-04", "EURUSD",
         "2026-11-04T15:00:00+00:00", status, None)
    )
    con.commit()
    con.close()
    with pytest.raises(DemoSafetyError, match="reconciliation"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert api.sent == []


@pytest.mark.parametrize("kind", ["other_position", "other_order"])
def test_other_market_exposure_blocks_demo_smoke(tmp_path, kind):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    if kind == "other_position":
        api.other_symbol_exposures = (object(),)
    else:
        api.other_symbol_pending = (object(),)
    with pytest.raises(DemoSafetyError, match="DEMO account has positions"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert api.sent == []


def test_other_symbol_order_appearing_after_preflight_blocks_send(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    api.exposure_appears_during_check = True
    with pytest.raises(DemoSafetyError, match="DEMO account has positions"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert api.sent == []


def test_previous_order_ledger_survives_restart_on_next_utc_day(tmp_path):
    api = FakeDemoMT5()
    kw = _setup(tmp_path, api)
    first = execute_one_demo_smoke(api, execute=True, **kw)
    assert first.status == "DEMO_ORDER_FILLED"
    # Treat a broker-reported DONE as an OPEN position until independently
    # reconciled; a calendar boundary cannot authorize another attempt.
    kw["utcnow"] = NOW + timedelta(days=1)
    api.tick_epoch = kw["utcnow"].timestamp()
    assert kw["utcnow"].weekday() <= 4
    with pytest.raises(DemoSafetyError, match="reconciliation"):
        execute_one_demo_smoke(api, execute=True, **kw)
    assert len(api.sent) == 1
