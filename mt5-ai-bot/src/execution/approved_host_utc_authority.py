"""Approved-host adapter for authenticated, bounded UTC evidence.

It intentionally performs no NTP/network access. A host administrator's
transport verifier must authenticate references and create the private input
record after retaining its evidence. This layer binds that record to one host,
one DEMO identity, a calibration epoch and a conservative uncertainty interval.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from src.execution.utc_evidence_collector import (
    IndependentUtcMeasurement,
    _verified_independent_utc_measurement,
)
from src.research.calibrated_clock import Calibration, CalibrationError, ReferenceObservation, calibrate
from src.execution.authenticated_utc_transport import VerifiedUtcTranscript, _is_verified_transcript


_AUTHENTICATED_REFERENCE_ISSUER = object()


@dataclass(frozen=True)
class AuthenticatedReferenceSet:
    """Result of host-side source authentication, not a caller-supplied label."""

    authority_id: str
    host_identity: str
    source_fingerprints: tuple[str, ...]
    transcript_digests: tuple[str, ...]
    synchronization_epoch: str
    calibration: Calibration
    _issuer: object | None = field(default=None, repr=False, compare=False)


def _authenticated_reference_set(*, authority_id: str, host_identity: str,
                                 source_fingerprints: tuple[str, ...],
                                 transcript_digests: tuple[str, ...] = (),
                                 synchronization_epoch: str,
                                 calibration: Calibration) -> AuthenticatedReferenceSet:
    """Private factory reserved for a separately reviewed host transport verifier."""
    return AuthenticatedReferenceSet(
        authority_id, host_identity, source_fingerprints, transcript_digests,
        synchronization_epoch, calibration, _AUTHENTICATED_REFERENCE_ISSUER,
    )


def reference_set_from_verified_transcripts(*, host_identity: str,
                                            synchronization_epoch: str,
                                            transcripts: tuple[VerifiedUtcTranscript, ...],
                                            maximum_age_ms: float,
                                            drift_bound_ppm: float,
                                            ) -> AuthenticatedReferenceSet | None:
    """Build a reference set only from distinct signed-source families.

    The private fixture factory remains for isolated tests; production callers
    must use this entry point after host-side signature verification.
    """
    if (len(transcripts) < 2 or not synchronization_epoch
            or any(not _is_verified_transcript(item) for item in transcripts)):
        return None
    raw = tuple(item.receipt for item in transcripts)
    assertions = tuple(item.assertion for item in raw)
    if (any(receipt.host_identity != host_identity or assertion.synchronization_epoch != synchronization_epoch
            for receipt, assertion in zip(raw, assertions))
            or len({item.source_family for item in assertions}) < 2):
        return None
    try:
        calibration = calibrate([
            ReferenceObservation(assertion.authority_id, assertion.source_family,
                                 receipt.received_monotonic_ns / 1_000_000,
                                 assertion.utc_seconds * 1000, 0.0,
                                 (receipt.received_monotonic_ns - receipt.sent_monotonic_ns) / 1_000_000,
                                 assertion.uncertainty_seconds * 1000)
            for receipt, assertion in zip(raw, assertions)], maximum_age_ms=maximum_age_ms,
            drift_bound_ppm=drift_bound_ppm)
    except CalibrationError:
        return None
    authority_id = "signed-set:" + "|".join(sorted({item.authority_id for item in assertions}))
    fingerprints = tuple(sorted(f"{item.authority_id}:{item.key_fingerprint}" for item in assertions))
    return _authenticated_reference_set(authority_id=authority_id, host_identity=host_identity,
                                        source_fingerprints=fingerprints,
                                        transcript_digests=tuple(sorted(item.transcript_digest for item in transcripts)),
                                        synchronization_epoch=synchronization_epoch,
                                        calibration=calibration)


class ApprovedHostUtcAuthorityAdapter:
    """Turns a verified host record into an internal UTC measurement.

    The calling host must authenticate source identities and retain transport
    evidence first. This adapter rejects unapproved authorities, source sets,
    host mismatch, expiry, clock-step and excessive uncertainty.
    """

    def __init__(self, *, host_identity: str, approved_authorities: frozenset[str],
                 approved_source_fingerprints: frozenset[str],
                 maximum_uncertainty_seconds: float = .25):
        if (not isinstance(host_identity, str) or not host_identity
                or not approved_authorities or not approved_source_fingerprints
                or maximum_uncertainty_seconds <= 0):
            raise ValueError("approved host authority configuration is required")
        self._host_identity = host_identity
        self._approved_authorities = approved_authorities
        self._approved_source_fingerprints = approved_source_fingerprints
        self._maximum_uncertainty_seconds = maximum_uncertainty_seconds

    def measure(self, references: AuthenticatedReferenceSet | None, *,
                monotonic_ns: int, slept: bool = False,
                host_clock_step: bool = False) -> IndependentUtcMeasurement | None:
        if references is None or references._issuer is not _AUTHENTICATED_REFERENCE_ISSUER:
            return None
        if (references.host_identity != self._host_identity
                or references.authority_id not in self._approved_authorities
                or not references.synchronization_epoch
                or len(references.source_fingerprints) < 2
                or any(item not in self._approved_source_fingerprints
                       for item in references.source_fingerprints)
                or type(monotonic_ns) is not int):
            return None
        try:
            low_ms, high_ms = references.calibration.utc_interval(
                monotonic_ns / 1_000_000,
                slept=slept,
                host_clock_step=host_clock_step,
                maximum_uncertainty_ms=self._maximum_uncertainty_seconds * 1000,
            )
        except CalibrationError:
            return None
        if not all(math.isfinite(value) for value in (low_ms, high_ms)) or high_ms < low_ms:
            return None
        uncertainty = (high_ms - low_ms) / 2 / 1000
        return _verified_independent_utc_measurement(
            source=references.authority_id,
            source_identity="|".join(sorted(references.source_fingerprints)),
            host_identity=self._host_identity,
            utc_seconds=(low_ms + high_ms) / 2 / 1000,
            uncertainty_seconds=uncertainty,
            measured_monotonic_ns=monotonic_ns,
            expires_monotonic_ns=int(references.calibration.expires_monotonic_ms * 1_000_000),
            synchronization_epoch=references.synchronization_epoch,
        )
