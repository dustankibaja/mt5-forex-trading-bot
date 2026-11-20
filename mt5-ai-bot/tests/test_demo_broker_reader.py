from types import SimpleNamespace as Row
from datetime import datetime, timedelta, timezone

import pytest

from src.execution import demo_broker_reader as reader
from src.execution.demo_account_binding import create_local_binding, AccountBindingError
from src.execution.demo_intent_journal import DemoIntentJournal, IntentBlocked
from src.execution.quote_time_certification import _verified_utc_evidence


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
    snapshots = iter([(Row(ticket=7, identifier=7, symbol="EURUSD", type=0, volume=v),)
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


def test_risk_recording_requires_controlled_utc_evidence(session, tmp_path, monkeypatch):
    adapter, _ = session
    journal = DemoIntentJournal(tmp_path / "ledger")
    adapter.record_equity(journal)
    assert "certified UTC" in journal.db.execute("SELECT reason FROM risk_coverage").fetchone()[0]
    journal.close()


def test_controlled_utc_evidence_is_bound_to_the_verified_account(session, tmp_path, monkeypatch):
    adapter, _ = session
    journal = DemoIntentJournal(tmp_path / "ledger")
    now = 10_000
    monkeypatch.setattr(reader.time, "monotonic_ns", lambda: now)
    evidence = _verified_utc_evidence(
        source="fixture-authority", utc_seconds=1_000., uncertainty_seconds=.05,
        monotonic_ns=now, expires_monotonic_ns=now + 1_000,
        account_binding="wrong-binding", host_identity="fixture-host", source_identity="fixture-source",
        sync_epoch="fixture-epoch", observation_sequence=1,
    )
    adapter.record_equity(journal, utc_evidence=evidence)
    assert "certified UTC" in journal.db.execute("SELECT reason FROM risk_coverage").fetchone()[0]
    journal.close()


def test_expired_utc_evidence_leaves_risk_record_incomplete(session, tmp_path, monkeypatch):
    adapter, _ = session
    journal = DemoIntentJournal(tmp_path / "ledger")
    now = 10_000
    monkeypatch.setattr(reader.time, "monotonic_ns", lambda: now)
    evidence = _verified_utc_evidence(
        source="fixture-authority", utc_seconds=1_000., uncertainty_seconds=.05,
        monotonic_ns=now - 2, expires_monotonic_ns=now - 1,
        account_binding=adapter._identity(), host_identity="fixture-host", source_identity="fixture-source",
        sync_epoch="fixture-epoch", observation_sequence=1,
    )
    adapter.record_equity(journal, utc_evidence=evidence)
    assert journal.db.execute("SELECT status FROM risk_samples").fetchone() == ("INCOMPLETE",)
    journal.close()


def _observation(binding="binding", received=None, monotonic=2_000_000_000):
    return reader.AccountObservation(
        binding, received or datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        monotonic, 10_000., 10_000., (), (),
    )


def _prior(status="INCOMPLETE", reason="baseline incomplete"):
    return ("binding", "2026-01-01", "session", "2026-01-01T00:00:00+00:00",
            1_000_000_000, status, reason)


def test_two_same_day_samples_without_utc_never_promote_to_observing():
    first_status, _ = reader._next_risk_status(_prior(), _observation(), "session", False, "unused")
    second_prior = _prior(status=first_status)
    second_status, _ = reader._next_risk_status(second_prior, _observation(monotonic=3_000_000_000),
                                                 "session", False, "unused")
    assert (first_status, second_status) == ("INCOMPLETE", "INCOMPLETE")


def test_trusted_observation_followed_by_missing_utc_invalidates_continuity():
    status, _ = reader._next_risk_status(_prior(status="OBSERVING"), _observation(), "session", False, "unused")
    assert status == "INVALIDATED"


def test_valid_account_bound_utc_continuity_can_only_observe_not_qualify():
    status, _ = reader._next_risk_status(_prior(), _observation(), "session", True, "baseline incomplete")
    assert status == "OBSERVING"


def test_existing_invalidation_is_preserved_even_with_trusted_utc():
    status, reason = reader._next_risk_status(_prior(status="INVALIDATED", reason="history missing"),
                                               _observation(), "session", True, "unused")
    assert (status, reason) == ("INVALIDATED", "history missing")


def test_reader_restart_invalidates_even_when_utc_evidence_is_missing():
    status, reason = reader._next_risk_status(_prior(), _observation(), "new-session", False, "unused")
    assert (status, reason) == ("INVALIDATED", "Observation continuity lost")


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
    assert result.timestamp_semantics == "UNVERIFIED_PROVIDER_CLOCK"


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


def test_open_reconciliation_captures_broker_protective_state(session):
    adapter, api = session
    api.history_orders_get = lambda start,end: (Row(ticket=11, symbol="EURUSD", type=0,
        volume_initial=.01, time_setup_msc=1000),)
    api.history_deals_get = lambda start,end: (Row(ticket=12, order=11, position_id=13,
        symbol="EURUSD", type=0, volume=.01, time_msc=1100, entry=0),)
    api.positions_get = lambda: (Row(ticket=13, identifier=13, symbol="EURUSD", type=0, volume=.01,
                                     sl=1.05, tp=1.15),)
    result = adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0,
        requested_volume=.01, since_utc=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status == "OPEN"
    assert result.position_protection == ((13, 1.05, 1.15),)


def test_invalid_protective_state_or_non_utc_start_blocks(session):
    adapter, api = session
    api.positions_get = lambda: (Row(ticket=13, identifier=13, symbol="EURUSD", type=0, volume=.01,
                                     sl=float("nan"), tp=0.0),)
    with pytest.raises(IntentBlocked, match="exposure"):
        adapter.observe()
    with pytest.raises(IntentBlocked, match="explicitly UTC"):
        adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0, requested_volume=.01,
            since_utc=datetime(2026,1,1,tzinfo=timezone(timedelta(hours=3))))


def test_hedging_reconciliation_ignores_same_symbol_unrelated_position(session):
    adapter, api = session
    api.history_orders_get = lambda start,end: (Row(ticket=11, symbol="EURUSD", type=0,
        volume_initial=.01, time_setup_msc=1000, position_id=13),)
    api.history_deals_get = lambda start,end: (
        Row(ticket=12, order=11, position_id=13, symbol="EURUSD", type=0, volume=.01, time_msc=1100, entry=0),
        Row(ticket=14, order=99, position_id=13, symbol="EURUSD", type=1, volume=.01, time_msc=1200, entry=1),)
    api.positions_get = lambda: (Row(ticket=40, identifier=40, symbol="EURUSD", type=0,
                                     volume=.03, sl=0., tp=0.),)
    result = adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0,
        requested_volume=.01, since_utc=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status == "CLOSED"
    assert result.position_tickets == ()


def test_multiple_closing_deals_are_required_to_cover_full_fill(session):
    adapter, api = session
    api.history_orders_get = lambda start,end: (Row(ticket=11, symbol="EURUSD", type=0,
        volume_initial=.02, time_setup_msc=1000, position_id=13),)
    api.history_deals_get = lambda start,end: (
        Row(ticket=12, order=11, position_id=13, symbol="EURUSD", type=0, volume=.02, time_msc=1100, entry=0),
        Row(ticket=14, order=99, position_id=13, symbol="EURUSD", type=1, volume=.01, time_msc=1200, entry=1),
        Row(ticket=15, order=100, position_id=13, symbol="EURUSD", type=1, volume=.01, time_msc=1300, entry=1),)
    result = adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0,
        requested_volume=.02, since_utc=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status == "CLOSED"


def test_netting_reversal_needs_closing_deal_not_opposite_position_inference(session):
    adapter, api = session
    api.history_orders_get = lambda start,end: (Row(ticket=11, symbol="EURUSD", type=0,
        volume_initial=.01, time_setup_msc=1000, position_id=13),)
    api.history_deals_get = lambda start,end: (
        Row(ticket=12, order=11, position_id=13, symbol="EURUSD", type=0, volume=.01, time_msc=1100, entry=0),
        Row(ticket=14, order=99, position_id=13, symbol="EURUSD", type=1, volume=.01, time_msc=1200, entry=1),)
    api.positions_get = lambda: (Row(ticket=13, identifier=13, symbol="EURUSD", type=1,
                                     volume=.02, sl=1.2, tp=1.0),)
    result = adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0,
        requested_volume=.01, since_utc=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status == "CLOSED"
    assert result.current_position_volume == 0


def test_session_switch_during_reconciliation_blocks(session):
    adapter, api = session
    api.history_orders_get = lambda start,end: (Row(ticket=11, symbol="EURUSD", type=0,
        volume_initial=.01, time_setup_msc=1000),)
    def switch(start, end):
        api.account_info().login = 999
        return ()
    api.history_deals_get = switch
    with pytest.raises(AccountBindingError):
        adapter.reconcile_order(order_ticket=11, symbol="EURUSD", side=0,
            requested_volume=.01, since_utc=datetime(2026,1,1,tzinfo=timezone.utc))
