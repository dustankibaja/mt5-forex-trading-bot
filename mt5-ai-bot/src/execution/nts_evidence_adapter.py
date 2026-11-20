"""Offline boundary for RFC 8915 NTS measurement evidence.

This is not an NTS client and never opens a socket or changes a host clock.
An eventual approved-host collector must validate NTS-KE TLS and NTP extension
field authentication before invoking the private measurement factory.  The
adapter only checks evidence relationships and deliberately emits no production
``UtcEvidence`` object, so recorded fixtures cannot certify a quote.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math


_NTS_MEASUREMENT_ISSUER = object()


@dataclass(frozen=True)
class NtsAuthenticatedMeasurement:
    authority_id: str
    source_family: str
    certificate_identity: str
    host_identity: str
    account_binding: str
    synchronization_epoch: str
    request_monotonic_ns: int
    receipt_monotonic_ns: int
    utc_seconds: float
    uncertainty_seconds: float
    expires_monotonic_ns: int
    sequence: int
    _issuer: object | None = field(default=None, repr=False, compare=False)


def _authenticated_nts_measurement(**values) -> NtsAuthenticatedMeasurement:
    """Private collector/fixture boundary; no public caller supplies this proof."""
    return NtsAuthenticatedMeasurement(**values, _issuer=_NTS_MEASUREMENT_ISSUER)


@dataclass(frozen=True)
class NtsEvidenceDecision:
    accepted: bool
    certified: bool
    reason: str
    bounded_utc_low: float | None = None
    bounded_utc_high: float | None = None


class NtsEvidenceAdapter:
    """Require two independent authenticated NTS source families.

    The reported interval conservatively contains each source's asserted UTC
    uncertainty plus its entire local request/receipt round trip. It is a
    candidate interval only: a real approved-host collector must separately
    persist source transcripts and pass the durable UTC evidence pipeline.
    """
    def __init__(self, *, host_identity: str, account_binding: str,
                 max_round_trip_ns: int = 2_000_000_000,
                 max_uncertainty_seconds: float = .25,
                 max_source_disagreement_seconds: float = .25):
        if not host_identity or not account_binding or min(max_round_trip_ns, max_uncertainty_seconds,
                                                           max_source_disagreement_seconds) <= 0:
            raise ValueError("bound NTS adapter limits are required")
        self._host = host_identity
        self._binding = account_binding
        self._max_rtt = max_round_trip_ns
        self._max_uncertainty = max_uncertainty_seconds
        self._max_disagreement = max_source_disagreement_seconds
        self._last_receipt_ns: int | None = None
        self._last_sequence: int | None = None
        self._epoch: str | None = None

    def assess(self, measurements: tuple[NtsAuthenticatedMeasurement, ...], *, now_monotonic_ns: int) -> NtsEvidenceDecision:
        if type(now_monotonic_ns) is not int or len(measurements) < 2:
            return NtsEvidenceDecision(False, False, "Two authenticated NTS measurements are required")
        if any(not isinstance(item, NtsAuthenticatedMeasurement) or item._issuer is not _NTS_MEASUREMENT_ISSUER
               for item in measurements):
            return NtsEvidenceDecision(False, False, "NTS measurement provenance is untrusted")
        first = measurements[0]
        if (any(item.host_identity != self._host or item.account_binding != self._binding
                or item.synchronization_epoch != first.synchronization_epoch for item in measurements)
                or len({item.source_family for item in measurements}) < 2
                or len({item.authority_id for item in measurements}) < 2):
            return NtsEvidenceDecision(False, False, "NTS source family, authority, host, account, or epoch mismatch")
        for item in measurements:
            if (not all(isinstance(value, str) and value for value in
                        (item.authority_id, item.source_family, item.certificate_identity, item.synchronization_epoch))
                    or type(item.request_monotonic_ns) is not int or type(item.receipt_monotonic_ns) is not int
                    or item.receipt_monotonic_ns <= item.request_monotonic_ns
                    or item.receipt_monotonic_ns - item.request_monotonic_ns > self._max_rtt
                    or now_monotonic_ns > item.expires_monotonic_ns
                    or type(item.sequence) is not int or item.sequence <= 0
                    or not all(math.isfinite(value) for value in (item.utc_seconds, item.uncertainty_seconds))
                    or item.uncertainty_seconds < 0 or item.uncertainty_seconds > self._max_uncertainty):
                return NtsEvidenceDecision(False, False, "NTS measurement is stale, malformed, or excessively uncertain")
        if self._last_receipt_ns is not None and (
                first.synchronization_epoch != self._epoch or first.sequence != self._last_sequence + 1
                or min(item.receipt_monotonic_ns for item in measurements) <= self._last_receipt_ns):
            return NtsEvidenceDecision(False, False, "NTS epoch or monotonic observation continuity was interrupted")
        intervals = []
        for item in measurements:
            # A one-way path is unknowable: charge the full RTT to the interval.
            allowance = item.uncertainty_seconds + (item.receipt_monotonic_ns - item.request_monotonic_ns) / 1e9
            intervals.append((item.utc_seconds - allowance, item.utc_seconds + allowance))
        low, high = max(value[0] for value in intervals), min(value[1] for value in intervals)
        if low > high or max(item.utc_seconds for item in measurements) - min(item.utc_seconds for item in measurements) > self._max_disagreement:
            return NtsEvidenceDecision(False, False, "Independent NTS sources disagree")
        self._last_receipt_ns = max(item.receipt_monotonic_ns for item in measurements)
        self._last_sequence = first.sequence
        self._epoch = first.synchronization_epoch
        return NtsEvidenceDecision(True, False, "Bounded NTS candidate requires approved-host durable evidence", low, high)
