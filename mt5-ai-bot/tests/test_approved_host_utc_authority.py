from src.execution.approved_host_utc_authority import (
    ApprovedHostUtcAuthorityAdapter, AuthenticatedReferenceSet,
    _authenticated_reference_set,
)
from src.research.calibrated_clock import ReferenceObservation, calibrate


def references(**overrides):
    calibration = calibrate([
        ReferenceObservation("a", "family-a", 1_000, 10_000, 10, 10, 1),
        ReferenceObservation("b", "family-b", 1_000, 10_000, 11, 10, 1),
    ], maximum_age_ms=60_000, drift_bound_ppm=10)
    values = dict(authority_id="approved-authority", host_identity="host-1",
                  source_fingerprints=("fp-a", "fp-b"), synchronization_epoch="epoch-1",
                  calibration=calibration)
    values.update(overrides)
    return _authenticated_reference_set(**values)


def adapter():
    return ApprovedHostUtcAuthorityAdapter(
        host_identity="host-1", approved_authorities=frozenset(("approved-authority",)),
        approved_source_fingerprints=frozenset(("fp-a", "fp-b")),
    )


def test_approved_host_measurement_contains_bounded_utc_and_host_identity():
    result = adapter().measure(references(), monotonic_ns=1_000_000_000)
    assert result is not None
    assert result.host_identity == "host-1"
    assert result.uncertainty_seconds <= .25


def test_invalid_host_or_untrusted_reference_record_never_measures():
    assert adapter().measure(references(host_identity="other"), monotonic_ns=1_000_000_000) is None
    direct = AuthenticatedReferenceSet("approved-authority", "host-1", ("fp-a", "fp-b"), (),
                                       "epoch-1", references().calibration)
    assert adapter().measure(direct, monotonic_ns=1_000_000_000) is None


def test_sleep_clock_step_and_source_disagreement_fail_closed():
    assert adapter().measure(references(), monotonic_ns=1_000_000_000, slept=True) is None
    assert adapter().measure(references(), monotonic_ns=1_000_000_000, host_clock_step=True) is None
    assert adapter().measure(references(source_fingerprints=("fp-a", "unknown")),
                             monotonic_ns=1_000_000_000) is None


def test_expired_calibration_never_creates_a_measurement():
    assert adapter().measure(references(), monotonic_ns=61_001_000_000) is None
