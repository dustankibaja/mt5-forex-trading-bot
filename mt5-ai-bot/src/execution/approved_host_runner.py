"""Operator-gated approved-host collection orchestration.

There is deliberately no network client in this module. A separately reviewed
host transport receives a host-issued challenge and returns a signed assertion.
Production request/receipt timings are captured here with ``time.monotonic_ns``;
an injectable clock exists only through the explicit test constructor.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

from src.execution.authenticated_utc_transport import (
    ApprovedHostSignedUtcVerifier, AuthorityTimeAssertion, HostChallenge,
    HostReceipt, VerifiedUtcTranscript,
)


@dataclass(frozen=True)
class HostCollectionResult:
    transcript: VerifiedUtcTranscript | None
    certified: bool
    reason: str


class ApprovedHostCertificationRunner:
    """Capture one authority exchange on an explicitly activated host.

    A verified transcript is evidence only. This layer never manufactures a
    UTC attestation and always returns ``certified=False`` until the separate
    independent-source and durable-evidence pipeline approves real data.
    """
    def __init__(self, *, verifier: ApprovedHostSignedUtcVerifier,
                 host_identity: str, account_binding: str, operator_enabled: bool = False):
        self._initialize(verifier, host_identity, account_binding, operator_enabled, time.monotonic_ns)

    @classmethod
    def for_test(cls, *, verifier: ApprovedHostSignedUtcVerifier, host_identity: str,
                 account_binding: str, operator_enabled: bool, monotonic_clock_ns):
        """Test-only constructor; production callers cannot inject a clock."""
        instance = cls.__new__(cls)
        instance._initialize(verifier, host_identity, account_binding, operator_enabled, monotonic_clock_ns)
        return instance

    def _initialize(self, verifier, host_identity, account_binding, operator_enabled, monotonic_clock_ns):
        if (not isinstance(verifier, ApprovedHostSignedUtcVerifier) or not host_identity
                or not account_binding or verifier.host_identity != host_identity
                or not callable(monotonic_clock_ns)):
            raise ValueError("bound approved-host runner configuration is required")
        self._verifier = verifier
        self.host_identity = host_identity
        self.account_binding = account_binding
        self._enabled = operator_enabled
        self._clock = monotonic_clock_ns

    def collect_exchange(self, *, authority_id: str, synchronization_epoch: str, ttl_ns: int,
                         request_assertion) -> HostCollectionResult:
        """Generate a challenge and capture both host monotonic timestamps.

        ``request_assertion`` is an approved-host transport callback. It is not
        implemented here and is never invoked unless an operator enabled this
        runner. ``None`` and malformed/reordered timings fail closed.
        """
        if not self._enabled:
            return HostCollectionResult(None, False, "Operator activation is required")
        if not callable(request_assertion):
            return HostCollectionResult(None, False, "Approved-host transport is missing")
        issued = self._clock()
        if type(issued) is not int:
            return HostCollectionResult(None, False, "Host monotonic clock is invalid")
        try:
            challenge: HostChallenge = self._verifier.issue_challenge(
                authority_id=authority_id, synchronization_epoch=synchronization_epoch,
                issued_monotonic_ns=issued, ttl_ns=ttl_ns)
            sent = self._clock()
            assertion: AuthorityTimeAssertion | None = request_assertion(challenge)
            received = self._clock()
        except Exception:
            return HostCollectionResult(None, False, "Approved-host exchange failed")
        if (type(sent) is not int or type(received) is not int or sent <= issued or received <= sent
                or not isinstance(assertion, AuthorityTimeAssertion)):
            return HostCollectionResult(None, False, "Host timing or signed response is inconsistent")
        transcript = self._verifier.verify(HostReceipt(self.host_identity, sent, received, assertion))
        if transcript is None:
            return HostCollectionResult(None, False, "Signed response was rejected or could not be durably consumed")
        return HostCollectionResult(transcript, False,
                                    "Accepted evidence still requires independent sources and durable qualification")
