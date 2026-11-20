"""Fail-closed evidence model for quote-time certification.

Attestations are issued only by the internal collector adapter. The certifier
rejects look-alike dataclasses constructed by callers: labels are not proof.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import time


class QuoteTimeState(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"


_UTC_ISSUER = object()
_SEMANTICS_ISSUER = object()


@dataclass(frozen=True)
class UtcEvidence:
    """An internal UTC collector attestation; direct construction is untrusted."""

    source: str
    utc_seconds: float
    uncertainty_seconds: float
    monotonic_ns: int
    expires_monotonic_ns: int
    account_binding: str = ""
    source_identity: str = ""
    sync_epoch: str = ""
    observation_sequence: int = 0
    _issuer: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class BrokerTimestampSemantics:
    """An internal broker-semantics attestation; direct construction is untrusted."""

    provider: str
    kind: str
    evidence_id: str
    account_binding: str = ""
    source_identity: str = ""
    _issuer: object | None = field(default=None, repr=False, compare=False)


def _verified_utc_evidence(*, source: str, utc_seconds: float,
                           uncertainty_seconds: float, monotonic_ns: int,
                           expires_monotonic_ns: int, account_binding: str,
                           source_identity: str, sync_epoch: str,
                           observation_sequence: int) -> UtcEvidence:
    """Internal adapter factory; do not expose this to UI/API callers."""
    return UtcEvidence(source, utc_seconds, uncertainty_seconds, monotonic_ns,
                       expires_monotonic_ns, account_binding, source_identity,
                       sync_epoch, observation_sequence, _UTC_ISSUER)


def _verified_broker_timestamp_semantics(*, provider: str, kind: str,
                                         evidence_id: str, account_binding: str,
                                         source_identity: str) -> BrokerTimestampSemantics:
    """Internal adapter factory; records a controlled semantics attestation."""
    return BrokerTimestampSemantics(provider, kind, evidence_id, account_binding,
                                    source_identity, _SEMANTICS_ISSUER)


@dataclass(frozen=True)
class QuoteCertification:
    state: QuoteTimeState
    reason: str
    raw_provider_seconds: int | None
    raw_provider_milliseconds: int | None
    host_utc_seconds: float | None
    uncertainty_seconds: float | None


class QuoteTimeCertifier:
    """Certifies only a continuous sequence of newer quotes under live evidence."""

    def __init__(self, *, max_uncertainty_seconds: float = .25,
                 max_quote_age_seconds: float = 60.0, monotonic_clock_ns=None):
        self.max_uncertainty_seconds = max_uncertainty_seconds
        self.max_quote_age_seconds = max_quote_age_seconds
        self._monotonic_clock_ns = monotonic_clock_ns or time.monotonic_ns
        self._last_now_ns: int | None = None
        self._last_utc_seconds: float | None = None
        self._last_quote_msc: int | None = None
        self._last_sequence: int | None = None
        self._account_binding: str | None = None
        self._source_identity: str | None = None
        self._sync_epoch: str | None = None
        self._revoked = False

    def assess(self, tick, *, utc: UtcEvidence | None,
               semantics: BrokerTimestampSemantics | None) -> QuoteCertification:
        seconds = getattr(tick, "time", None)
        milliseconds = getattr(tick, "time_msc", None)
        if self._revoked:
            return self._result(QuoteTimeState.REVOKED, "Certification was revoked", seconds, milliseconds, utc)
        if utc is None or semantics is None:
            return self._result(QuoteTimeState.UNCERTIFIED, "Independent UTC or broker timestamp semantics are missing", seconds, milliseconds, utc)
        if utc._issuer is not _UTC_ISSUER or semantics._issuer is not _SEMANTICS_ISSUER:
            return self._result(QuoteTimeState.UNCERTIFIED, "UTC or broker timestamp evidence is not internally verified", seconds, milliseconds, utc)
        if (not all(isinstance(value, str) and value for value in
                    (utc.source, utc.account_binding, utc.source_identity, utc.sync_epoch,
                     semantics.provider, semantics.evidence_id, semantics.account_binding,
                     semantics.source_identity))
                or semantics.kind != "UTC_EPOCH_SECONDS"
                or utc.account_binding != semantics.account_binding
                or utc.source_identity != semantics.source_identity):
            return self._result(QuoteTimeState.UNCERTIFIED, "UTC or broker timestamp evidence is inconsistent", seconds, milliseconds, utc)
        now_ns = self._monotonic_clock_ns()
        if (type(now_ns) is not int or not all(type(value) in (int, float) and math.isfinite(value) for value in
                (utc.utc_seconds, utc.uncertainty_seconds))
                or utc.uncertainty_seconds < 0 or utc.uncertainty_seconds > self.max_uncertainty_seconds
                or type(utc.monotonic_ns) is not int or type(utc.expires_monotonic_ns) is not int
                or type(utc.observation_sequence) is not int or utc.observation_sequence <= 0
                or utc.expires_monotonic_ns <= utc.monotonic_ns):
            return self._result(QuoteTimeState.UNCERTIFIED, "UTC uncertainty evidence is invalid or excessive", seconds, milliseconds, utc)
        if now_ns > utc.expires_monotonic_ns:
            return self._result(QuoteTimeState.UNCERTIFIED, "UTC evidence expired", seconds, milliseconds, utc)
        if self._last_now_ns is None and utc.observation_sequence != 1:
            return self._result(QuoteTimeState.UNCERTIFIED, "First UTC evidence observation must start at sequence one", seconds, milliseconds, utc)
        if self._last_now_ns is not None:
            if now_ns <= self._last_now_ns:
                return self._revoke("Host monotonic clock did not advance", seconds, milliseconds, utc)
            if utc.utc_seconds + utc.uncertainty_seconds < self._last_utc_seconds - utc.uncertainty_seconds:
                return self._revoke("Host UTC clock rolled back", seconds, milliseconds, utc)
            if (utc.account_binding != self._account_binding or utc.source_identity != self._source_identity
                    or utc.sync_epoch != self._sync_epoch):
                return self._revoke("Account binding, source identity, or time synchronization changed", seconds, milliseconds, utc)
            if utc.observation_sequence != self._last_sequence + 1:
                return self._revoke("UTC evidence continuity was interrupted", seconds, milliseconds, utc)
        if (type(seconds) is not int or seconds <= 0 or type(milliseconds) is not int or milliseconds <= 0
                or milliseconds // 1000 != seconds):
            return self._result(QuoteTimeState.UNCERTIFIED, "Raw broker timestamp fields are missing or inconsistent", seconds, milliseconds, utc)
        if self._last_quote_msc is not None and milliseconds <= self._last_quote_msc:
            return self._result(QuoteTimeState.UNCERTIFIED, "Quote is cached or not newer than the prior observation", seconds, milliseconds, utc)
        age = utc.utc_seconds - milliseconds / 1000
        if age < -utc.uncertainty_seconds:
            return self._result(QuoteTimeState.UNCERTIFIED, "Broker quote is future-dated beyond UTC uncertainty", seconds, milliseconds, utc)
        if age > self.max_quote_age_seconds + utc.uncertainty_seconds:
            return self._result(QuoteTimeState.UNCERTIFIED, "Broker quote exceeds certified freshness window", seconds, milliseconds, utc)
        self._last_now_ns, self._last_utc_seconds = now_ns, utc.utc_seconds
        self._last_quote_msc, self._last_sequence = milliseconds, utc.observation_sequence
        self._account_binding, self._source_identity, self._sync_epoch = (
            utc.account_binding, utc.source_identity, utc.sync_epoch)
        if self._last_sequence == 1:
            return self._result(QuoteTimeState.UNCERTIFIED, "First verified quote establishes continuity", seconds, milliseconds, utc)
        return self._result(QuoteTimeState.CERTIFIED, "Fresh successive quote under verified UTC and broker semantics", seconds, milliseconds, utc)

    def _revoke(self, reason, seconds, milliseconds, utc):
        self._revoked = True
        return self._result(QuoteTimeState.REVOKED, reason, seconds, milliseconds, utc)

    @staticmethod
    def _result(state, reason, seconds, milliseconds, utc):
        return QuoteCertification(
            state, reason, seconds if type(seconds) is int else None,
            milliseconds if type(milliseconds) is int else None,
            utc.utc_seconds if utc else None,
            utc.uncertainty_seconds if utc else None,
        )
