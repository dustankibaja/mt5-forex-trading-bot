import sqlite3

import pytest

from src.execution.durable_certification_evidence import (
    DurableCertificationEvidence, RiskQualificationEvaluator,
    _verified_broker_history_evidence,
)
from src.execution.quote_time_certification import _verified_utc_evidence


def utc(sequence=1, utc_seconds=1_000., monotonic=10, expires=20):
    return _verified_utc_evidence(
        source="approved-authority", utc_seconds=utc_seconds, uncertainty_seconds=.05,
        monotonic_ns=monotonic, expires_monotonic_ns=expires,
        account_binding="binding", host_identity="host", source_identity="source-a|source-b",
        sync_epoch="epoch", observation_sequence=sequence)


def history(**overrides):
    values = dict(binding="binding", host_identity="host", synchronization_epoch="epoch",
                  complete=True, flat=True, no_external_activity=True,
                  no_cash_movements=True, connected_continuously=True)
    values.update(overrides)
    return _verified_broker_history_evidence(**values)


def test_append_only_ledger_preserves_raw_utc_and_mt5_fields():
    ledger = DurableCertificationEvidence(sqlite3.connect(":memory:"))
    ledger.append(binding="binding", utc=utc(), raw_mt5_time=999,
                  raw_mt5_time_msc=999_900, bid=1.1, ask=1.1001)
    ledger.append(binding="binding", utc=utc(2, 1_001., 11, 21),
                  raw_mt5_time=1_000, raw_mt5_time_msc=1_000_900, bid=1.2, ask=1.2001)
    rows = ledger.rows("binding")
    assert len(rows) == 2
    assert rows[0][9] == 1 and rows[1][9] == 2
    assert rows[0][10:14] == (999, 999_900, 1.1, 1.1001)


def test_ledger_rejects_untrusted_or_inconsistent_raw_evidence():
    ledger = DurableCertificationEvidence(sqlite3.connect(":memory:"))
    with pytest.raises(ValueError):
        ledger.append(binding="binding", utc=utc(), raw_mt5_time=1, raw_mt5_time_msc=999)


def test_evaluator_explains_history_and_continuity_failures():
    ledger = DurableCertificationEvidence(sqlite3.connect(":memory:"))
    ledger.append(binding="binding", utc=utc())
    rows = ledger.rows("binding")
    evaluator = RiskQualificationEvaluator()
    assert evaluator.evaluate(binding="binding", rows=rows, history=None).status == "INCOMPLETE"
    assert evaluator.evaluate(binding="binding", rows=rows, history=history()).status == "OBSERVING"
    assert evaluator.evaluate(binding="binding", rows=rows, history=history(no_cash_movements=False)).status == "INCOMPLETE"


def test_evaluator_never_qualifies_incomplete_or_interrupted_evidence():
    ledger = DurableCertificationEvidence(sqlite3.connect(":memory:"))
    ledger.append(binding="binding", utc=utc(1, 86_399., 10, 20))
    ledger.append(binding="binding", utc=utc(3, 86_401., 11, 21))
    decision = RiskQualificationEvaluator().evaluate(
        binding="binding", rows=ledger.rows("binding"), history=history())
    assert decision.status == "INCOMPLETE"
    assert "interrupted" in decision.reason
