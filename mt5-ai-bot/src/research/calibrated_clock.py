"""Candidate research-clock protocol. It is not an acceptance-v1 clock source."""

from dataclasses import dataclass
import math


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class ReferenceObservation:
    reference: str
    reference_family: str
    monotonic_ms: float
    host_utc_ms: float
    offset_ms: float
    round_trip_ms: float
    reference_uncertainty_ms: float

    def offset_interval(self) -> tuple[float, float]:
        values = (
            self.monotonic_ms,
            self.host_utc_ms,
            self.offset_ms,
            self.round_trip_ms,
            self.reference_uncertainty_ms,
        )
        if not all(math.isfinite(value) for value in values):
            raise CalibrationError("Observation values must be finite")
        if self.round_trip_ms < 0 or self.reference_uncertainty_ms < 0:
            raise CalibrationError("Uncertainty inputs must be nonnegative")
        allowance = self.round_trip_ms / 2 + self.reference_uncertainty_ms
        return self.offset_ms - allowance, self.offset_ms + allowance


@dataclass(frozen=True)
class Calibration:
    anchor_monotonic_ms: float
    anchor_host_utc_ms: float
    offset_low_ms: float
    offset_high_ms: float
    drift_low_ms_per_ms: float
    drift_high_ms_per_ms: float
    expires_monotonic_ms: float
    reference_families: tuple[str, ...]
    protocol: str = "research-calibrated-clock-candidate-v1"

    def utc_interval(
        self,
        monotonic_ms: float,
        *,
        slept: bool = False,
        host_clock_step: bool = False,
        maximum_uncertainty_ms: float | None = None,
    ) -> tuple[float, float]:
        if slept or host_clock_step:
            raise CalibrationError("Calibration invalidated by sleep or host-clock step")
        if monotonic_ms < self.anchor_monotonic_ms:
            raise CalibrationError("Monotonic time precedes calibration")
        if monotonic_ms > self.expires_monotonic_ms:
            raise CalibrationError("Calibration expired")
        elapsed = monotonic_ms - self.anchor_monotonic_ms
        host_estimate = self.anchor_host_utc_ms + elapsed
        low = host_estimate + self.offset_low_ms + self.drift_low_ms_per_ms * elapsed
        high = host_estimate + self.offset_high_ms + self.drift_high_ms_per_ms * elapsed
        if maximum_uncertainty_ms is not None and (high - low) / 2 > maximum_uncertainty_ms:
            raise CalibrationError("Derived UTC uncertainty exceeds protocol bound")
        return low, high


def calibrate(
    observations: list[ReferenceObservation],
    *,
    maximum_age_ms: float,
    drift_bound_ppm: float,
    required_reference_families: int = 2,
) -> Calibration:
    if not observations:
        raise CalibrationError("At least one reference observation is required")
    if maximum_age_ms <= 0 or drift_bound_ppm < 0:
        raise CalibrationError("Invalid calibration lifetime or drift bound")
    families = tuple(sorted({item.reference_family for item in observations}))
    if len(families) < required_reference_families:
        raise CalibrationError("Insufficient independently administered reference families")

    intervals = [item.offset_interval() for item in observations]
    overlap_low = max(low for low, _ in intervals)
    overlap_high = min(high for _, high in intervals)
    if overlap_low > overlap_high:
        raise CalibrationError("Reference uncertainty intervals are inconsistent")

    anchor = max(observations, key=lambda item: item.monotonic_ms)
    drift = drift_bound_ppm / 1_000_000
    return Calibration(
        anchor_monotonic_ms=anchor.monotonic_ms,
        anchor_host_utc_ms=anchor.host_utc_ms,
        offset_low_ms=overlap_low,
        offset_high_ms=overlap_high,
        drift_low_ms_per_ms=-drift,
        drift_high_ms_per_ms=drift,
        expires_monotonic_ms=anchor.monotonic_ms + maximum_age_ms,
        reference_families=families,
    )
