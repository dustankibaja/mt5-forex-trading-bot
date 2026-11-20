"""Operator-gated collection orchestration for an approved Windows host.

There is intentionally no network client here.  An authorized host supplies a
transport implementation after separately approving its endpoint and keys.
Fixtures can exercise this orchestration but cannot turn its result into a
production UTC certification.
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
    """Issue challenges and collect a response only after local activation.

    The runner is not a certification authority: even an accepted response is
    returned as evidence for the independent-family/evidence ledger path, with
    ``certified`` always false.  This prevents test transports and synthesized
    observations from granting a production readiness state.
    """

    def __init__(self, *, verifier: ApprovedHostSignedUtcVerifier,
                 host_identity: str, account_binding: str,
                 operator_enabled: bool = False, monotonic_clock_ns=time.monotonic_ns):
        if not verifier or not host_identity or not account_binding or not callable(monotonic_clock_ns):
            raise ValueError("bound approved-host runner configuration is required")
        self._verifier = verifier
        self.host_identity = host_identity
        self.account_binding = account_binding
        self._enabled = operator_enabled
        self._monotonic_clock_ns = monotonic_clock_ns

    def issue(self, *, authority_id: str, synchronization_epoch: str, ttl_ns: int) -> HostChallenge:
        if not self._enabled:
            raise PermissionError("approved-host collection requires explicit operator activation")
        return self._verifier.issue_challenge(
            authority_id=authority_id, synchronization_epoch=synchronization_epoch,
            issued_monotonic_ns=self._monotonic_clock_ns(), ttl_ns=ttl_ns)

    def collect(self, assertion: AuthorityTimeAssertion, *, sent_monotonic_ns: int,
                received_monotonic_ns: int | None = None) -> HostCollectionResult:
        if not self._enabled:
            return HostCollectionResult(None, False, "Operator activation is required")
        receipt = HostReceipt(self.host_identity, sent_monotonic_ns,
                              self._monotonic_clock_ns() if received_monotonic_ns is None else received_monotonic_ns,
                              assertion)
        transcript = self._verifier.verify(receipt)
        if transcript is None:
            return HostCollectionResult(None, False, "Signed response was rejected or could not be durably consumed")
        return HostCollectionResult(transcript, False,
                                    "Accepted evidence still requires independent sources and durable qualification")
