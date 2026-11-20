from types import SimpleNamespace

from src.execution.quote_time_certification import (
    BrokerTimestampSemantics, QuoteTimeCertifier, QuoteTimeState, UtcEvidence,
    _verified_broker_timestamp_semantics, _verified_utc_evidence,
)


def evidence(*, utc=1000., mono=10, expires=20, uncertainty=.05, sequence=1,
             account="demo-binding", source="utc-source", sync="sync-epoch-1"):
    return _verified_utc_evidence(
        source="independent-utc", utc_seconds=utc, uncertainty_seconds=uncertainty,
        monotonic_ns=mono, expires_monotonic_ns=expires, account_binding=account,
        source_identity=source, sync_epoch=sync, observation_sequence=sequence,
    )


def semantics(*, account="demo-binding", source="utc-source"):
    return _verified_broker_timestamp_semantics(
        provider="MetaQuotes-Demo", kind="UTC_EPOCH_SECONDS", evidence_id="validated-probe-1",
        account_binding=account, source_identity=source,
    )


def tick(milliseconds):
    return SimpleNamespace(time=milliseconds // 1000, time_msc=milliseconds)


def test_directly_constructed_labels_are_not_attestations():
    direct = UtcEvidence("independent-utc", 1000., .05, 10, 20, "demo-binding", "utc-source", "sync", 1)
    direct_semantics = BrokerTimestampSemantics("MetaQuotes-Demo", "UTC_EPOCH_SECONDS", "claim", "demo-binding", "utc-source")
    result = QuoteTimeCertifier(monotonic_clock_ns=lambda: 10).assess(tick(999_900), utc=direct, semantics=direct_semantics)
    assert result.state == QuoteTimeState.UNCERTIFIED


def test_new_certifier_requires_successive_controlled_observations():
    certifier = QuoteTimeCertifier(monotonic_clock_ns=iter((10, 11)).__next__)
    assert certifier.assess(tick(999_900), utc=evidence(sequence=1), semantics=semantics()).state == QuoteTimeState.UNCERTIFIED
    result = certifier.assess(tick(1_000_900), utc=evidence(utc=1001, mono=11, sequence=2), semantics=semantics())
    assert result.state == QuoteTimeState.CERTIFIED
    assert result.raw_provider_milliseconds == 1_000_900


def test_new_certifier_rejects_a_first_observation_with_a_skipped_sequence():
    result = QuoteTimeCertifier(monotonic_clock_ns=lambda: 10).assess(
        tick(999_900), utc=evidence(sequence=2), semantics=semantics())
    assert result.state == QuoteTimeState.UNCERTIFIED
    assert result.reason == "First UTC evidence observation must start at sequence one"


def test_invalid_numeric_evidence_fails_closed_without_throwing():
    result = QuoteTimeCertifier(monotonic_clock_ns=lambda: 10).assess(
        tick(999_900), utc=evidence(utc="not-a-number"), semantics=semantics())
    assert result.state == QuoteTimeState.UNCERTIFIED


def test_actual_monotonic_reading_expires_evidence():
    result = QuoteTimeCertifier(monotonic_clock_ns=lambda: 21).assess(
        tick(999_900), utc=evidence(expires=20), semantics=semantics())
    assert result.state == QuoteTimeState.UNCERTIFIED
    assert result.reason == "UTC evidence expired"


def test_cached_quote_and_continuity_change_fail_closed():
    certifier = QuoteTimeCertifier(monotonic_clock_ns=iter((10, 11, 12, 13)).__next__)
    certifier.assess(tick(999_900), utc=evidence(sequence=1), semantics=semantics())
    assert certifier.assess(tick(999_900), utc=evidence(utc=1001, mono=11, sequence=2), semantics=semantics()).state == QuoteTimeState.UNCERTIFIED
    assert certifier.assess(tick(1_001_900), utc=evidence(utc=1002, mono=12, sequence=4), semantics=semantics()).state == QuoteTimeState.REVOKED
    assert certifier.assess(tick(1_002_900), utc=evidence(utc=1003, mono=13, sequence=5), semantics=semantics()).state == QuoteTimeState.REVOKED


def test_rollback_and_binding_change_revoke_certification():
    certifier = QuoteTimeCertifier(monotonic_clock_ns=iter((10, 11, 12)).__next__)
    certifier.assess(tick(999_900), utc=evidence(sequence=1), semantics=semantics())
    assert certifier.assess(tick(1_000_900), utc=evidence(utc=1001, mono=11, sequence=2), semantics=semantics()).state == QuoteTimeState.CERTIFIED
    result = certifier.assess(tick(1_001_900), utc=evidence(utc=1002, mono=12, sequence=3, account="other"), semantics=semantics(account="other"))
    assert result.state == QuoteTimeState.REVOKED


def test_excessive_uncertainty_and_nonadvancing_monotonic_clock_never_certify():
    assert QuoteTimeCertifier(monotonic_clock_ns=lambda: 10).assess(
        tick(999_900), utc=evidence(uncertainty=.3), semantics=semantics()).state == QuoteTimeState.UNCERTIFIED
    certifier = QuoteTimeCertifier(monotonic_clock_ns=iter((10, 10)).__next__)
    certifier.assess(tick(999_900), utc=evidence(sequence=1), semantics=semantics())
    assert certifier.assess(tick(1_000_900), utc=evidence(utc=1001, mono=11, sequence=2), semantics=semantics()).state == QuoteTimeState.REVOKED
