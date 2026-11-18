import pytest
from src.execution.demo_intent_journal import DemoIntentJournal,IntentBlocked,canonical_intent_id


def plan(**changes):
    value={"binding_id":"abc","symbol":"EURUSD","side":"buy","volume":.01,"sl":1.09,"tp":1.12,"strategy_hash":"s","signal_id":"x"};value.update(changes);return value


def test_duplicate_and_crash_unknown_outcome_never_retry(tmp_path):
    journal=DemoIntentJournal(tmp_path/"journal.sqlite3");intent=plan()
    key=journal.reserve(intent,created_utc="2026-01-01T00:00:00Z",risk_pct=.25,daily_loss_pct=0,drawdown_pct=0,open_positions=0,pending_orders=0)
    assert key==canonical_intent_id(intent)
    journal.transition(key,"SEND_STARTED")
    with pytest.raises(IntentBlocked,match="Duplicate"):
        journal.reserve(intent,created_utc="2026-01-01T00:01:00Z",risk_pct=.25,daily_loss_pct=0,drawdown_pct=0,open_positions=0,pending_orders=0)
    journal.close();reopened=DemoIntentJournal(tmp_path/"journal.sqlite3")
    assert reopened.unreconciled()[0]["status"]=="SEND_STARTED"


@pytest.mark.parametrize("kwargs,message",[
    ({"risk_pct":.26},"0.25"),({"daily_loss_pct":2},"circuit"),({"drawdown_pct":5},"circuit"),({"open_positions":1},"exposure")])
def test_risk_and_account_wide_circuit_breakers(tmp_path,kwargs,message):
    journal=DemoIntentJournal(tmp_path/(message+".sqlite3"));base=dict(created_utc="2026-01-01T00:00:00Z",risk_pct=.25,daily_loss_pct=0,drawdown_pct=0,open_positions=0,pending_orders=0);base.update(kwargs)
    with pytest.raises(IntentBlocked,match=message):journal.reserve(plan(),**base)


def test_emergency_stop_partial_fill_and_final_reconciliation(tmp_path):
    journal=DemoIntentJournal(tmp_path/"journal.sqlite3");journal.set_emergency_stop(True)
    with pytest.raises(IntentBlocked,match="Emergency"):journal.reserve(plan(),created_utc="x",risk_pct=.25,daily_loss_pct=0,drawdown_pct=0,open_positions=0,pending_orders=0)
    journal.set_emergency_stop(False);key=journal.reserve(plan(),created_utc="x",risk_pct=.25,daily_loss_pct=0,drawdown_pct=0,open_positions=0,pending_orders=0)
    journal.transition(key,"PARTIAL",broker_order=7,broker_deal=8);assert journal.unreconciled()
    journal.transition(key,"CLOSED_RECONCILED",broker_order=7,broker_deal=8);assert journal.unreconciled()==[]
    with pytest.raises(IntentBlocked,match="Final"):journal.transition(key,"CHECKED")
