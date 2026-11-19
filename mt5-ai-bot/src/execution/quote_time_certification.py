"""Fail-closed evidence model for quote-time certification.

This module never changes the host clock, queries a broker, or infers a
timezone.  A caller supplies independently measured UTC and separately
confirmed broker timestamp semantics.  Until both are present, every quote is
uncertified.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class QuoteTimeState(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class UtcEvidence:
    source: str
    utc_seconds: float
    uncertainty_seconds: float
    monotonic_ns: int
    expires_monotonic_ns: int


@dataclass(frozen=True)
class BrokerTimestampSemantics:
    provider: str
    kind: str
    evidence_id: str


@dataclass(frozen=True)
class QuoteCertification:
    state: QuoteTimeState
    reason: str
    raw_provider_seconds: int | None
    raw_provider_milliseconds: int | None
    host_utc_seconds: float | None
    uncertainty_seconds: float | None


class QuoteTimeCertifier:
    """Certifies only monotonically newer quotes under fresh UTC evidence."""

    def __init__(self, *, max_uncertainty_seconds: float = .25,
                 max_quote_age_seconds: float = 60.0):
        self.max_uncertainty_seconds = max_uncertainty_seconds
        self.max_quote_age_seconds = max_quote_age_seconds
        self._last_monotonic_ns: int | None = None
        self._last_utc_seconds: float | None = None
        self._last_quote_msc: int | None = None
        self._revoked = False

    def assess(self, tick, *, utc: UtcEvidence | None,
               semantics: BrokerTimestampSemantics | None) -> QuoteCertification:
        seconds = getattr(tick, "time", None)
        milliseconds = getattr(tick, "time_msc", None)
        if self._revoked:
            return self._result(QuoteTimeState.REVOKED, "Certification was revoked", seconds, milliseconds, utc)
        if utc is None or semantics is None:
            return self._result(QuoteTimeState.UNCERTIFIED, "Independent UTC or broker timestamp semantics are missing", seconds, milliseconds, utc)
        if (not isinstance(utc.source, str) or not utc.source or not isinstance(semantics.evidence_id, str)
                or not semantics.evidence_id or semantics.kind != "UTC_EPOCH_SECONDS"):
            return self._result(QuoteTimeState.UNCERTIFIED, "UTC or broker timestamp evidence is not verified", seconds, milliseconds, utc)
        if (not all(math.isfinite(value) for value in (utc.utc_seconds, utc.uncertainty_seconds))
                or utc.uncertainty_seconds < 0 or utc.uncertainty_seconds > self.max_uncertainty_seconds
                or type(utc.monotonic_ns) is not int or type(utc.expires_monotonic_ns) is not int
                or utc.expires_monotonic_ns <= utc.monotonic_ns):
            return self._result(QuoteTimeState.UNCERTIFIED, "UTC uncertainty evidence is invalid or excessive", seconds, milliseconds, utc)
        if utc.monotonic_ns > utc.expires_monotonic_ns:
            return self._result(QuoteTimeState.UNCERTIFIED, "UTC evidence expired", seconds, milliseconds, utc)
        if self._last_monotonic_ns is not None:
            if utc.monotonic_ns <= self._last_monotonic_ns:
                self._revoked = True
                return self._result(QuoteTimeState.REVOKED, "Host monotonic clock did not advance", seconds, milliseconds, utc)
            if utc.utc_seconds + utc.uncertainty_seconds < self._last_utc_seconds - utc.uncertainty_seconds:
                self._revoked = True
                return self._result(QuoteTimeState.REVOKED, "Host UTC clock rolled back", seconds, milliseconds, utc)
        self._last_monotonic_ns, self._last_utc_seconds = utc.monotonic_ns, utc.utc_seconds
        if (type(seconds) is not int or seconds <= 0 or type(milliseconds) is not int or milliseconds <= 0
                or milliseconds // 1000 != seconds):
            return self._result(QuoteTimeState.UNCERTIFIED, "Raw broker timestamp fields are missing or inconsistent", seconds, milliseconds, utc)
        if self._last_quote_msc is not None and milliseconds <= self._last_quote_msc:
            return self._result(QuoteTimeState.UNCERTIFIED, "Quote is cached or not newer than the prior observation", seconds, milliseconds, utc)
        self._last_quote_msc = milliseconds
        age = utc.utc_seconds - milliseconds / 1000
        if age < -utc.uncertainty_seconds:
            return self._result(QuoteTimeState.UNCERTIFIED, "Broker quote is future-dated beyond UTC uncertainty", seconds, milliseconds, utc)
        if age > self.max_quote_age_seconds + utc.uncertainty_seconds:
            return self._result(QuoteTimeState.UNCERTIFIED, "Broker quote exceeds certified freshness window", seconds, milliseconds, utc)
        return self._result(QuoteTimeState.CERTIFIED, "Fresh newer quote under verified UTC and broker semantics", seconds, milliseconds, utc)

    @staticmethod
    def _result(state, reason, seconds, milliseconds, utc):
        return QuoteCertification(
            state, reason, seconds if type(seconds) is int else None,
            milliseconds if type(milliseconds) is int else None,
            utc.utc_seconds if utc else None,
            utc.uncertainty_seconds if utc else None,
        )
