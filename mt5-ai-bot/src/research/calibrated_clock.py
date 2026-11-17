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

    def reference_utc_interval(
        self, anchor_monotonic_ms: float, drift_bound_ppm: float
    ) -> tuple[float, float]:
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
        if not self.reference.strip() or not self.reference_family.strip():
            raise CalibrationError("Reference identity and family are required")
        elapsed = anchor_monotonic_ms - self.monotonic_ms
        if elapsed < 0:
            raise CalibrationError("Observation follows the calibration anchor")
        drift_allowance = elapsed * drift_bound_ppm / 1_000_000
        allowance = self.round_trip_ms / 2 + self.reference_uncertainty_ms + drift_allowance
        projected_utc = self.host_utc_ms + self.offset_ms + elapsed
        return projected_utc - allowance, projected_utc + allowance


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
        state = (
            monotonic_ms,
            self.anchor_monotonic_ms,
            self.anchor_host_utc_ms,
            self.offset_low_ms,
            self.offset_high_ms,
            self.drift_low_ms_per_ms,
            self.drift_high_ms_per_ms,
            self.expires_monotonic_ms,
        )
        if not all(math.isfinite(value) for value in state):
            raise CalibrationError("Calibration and timestamp values must be finite")
        if monotonic_ms < self.anchor_monotonic_ms:
            raise CalibrationError("Monotonic time precedes calibration")
        if monotonic_ms > self.expires_monotonic_ms:
            raise CalibrationError("Calibration expired")
        elapsed = monotonic_ms - self.anchor_monotonic_ms
        host_estimate = self.anchor_host_utc_ms + elapsed
        low = host_estimate + self.offset_low_ms + self.drift_low_ms_per_ms * elapsed
        high = host_estimate + self.offset_high_ms + self.drift_high_ms_per_ms * elapsed
        if maximum_uncertainty_ms is not None:
            if not math.isfinite(maximum_uncertainty_ms) or maximum_uncertainty_ms < 0:
                raise CalibrationError("Maximum uncertainty must be finite and nonnegative")
            if (high - low) / 2 > maximum_uncertainty_ms:
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
    configuration = (maximum_age_ms, drift_bound_ppm)
    if not all(math.isfinite(value) for value in configuration):
        raise CalibrationError("Calibration configuration must be finite")
    if maximum_age_ms <= 0 or drift_bound_ppm < 0:
        raise CalibrationError("Invalid calibration lifetime or drift bound")
    if (isinstance(required_reference_families, bool)
            or not isinstance(required_reference_families, int)
            or required_reference_families < 2):
        raise CalibrationError("At least two independent reference families are required")
    reference_families: dict[str, str] = {}
    for item in observations:
        item.reference_utc_interval(item.monotonic_ms, drift_bound_ppm)
        previous_family = reference_families.setdefault(item.reference, item.reference_family)
        if previous_family != item.reference_family:
            raise CalibrationError("A reference endpoint cannot claim multiple families")
    families = tuple(sorted(set(reference_families.values())))
    if len(reference_families) < required_reference_families:
        raise CalibrationError("Insufficient distinct reference endpoints")
    if len(families) < required_reference_families:
        raise CalibrationError("Insufficient independently administered reference families")

    anchor = max(observations, key=lambda item: item.monotonic_ms)
    intervals = []
    for item in observations:
        age = anchor.monotonic_ms - item.monotonic_ms
        if age > maximum_age_ms:
            raise CalibrationError("Reference observation is stale at calibration anchor")
        reference_low, reference_high = item.reference_utc_interval(
            anchor.monotonic_ms, drift_bound_ppm
        )
        intervals.append((
            reference_low - anchor.host_utc_ms,
            reference_high - anchor.host_utc_ms,
        ))
    overlap_low = max(low for low, _ in intervals)
    overlap_high = min(high for _, high in intervals)
    if overlap_low > overlap_high:
        raise CalibrationError("Reference uncertainty intervals are inconsistent")

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
