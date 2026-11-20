"""Approved-host verification of nonce-bound authority time assertions.

Protocol ``emtifize-signed-utc-v1``: the host generates a random challenge;
the authority signs the exact canonical assertion below (including that
challenge and its asserted UTC interval). The host records send/receipt
monotonic timestamps separately, then verifies the detached signature against
the authority-to-pinned-key map. Ordinary NTP, labels and fixture factories are
not accepted as authentication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math


_VERIFIED_TRANSCRIPT_ISSUER = object()
_PROTOCOL = "emtifize-signed-utc-v1"


@dataclass(frozen=True)
class AuthorityTimeAssertion:
    authority_id: str
    source_family: str
    key_fingerprint: str
    synchronization_epoch: str
    challenge: str
    utc_seconds: float
    uncertainty_seconds: float
    signature: bytes

    def canonical_payload(self) -> bytes:
        """UTF-8 JSON, sorted keys and compact separators, exactly as signed."""
        values = {key: getattr(self, key) for key in (
            "authority_id", "source_family", "key_fingerprint", "synchronization_epoch",
            "challenge", "utc_seconds", "uncertainty_seconds")}
        return json.dumps({"protocol": _PROTOCOL, "assertion": values}, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class HostReceipt:
    host_identity: str
    sent_monotonic_ns: int
    received_monotonic_ns: int
    assertion: AuthorityTimeAssertion


@dataclass(frozen=True)
class VerifiedUtcTranscript:
    receipt: HostReceipt
    transcript_digest: str
    _issuer: object | None = field(default=None, repr=False, compare=False)


class ApprovedHostSignedUtcVerifier:
    """Verifies signed assertions and durably consumes each challenge.

    ``verify_detached`` is supplied by the approved host's reviewed
    cryptographic provider (for example Ed25519 with pinned public keys). The
    local SQLite database stores only consumed challenge digests, so replay is
    rejected across an ordinary process restart.
    """
    def __init__(self, *, host_identity: str, authority_keys: dict[str, frozenset[str]],
                 replay_db, verify_detached, max_network_delay_ns: int = 2_000_000_000):
        if (not host_identity or not authority_keys or not callable(verify_detached)
                or max_network_delay_ns <= 0):
            raise ValueError("approved host signature-verifier configuration is required")
        self._host_identity = host_identity
        self._authority_keys = {key: frozenset(value) for key, value in authority_keys.items()}
        if any(not key or not value for key, value in self._authority_keys.items()):
            raise ValueError("every authority requires pinned key fingerprints")
        self._db = replay_db
        self._verify_detached = verify_detached
        self._max_network_delay_ns = max_network_delay_ns
        self._db.execute("""CREATE TABLE IF NOT EXISTS consumed_utc_challenges(
            authority_id TEXT NOT NULL, challenge_digest TEXT NOT NULL,
            consumed_monotonic_ns INTEGER NOT NULL,
            PRIMARY KEY(authority_id, challenge_digest))""")

    def verify(self, receipt: HostReceipt | None) -> VerifiedUtcTranscript | None:
        if receipt is None or receipt.host_identity != self._host_identity:
            return None
        assertion = receipt.assertion
        if (assertion.authority_id not in self._authority_keys
                or assertion.key_fingerprint not in self._authority_keys[assertion.authority_id]
                or not all(isinstance(value, str) and value for value in
                           (assertion.source_family, assertion.synchronization_epoch, assertion.challenge))
                or type(receipt.sent_monotonic_ns) is not int
                or type(receipt.received_monotonic_ns) is not int
                or receipt.received_monotonic_ns <= receipt.sent_monotonic_ns
                or receipt.received_monotonic_ns - receipt.sent_monotonic_ns > self._max_network_delay_ns
                or not all(math.isfinite(value) for value in
                           (assertion.utc_seconds, assertion.uncertainty_seconds))
                or assertion.uncertainty_seconds < 0):
            return None
        payload = assertion.canonical_payload()
        if not self._verify_detached(assertion.key_fingerprint, payload, assertion.signature):
            return None
        challenge_digest = hashlib.sha256(assertion.challenge.encode("utf-8")).hexdigest()
        try:
            self._db.execute("INSERT INTO consumed_utc_challenges VALUES(?,?,?)", (
                assertion.authority_id, challenge_digest, receipt.received_monotonic_ns))
        except Exception:
            return None
        digest = hashlib.sha256(payload + assertion.signature + str(receipt.sent_monotonic_ns).encode()
                                + str(receipt.received_monotonic_ns).encode()).hexdigest()
        return VerifiedUtcTranscript(receipt, digest, _VERIFIED_TRANSCRIPT_ISSUER)


def _is_verified_transcript(value: object) -> bool:
    return isinstance(value, VerifiedUtcTranscript) and value._issuer is _VERIFIED_TRANSCRIPT_ISSUER
