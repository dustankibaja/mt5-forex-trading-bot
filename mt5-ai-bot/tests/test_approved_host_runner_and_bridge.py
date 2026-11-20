import sqlite3

import pytest

from src.execution.approved_host_runner import ApprovedHostCertificationRunner
from src.execution.approved_host_mt5_bridge import Mt5Build6327ReadOnlyBridge, RawMt5Tick
from src.execution.authenticated_utc_transport import ApprovedHostSignedUtcVerifier, AuthorityTimeAssertion
from src.execution.quote_time_certification import _verified_utc_evidence


def verifier():
    return ApprovedHostSignedUtcVerifier(
        host_identity="host", authority_keys={"authority": frozenset(("key",))},
        replay_db=sqlite3.connect(":memory:"),
        verify_detached=lambda key, payload, signature: key == "key" and signature == b"valid")


def evidence():
    return _verified_utc_evidence(source="signed", utc_seconds=1000.0, uncertainty_seconds=.01,
        monotonic_ns=10, expires_monotonic_ns=100, account_binding="demo", host_identity="host",
        source_identity="source-a|source-b", sync_epoch="epoch", observation_sequence=1)


def test_runner_requires_activation_and_never_declares_fixture_evidence_certified():
    checked = verifier()
    runner = ApprovedHostCertificationRunner(verifier=checked, host_identity="host", account_binding="demo",
                                             monotonic_clock_ns=lambda: 10)
    with pytest.raises(PermissionError):
        runner.issue(authority_id="authority", synchronization_epoch="epoch", ttl_ns=100)
    enabled = ApprovedHostCertificationRunner(verifier=checked, host_identity="host", account_binding="demo",
                                              operator_enabled=True, monotonic_clock_ns=lambda: 10)
    challenge = enabled.issue(authority_id="authority", synchronization_epoch="epoch", ttl_ns=100)
    assertion = AuthorityTimeAssertion("authority", "family", "key", "epoch", challenge.challenge,
                                       1000.0, .01, b"valid")
    result = enabled.collect(assertion, sent_monotonic_ns=10, received_monotonic_ns=20)
    assert result.transcript is not None
    assert not result.certified


def test_mt5_bridge_retains_raw_values_and_marks_only_repeated_raw_ticks_cached():
    bridge = Mt5Build6327ReadOnlyBridge(account_binding="demo", host_identity="host")
    raw = RawMt5Tick("demo", "host", "EURUSD", 1000, 1_000_001, 1000, 1_000_001, 1.1, 1.1001, 20)
    first = bridge.record(raw, evidence())
    repeated = bridge.record(raw, evidence())
    assert first.is_new_tick and not repeated.is_new_tick
    assert repeated.cached_reason
    with pytest.raises(ValueError):
        bridge.record(RawMt5Tick("other", "host", "EURUSD", 1000, 1_000_001, 1000, 1_000_001, 1.1, 1.1001, 20), evidence())
