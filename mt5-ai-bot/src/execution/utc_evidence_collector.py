"""Read-only intake boundary for independently bounded UTC measurements.

This module deliberately has no network client and does not inspect or alter
Windows Time.  A platform-specific authority may hand it a signed/verified
measurement only after it has established an uncertainty bound.  Until then it
returns no attestation, keeping quote certification fail-closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from src.execution.quote_time_certification import UtcEvidence, _verified_utc_evidence


_AUTHORITY_ISSUER = object()


@dataclass(frozen=True)
class IndependentUtcMeasurement:
    """Opaque input emitted by an approved UTC authority adapter only."""

    source: str
    source_identity: str
    utc_seconds: float
    uncertainty_seconds: float
    measured_monotonic_ns: int
    expires_monotonic_ns: int
    synchronization_epoch: str
    _issuer: object | None = None


def _verified_independent_utc_measurement(*, source: str, source_identity: str,
                                          utc_seconds: float, uncertainty_seconds: float,
                                          measured_monotonic_ns: int,
                                          expires_monotonic_ns: int,
                                          synchronization_epoch: str) -> IndependentUtcMeasurement:
    """Internal authority adapter factory; not a UI/API input surface."""
    return IndependentUtcMeasurement(
        source, source_identity, utc_seconds, uncertainty_seconds,
        measured_monotonic_ns, expires_monotonic_ns, synchronization_epoch,
        _AUTHORITY_ISSUER,
    )


class ReadOnlyUtcEvidenceCollector:
    """Binds a continuous UTC-measurement chain to one verified DEMO account."""

    def __init__(self, account_binding: str, *, max_uncertainty_seconds: float = .25):
        if not isinstance(account_binding, str) or not account_binding:
            raise ValueError("account_binding is required")
        self._account_binding = account_binding
        self._max_uncertainty_seconds = max_uncertainty_seconds
        self._source_identity: str | None = None
        self._sync_epoch: str | None = None
        self._sequence = 0
        self._invalidated = False

    @property
    def invalidated(self) -> bool:
        return self._invalidated

    def accept(self, measurement: IndependentUtcMeasurement | None) -> UtcEvidence | None:
        """Return an internal attestation or ``None`` without guessing UTC."""
        if self._invalidated or measurement is None or measurement._issuer is not _AUTHORITY_ISSUER:
            return None
        if (not all(isinstance(value, str) and value for value in
                    (measurement.source, measurement.source_identity, measurement.synchronization_epoch))
                or not all(type(value) in (int, float) and math.isfinite(value) for value in
                           (measurement.utc_seconds, measurement.uncertainty_seconds))
                or measurement.uncertainty_seconds < 0
                or measurement.uncertainty_seconds > self._max_uncertainty_seconds
                or type(measurement.measured_monotonic_ns) is not int
                or type(measurement.expires_monotonic_ns) is not int
                or measurement.expires_monotonic_ns <= measurement.measured_monotonic_ns):
            self._invalidated = True
            return None
        if self._source_identity is None:
            self._source_identity = measurement.source_identity
            self._sync_epoch = measurement.synchronization_epoch
        elif (measurement.source_identity != self._source_identity
              or measurement.synchronization_epoch != self._sync_epoch):
            self._invalidated = True
            return None
        self._sequence += 1
        return _verified_utc_evidence(
            source=measurement.source,
            utc_seconds=measurement.utc_seconds,
            uncertainty_seconds=measurement.uncertainty_seconds,
            monotonic_ns=measurement.measured_monotonic_ns,
            expires_monotonic_ns=measurement.expires_monotonic_ns,
            account_binding=self._account_binding,
            source_identity=measurement.source_identity,
            sync_epoch=measurement.synchronization_epoch,
            observation_sequence=self._sequence,
        )
