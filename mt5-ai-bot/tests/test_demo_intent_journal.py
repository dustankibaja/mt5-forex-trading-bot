from concurrent.futures import ThreadPoolExecutor

import pytest

from src.execution.demo_intent_journal import DemoIntentJournal as ProductionJournal, IntentBlocked, canonical_intent_id


class DemoIntentJournal(ProductionJournal):
    """Exercise storage transitions only against pytest's temporary database."""
    reserve = ProductionJournal._record_reservation
    transition = ProductionJournal._record_transition


def test_public_journal_rejects_self_attested_broker_and_risk_records(tmp_path):
    journal = ProductionJournal(tmp_path / "production.sqlite3")
    try:
        with pytest.raises(IntentBlocked, match="internally measured"):
            reserve(journal)
        with pytest.raises(IntentBlocked, match="prohibited"):
            move(journal, "invented", "CLOSED_RECONCILED", broker_order=1,
                 evidence_source="mt5-broker-history", evidence={"closed": True})
        assert journal.unreconciled() == []
    finally:
        journal.close()


def plan(**changes):
    value = {"binding_id":"bound-demo","symbol":"EURUSD","side":"buy","volume":.01,
             "sl":1.10,"tp":1.12,"strategy_hash":"s","signal_id":"x"}
    value.update(changes); return value


def risk(**changes):
    value = {"source":"deterministic-broker-fixture","captured_utc":"2026-01-01T00:00:00Z",
             "balance":10000,"equity":10000,"daily_start_balance":10000,
             "high_water_equity":10000,"open_positions":0,"pending_orders":0}
    value.update(changes); return value


def reserve(journal, intent=None, **kwargs):
    return journal.reserve(intent or plan(), created_utc="2026-01-01T00:00:00Z",
                           risk_pct=.25, risk_evidence=risk(), **kwargs)


def move(journal, key, status, **kwargs):
    defaults = dict(recorded_utc="2026-01-01T00:00:01Z",
                    evidence_source="deterministic-broker-fixture", evidence={"retcode":0})
    defaults.update(kwargs); journal.transition(key, status, **defaults)


def test_explicit_graph_blocks_skips_reversals_and_duplicate_send(tmp_path):
    journal=DemoIntentJournal(tmp_path/"journal.sqlite3"); key=reserve(journal)
    with pytest.raises(IntentBlocked, match="RESERVED -> SEND_STARTED"): move(journal,key,"SEND_STARTED")
    move(journal,key,"CHECKED")
    move(journal,key,"SEND_STARTED",evidence_source="local-send-boundary",evidence={})
    with pytest.raises(IntentBlocked, match="SEND_STARTED -> SEND_STARTED"):
        move(journal,key,"SEND_STARTED",evidence_source="local-send-boundary",evidence={})
    move(journal,key,"UNKNOWN")
    with pytest.raises(IntentBlocked, match="UNKNOWN -> CHECKED"): move(journal,key,"CHECKED")


def test_final_reconciliation_requires_broker_identity_and_evidence(tmp_path):
    journal=DemoIntentJournal(tmp_path/"journal.sqlite3"); key=reserve(journal)
    move(journal,key,"CHECKED"); move(journal,key,"SEND_STARTED",evidence_source="local-send-boundary",evidence={})
    with pytest.raises(IntentBlocked, match="identity"): move(journal,key,"PARTIAL")
    move(journal,key,"PARTIAL",broker_order=7,broker_deal=8)
    with pytest.raises(IntentBlocked, match="Broker evidence"):
        journal.transition(key,"CLOSED_RECONCILED",recorded_utc="x",evidence_source="caller-claim",evidence={"closed":True},broker_order=7)
    move(journal,key,"CLOSED_RECONCILED",broker_order=7,broker_deal=9)
    assert journal.unreconciled()==[]
    assert [row["to_status"] for row in journal.audit(key)] == ["RESERVED","CHECKED","SEND_STARTED","PARTIAL","CLOSED_RECONCILED"]


@pytest.mark.parametrize("changes,message",[
    ({"equity":9799},"circuit"),({"equity":9499,"daily_start_balance":9500},"circuit"),
    ({"source":"caller"},"Untrusted"),({"open_positions":-1},"exposure")])
def test_risk_metrics_require_verifiable_evidence(tmp_path,changes,message):
    journal=DemoIntentJournal(tmp_path/"journal.sqlite3")
    with pytest.raises(IntentBlocked,match=message):
        journal.reserve(plan(),created_utc="x",risk_pct=.25,risk_evidence=risk(**changes))


def test_emergency_stop_and_binding_change_races_fail_closed(tmp_path):
    journal=DemoIntentJournal(tmp_path/"journal.sqlite3"); key=reserve(journal)
    journal.set_emergency_stop(True,recorded_utc="2026-01-01T00:00:01Z")
    with pytest.raises(IntentBlocked,match="Emergency"): move(journal,key,"CHECKED")
    journal.set_emergency_stop(False)
    with pytest.raises(IntentBlocked,match="binding changed"): move(journal,key,"CHECKED",expected_binding_id="different")


def test_concurrent_reservations_respect_account_exposure_limit(tmp_path):
    path=tmp_path/"journal.sqlite3"
    def attempt(index):
        journal=DemoIntentJournal(path)
        try: return reserve(journal,plan(signal_id=str(index)))
        except IntentBlocked: return None
        finally: journal.close()
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt,range(2)))
    assert sum(value is not None for value in results)==1


@pytest.mark.parametrize("cut",["RESERVED","CHECKED","SEND_STARTED","UNKNOWN","PARTIAL","ACCEPTED"])
def test_restart_preserves_every_critical_unreconciled_state(tmp_path,cut):
    path=tmp_path/f"{cut}.sqlite3"; journal=DemoIntentJournal(path); key=reserve(journal)
    sequence=[] if cut=="RESERVED" else (["CHECKED","SEND_STARTED","UNKNOWN"] if cut=="UNKNOWN" else ["CHECKED","SEND_STARTED","PARTIAL","ACCEPTED"])
    for state in sequence:
        if state in {"PARTIAL","ACCEPTED"}: move(journal,key,state,broker_order=7)
        elif state=="SEND_STARTED": move(journal,key,state,evidence_source="local-send-boundary",evidence={})
        else: move(journal,key,state)
        if state==cut: break
    journal.close(); reopened=DemoIntentJournal(path)
    assert reopened.unreconciled()[0]["status"]==cut


def test_duplicate_intent_is_never_reused_after_restart(tmp_path):
    path=tmp_path/"journal.sqlite3"; journal=DemoIntentJournal(path); intent=plan(); key=reserve(journal,intent)
    assert key==canonical_intent_id(intent); journal.close(); reopened=DemoIntentJournal(path)
    with pytest.raises(IntentBlocked,match="Duplicate"): reserve(reopened,intent,max_account_exposure=2)
