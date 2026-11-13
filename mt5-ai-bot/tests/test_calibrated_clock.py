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
    with pytest.raises(CalibrationError, match="independently administered"):
        calibrate(
            [observation("same", 15), observation("same", 16)],
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
