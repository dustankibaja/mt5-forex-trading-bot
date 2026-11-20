"""Host-only signed UTC transcript verifier.

The approved host obtains nonce-bound signed time transcripts from independently
operated authorities. This module does not open sockets: the network transport,
certificate/key provisioning and administrator authorization remain outside the
sandbox. A transcript is acceptable only when a pinned verifier validates its
canonical payload and receipt monotonic interval.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math


_VERIFIED_TRANSCRIPT_ISSUER = object()


@dataclass(frozen=True)
class SignedUtcTranscript:
    authority_id: str
    source_family: str
    host_identity: str
    synchronization_epoch: str
    nonce: str
    utc_seconds: float
    uncertainty_seconds: float
    sent_monotonic_ns: int
    received_monotonic_ns: int
    signature: bytes
    key_fingerprint: str

    def canonical_payload(self) -> bytes:
        payload = {key: getattr(self, key) for key in (
            "authority_id", "source_family", "host_identity", "synchronization_epoch",
            "nonce", "utc_seconds", "uncertainty_seconds", "sent_monotonic_ns",
            "received_monotonic_ns", "key_fingerprint")}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class VerifiedUtcTranscript:
    transcript: SignedUtcTranscript
    transcript_digest: str
    _issuer: object | None = field(default=None, repr=False, compare=False)


class ApprovedHostSignedUtcVerifier:
    """Validates detached signatures using host-managed pinned public keys.

    ``verify_detached`` must be a production cryptographic verifier (for
    example an Ed25519 verifier configured from an administrator-approved
    pinned key). It receives ``fingerprint, payload, signature`` and returns a
    bool. This class never accepts endpoint labels or unsigned NTP data.
    """
    def __init__(self, *, host_identity: str, pinned_keys: frozenset[str],
                 approved_authorities: frozenset[str], verify_detached):
        if (not host_identity or not pinned_keys or not approved_authorities
                or not callable(verify_detached)):
            raise ValueError("approved host signature-verifier configuration is required")
        self._host_identity = host_identity
        self._pinned_keys = pinned_keys
        self._approved_authorities = approved_authorities
        self._verify_detached = verify_detached
        self._seen_nonces: set[str] = set()

    def verify(self, transcript: SignedUtcTranscript | None) -> VerifiedUtcTranscript | None:
        if transcript is None or transcript.host_identity != self._host_identity:
            return None
        if (transcript.authority_id not in self._approved_authorities
                or transcript.key_fingerprint not in self._pinned_keys
                or not transcript.nonce or transcript.nonce in self._seen_nonces
                or transcript.received_monotonic_ns <= transcript.sent_monotonic_ns
                or transcript.received_monotonic_ns - transcript.sent_monotonic_ns > 2_000_000_000
                or not all(math.isfinite(value) for value in
                           (transcript.utc_seconds, transcript.uncertainty_seconds))
                or transcript.uncertainty_seconds < 0):
            return None
        payload = transcript.canonical_payload()
        if not self._verify_detached(transcript.key_fingerprint, payload, transcript.signature):
            return None
        self._seen_nonces.add(transcript.nonce)
        return VerifiedUtcTranscript(transcript, hashlib.sha256(payload + transcript.signature).hexdigest(),
                                    _VERIFIED_TRANSCRIPT_ISSUER)


def _is_verified_transcript(value: object) -> bool:
    return isinstance(value, VerifiedUtcTranscript) and value._issuer is _VERIFIED_TRANSCRIPT_ISSUER
