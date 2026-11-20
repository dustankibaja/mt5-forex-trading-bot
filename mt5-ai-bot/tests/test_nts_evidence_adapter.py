from src.execution.nts_evidence_adapter import NtsEvidenceAdapter, _authenticated_nts_measurement


def measurement(authority, family, **overrides):
    values = dict(authority_id=authority, source_family=family, certificate_identity=f"cert-{authority}",
                  host_identity="host", account_binding="demo", synchronization_epoch="epoch",
                  request_monotonic_ns=10, receipt_monotonic_ns=20, utc_seconds=1000.0,
                  uncertainty_seconds=.01, expires_monotonic_ns=100, sequence=1)
    values.update(overrides)
    return _authenticated_nts_measurement(**values)


def test_two_authenticated_independent_nts_sources_create_only_a_noncertifying_candidate():
    adapter = NtsEvidenceAdapter(host_identity="host", account_binding="demo")
    result = adapter.assess((measurement("cloudflare", "cloudflare"), measurement("netnod", "netnod")), now_monotonic_ns=30)
    assert result.accepted and not result.certified
    assert result.bounded_utc_low < 1000 < result.bounded_utc_high


def test_nts_adapter_rejects_source_disagreement_stale_epochs_and_identity_mismatch():
    adapter = NtsEvidenceAdapter(host_identity="host", account_binding="demo")
    assert not adapter.assess((measurement("a", "one"), measurement("b", "two", utc_seconds=1001)), now_monotonic_ns=30).accepted
    assert not adapter.assess((measurement("a", "one", expires_monotonic_ns=25), measurement("b", "two", expires_monotonic_ns=25)), now_monotonic_ns=30).accepted
    assert not adapter.assess((measurement("a", "one"), measurement("b", "two", host_identity="other")), now_monotonic_ns=30).accepted


def test_nts_adapter_rejects_replay_and_monotonic_discontinuity():
    adapter = NtsEvidenceAdapter(host_identity="host", account_binding="demo")
    first = (measurement("a", "one"), measurement("b", "two"))
    assert adapter.assess(first, now_monotonic_ns=30).accepted
    assert not adapter.assess(first, now_monotonic_ns=30).accepted
