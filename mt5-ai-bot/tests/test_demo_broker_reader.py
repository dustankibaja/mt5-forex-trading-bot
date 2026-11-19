from types import SimpleNamespace as Row
from datetime import datetime, timezone

import pytest

from src.execution import demo_broker_reader as reader
from src.execution.demo_account_binding import create_local_binding, AccountBindingError
from src.execution.demo_intent_journal import DemoIntentJournal, IntentBlocked


@pytest.fixture
def session(monkeypatch, tmp_path):
    account = Row(login=42, server="fixture", balance=10000., equity=10000., trade_mode=0)
    terminal = Row(path="terminal", data_path="data", connected=True)
    api = Row(ACCOUNT_TRADE_MODE_DEMO=0, account_info=lambda:account, terminal_info=lambda:terminal,
              positions_get=lambda:(), orders_get=lambda:(), history_deals_get=lambda start,end:(),
              history_orders_get=lambda start,end:(), DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1,
              DEAL_ENTRY_OUT=1)
    monkeypatch.setattr(reader, "mt5", api)
    pin = tmp_path / "pin"
    create_local_binding(api, pin)
    return reader.PinnedBrokerReader(pin), api


def test_baseline_and_observed_peak_survive_restart(session, tmp_path):
    adapter, api = session
    path = tmp_path / "ledger"
    for equity in (10000., 11000., 9000.):
        journal = DemoIntentJournal(path)
        api.account_info().equity = equity
        adapter.record_equity(journal)
        journal.close()
    journal = DemoIntentJournal(path)
    assert journal.db.execute("SELECT first_equity,peak_equity FROM observed_equity").fetchall() == [(10000.,11000.)]
    journal.close()


def test_missing_exposure_disconnect_and_switch_block(session):
    adapter, api = session
    api.positions_get = lambda:None
    with pytest.raises(IntentBlocked): adapter.observe()
    api.terminal_info().connected = False
    with pytest.raises(IntentBlocked): adapter.observe()
    api.account_info().login += 1
    with pytest.raises(AccountBindingError): adapter.observe()


def test_partial_volume_change_same_position_ticket_blocks(session):
    adapter, api = session
    snapshots = iter([(Row(ticket=7, symbol="EURUSD", type=0, volume=v),)
                      for v in (.02, .01)])
    api.positions_get = lambda: next(snapshots)
    with pytest.raises(IntentBlocked, match="Exposure changed"):
        adapter.observe()


def test_account_switch_during_exposure_read_blocks(session):
    adapter, api = session
    def switch():
        api.account_info().login = 999
        return ()
    api.orders_get = switch
    with pytest.raises(AccountBindingError):
        adapter.observe()


@pytest.mark.parametrize("history,reason", [
    (None, "unavailable"), ((), "unverified"),
    ((Row(type=2, profit=500),), "adjustment"), ((Row(type=2, profit=-500),), "adjustment"),
])
def test_history_never_promotes_midday_baseline(session, tmp_path, history, reason):
    adapter, api = session
    api.history_deals_get = lambda start,end: history
    journal = DemoIntentJournal(tmp_path / "ledger")
    adapter.record_equity(journal)
    assert reason in journal.db.execute("SELECT reason FROM risk_coverage").fetchone()[0]
    expected = "INCOMPLETE" if history == () else "INVALIDATED"
    assert journal.db.execute("SELECT status FROM risk_samples").fetchone() == (expected,)
    journal.close()


def test_restarted_reader_invalidates_same_day(session, tmp_path):
    adapter, _ = session
    journal = DemoIntentJournal(tmp_path / "ledger")
    adapter.record_equity(journal)
    reader.PinnedBrokerReader(adapter.binding_path).record_equity(journal)
    assert journal.db.execute("SELECT status FROM risk_samples ORDER BY id").fetchall() == [
        ("INCOMPLETE",), ("INVALIDATED",)]
    journal.close()


def test_history_reconciliation_reports_partial_fill_from_linked_deals(session):
    adapter, api = session
    api.history_orders_get = lambda start,end: (Row(ticket=11, symbol="EURUSD", type=0,
        volume_initial=.02, time_setup_msc=1000),)
    api.history_deals_get = lambda start,end: (Row(ticket=12, order=11, position_id=13,
        symbol="EURUSD", type=0, volume=.01, time_msc=1100, entry=0),)
    result = adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0,
        requested_volume=.02, since_utc=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status == "PARTIAL"
    assert result.deal_tickets == (12,)


def test_empty_position_cannot_prove_closure_without_closing_deal(session):
    adapter, api = session
    api.history_orders_get = lambda start,end: (Row(ticket=11, symbol="EURUSD", type=0,
        volume_initial=.01, time_setup_msc=1000),)
    api.history_deals_get = lambda start,end: (Row(ticket=12, order=11, position_id=13,
        symbol="EURUSD", type=0, volume=.01, time_msc=1100, entry=0),)
    with pytest.raises(IntentBlocked, match="Closure"):
        adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0,
            requested_volume=.01, since_utc=datetime(2026,1,1,tzinfo=timezone.utc))


def test_closure_needs_matching_exit_volume(session):
    adapter, api = session
    api.history_orders_get = lambda start,end: (Row(ticket=11, symbol="EURUSD", type=0,
        volume_initial=.01, time_setup_msc=1000),)
    api.history_deals_get = lambda start,end: (
        Row(ticket=12, order=11, position_id=13, symbol="EURUSD", type=0, volume=.01, time_msc=1100, entry=0),
        Row(ticket=14, order=99, position_id=13, symbol="EURUSD", type=1, volume=.01, time_msc=1200, entry=1),)
    result = adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0,
        requested_volume=.01, since_utc=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status == "CLOSED"
