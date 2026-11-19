from types import SimpleNamespace

from src.execution.quote_time_certification import (
    BrokerTimestampSemantics, QuoteTimeCertifier, QuoteTimeState, UtcEvidence,
)


def evidence(*, utc=1000., mono=10, expires=20, uncertainty=.05):
    return UtcEvidence("independent-ntp-measurement", utc, uncertainty, mono, expires)


SEMANTICS = BrokerTimestampSemantics("MetaQuotes-Demo", "UTC_EPOCH_SECONDS", "validated-probe-1")


def tick(milliseconds):
    return SimpleNamespace(time=milliseconds // 1000, time_msc=milliseconds)


def test_missing_evidence_and_unknown_semantics_never_certify():
    certifier = QuoteTimeCertifier()
    assert certifier.assess(tick(999_900), utc=None, semantics=None).state == QuoteTimeState.UNCERTIFIED
    unknown = BrokerTimestampSemantics("MetaQuotes-Demo", "UNKNOWN", "raw-only")
    assert certifier.assess(tick(999_900), utc=evidence(), semantics=unknown).state == QuoteTimeState.UNCERTIFIED


def test_new_quote_can_certify_only_with_bounded_evidence():
    certifier = QuoteTimeCertifier()
    result = certifier.assess(tick(999_900), utc=evidence(), semantics=SEMANTICS)
    assert result.state == QuoteTimeState.CERTIFIED
    assert result.raw_provider_milliseconds == 999_900


def test_cached_quote_expired_evidence_and_clock_rollback_fail_closed():
    certifier = QuoteTimeCertifier()
    assert certifier.assess(tick(999_900), utc=evidence(), semantics=SEMANTICS).state == QuoteTimeState.CERTIFIED
    assert certifier.assess(tick(999_900), utc=evidence(utc=1001, mono=11), semantics=SEMANTICS).state == QuoteTimeState.UNCERTIFIED
    assert certifier.assess(tick(1_000_900), utc=evidence(utc=999, mono=12), semantics=SEMANTICS).state == QuoteTimeState.REVOKED
    assert certifier.assess(tick(1_001_000), utc=evidence(utc=1002, mono=13), semantics=SEMANTICS).state == QuoteTimeState.REVOKED


def test_expired_or_excessive_uncertainty_evidence_never_certifies():
    assert QuoteTimeCertifier().assess(tick(999_900), utc=evidence(mono=21), semantics=SEMANTICS).state == QuoteTimeState.UNCERTIFIED
    assert QuoteTimeCertifier().assess(tick(999_900), utc=evidence(uncertainty=.3), semantics=SEMANTICS).state == QuoteTimeState.UNCERTIFIED
