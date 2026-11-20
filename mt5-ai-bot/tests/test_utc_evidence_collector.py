from src.execution.utc_evidence_collector import (
    IndependentUtcMeasurement,
    ReadOnlyUtcEvidenceCollector,
    _verified_independent_utc_measurement,
)


def measurement(**overrides):
    values = dict(
        source="bounded-independent-authority", source_identity="authority-key-1",
        host_identity="approved-host-1",
        utc_seconds=1000.0, uncertainty_seconds=.05, measured_monotonic_ns=10,
        expires_monotonic_ns=20, synchronization_epoch="sync-epoch-1",
    )
    values.update(overrides)
    return _verified_independent_utc_measurement(**values)


def test_untrusted_or_missing_measurements_never_create_evidence():
    collector = ReadOnlyUtcEvidenceCollector("bound-demo", "approved-host-1")
    assert collector.accept(None) is None
    direct = IndependentUtcMeasurement("source", "identity", "approved-host-1", 1000., .05, 10, 20, "epoch")
    assert collector.accept(direct) is None
    assert not collector.invalidated


def test_collector_sequences_controlled_measurements_for_one_binding():
    collector = ReadOnlyUtcEvidenceCollector("bound-demo", "approved-host-1")
    first = collector.accept(measurement())
    second = collector.accept(measurement(utc_seconds=1001., measured_monotonic_ns=11,
                                          expires_monotonic_ns=21))
    assert first is not None and first.observation_sequence == 1
    assert second is not None and second.observation_sequence == 2
    assert second.account_binding == "bound-demo"


def test_source_or_time_sync_change_invalidates_collection():
    collector = ReadOnlyUtcEvidenceCollector("bound-demo", "approved-host-1")
    assert collector.accept(measurement()) is not None
    assert collector.accept(measurement(source_identity="other")) is None
    assert collector.invalidated
    assert collector.accept(measurement()) is None


def test_measurement_from_another_host_invalidates_collection():
    collector = ReadOnlyUtcEvidenceCollector("bound-demo", "approved-host-1")
    assert collector.accept(measurement(host_identity="another-host")) is None
    assert collector.invalidated


def test_invalid_uncertainty_invalidates_without_guessing():
    collector = ReadOnlyUtcEvidenceCollector("bound-demo", "approved-host-1")
    assert collector.accept(measurement(uncertainty_seconds=.5)) is None
    assert collector.invalidated


def test_repeated_or_out_of_order_measurement_invalidates_continuity():
    collector = ReadOnlyUtcEvidenceCollector("bound-demo", "approved-host-1")
    assert collector.accept(measurement()) is not None
    assert collector.accept(measurement()) is None
    assert collector.invalidated


def test_future_sequence_requires_strictly_new_monotonic_and_utc_values():
    collector = ReadOnlyUtcEvidenceCollector("bound-demo", "approved-host-1")
    assert collector.accept(measurement()) is not None
    assert collector.accept(measurement(utc_seconds=999., measured_monotonic_ns=11,
                                        expires_monotonic_ns=21)) is None
    assert collector.invalidated
