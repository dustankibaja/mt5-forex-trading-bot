import pytest

from src.research.calibrated_clock import (
    CalibrationError,
    ReferenceObservation,
    calibrate,
)


def observation(family, offset, rtt=20, uncertainty=2, monotonic=1_000, host=10_000):
    return ReferenceObservation(family, family, monotonic, host, offset, rtt, uncertainty)


def test_interval_propagates_reference_and_network_uncertainty():
    clock = calibrate(
        [observation("a", 15), observation("b", 16)],
        maximum_age_ms=60_000,
        drift_bound_ppm=10,
    )
    low, high = clock.utc_interval(2_000)
    assert low < 11_015 < high
    assert high - low >= 22


def test_drift_expands_interval_with_elapsed_monotonic_time():
    clock = calibrate(
        [observation("a", 15), observation("b", 16)],
        maximum_age_ms=60_000,
        drift_bound_ppm=100,
    )
    near = clock.utc_interval(1_000)
    later = clock.utc_interval(51_000)
    assert later[1] - later[0] > near[1] - near[0]


def test_observations_are_projected_to_common_monotonic_anchor_with_drift():
    earlier = observation("a", 15, rtt=10, uncertainty=1, monotonic=1_000, host=10_000)
    later = observation("b", 16, rtt=10, uncertainty=1, monotonic=11_000, host=20_000)
    clock = calibrate(
        [earlier, later],
        maximum_age_ms=20_000,
        drift_bound_ppm=100,
    )
    low, high = clock.utc_interval(11_000)
    assert low <= 20_015 <= high
    assert clock.anchor_monotonic_ms == 11_000


def test_stale_reference_observation_is_rejected_at_anchor():
    with pytest.raises(CalibrationError, match="stale"):
        calibrate(
            [observation("a", 15), observation("b", 16, monotonic=10_000, host=19_000)],
            maximum_age_ms=5_000,
            drift_bound_ppm=10,
        )


def test_expired_calibration_is_rejected():
    clock = calibrate(
        [observation("a", 15), observation("b", 16)],
        maximum_age_ms=1_000,
        drift_bound_ppm=10,
    )
    with pytest.raises(CalibrationError, match="expired"):
        clock.utc_interval(2_001)


def test_inconsistent_reference_intervals_are_rejected():
    with pytest.raises(CalibrationError, match="inconsistent"):
        calibrate(
            [observation("a", -200, rtt=4), observation("b", 200, rtt=4)],
            maximum_age_ms=1_000,
            drift_bound_ppm=10,
        )


def test_agreeing_servers_from_one_family_are_not_independent():
    first = ReferenceObservation("server-1", "same", 1_000, 10_000, 15, 20, 2)
    second = ReferenceObservation("server-2", "same", 1_000, 10_000, 16, 20, 2)
    with pytest.raises(CalibrationError, match="independently administered"):
        calibrate(
            [first, second],
            maximum_age_ms=1_000,
            drift_bound_ppm=10,
        )


def test_one_endpoint_cannot_claim_multiple_reference_families():
    first = ReferenceObservation("same", "a", 1_000, 10_000, 15, 20, 2)
    second = ReferenceObservation("same", "b", 1_000, 10_000, 16, 20, 2)
    with pytest.raises(CalibrationError, match="multiple families"):
        calibrate(
            [first, second],
            maximum_age_ms=1_000,
            drift_bound_ppm=10,
        )


def test_blank_reference_identity_is_rejected():
    blank = ReferenceObservation(" ", "a", 1_000, 10_000, 15, 20, 2)
    with pytest.raises(CalibrationError, match="identity"):
        calibrate(
            [blank, observation("b", 16)],
            maximum_age_ms=1_000,
            drift_bound_ppm=10,
        )


@pytest.mark.parametrize("condition", ["sleep", "step"])
def test_sleep_and_clock_step_invalidate_calibration(condition):
    clock = calibrate(
        [observation("a", 15), observation("b", 16)],
        maximum_age_ms=60_000,
        drift_bound_ppm=10,
    )
    with pytest.raises(CalibrationError, match="invalidated"):
        clock.utc_interval(2_000, slept=condition == "sleep", host_clock_step=condition == "step")


def test_uncertainty_bound_violation_is_rejected():
    clock = calibrate(
        [observation("a", 15, rtt=160), observation("b", 16, rtt=160)],
        maximum_age_ms=60_000,
        drift_bound_ppm=10,
    )
    with pytest.raises(CalibrationError, match="exceeds"):
        clock.utc_interval(2_000, maximum_uncertainty_ms=50)


@pytest.mark.parametrize("field", ["maximum_age_ms", "drift_bound_ppm"])
def test_nonfinite_calibration_configuration_is_rejected(field):
    arguments = {"maximum_age_ms": 60_000, "drift_bound_ppm": 10}
    arguments[field] = float("nan")
    with pytest.raises(CalibrationError, match="finite"):
        calibrate([observation("a", 15), observation("b", 16)], **arguments)


@pytest.mark.parametrize("field", ["monotonic_ms", "host_utc_ms", "offset_ms"])
def test_nonfinite_observation_timestamps_are_rejected(field):
    values = {
        "reference": "a",
        "reference_family": "a",
        "monotonic_ms": 1_000,
        "host_utc_ms": 10_000,
        "offset_ms": 15,
        "round_trip_ms": 20,
        "reference_uncertainty_ms": 2,
    }
    values[field] = float("inf")
    with pytest.raises(CalibrationError, match="finite"):
        calibrate(
            [ReferenceObservation(**values), observation("b", 16)],
            maximum_age_ms=60_000,
            drift_bound_ppm=10,
        )


def test_nonfinite_or_negative_runtime_uncertainty_bound_is_rejected():
    clock = calibrate(
        [observation("a", 15), observation("b", 16)],
        maximum_age_ms=60_000,
        drift_bound_ppm=10,
    )
    for bound in (float("nan"), -1):
        with pytest.raises(CalibrationError, match="finite and nonnegative"):
            clock.utc_interval(2_000, maximum_uncertainty_ms=bound)
