"""Pinned Ed25519 public-key verification for approved-host time sources.

This module deliberately has no transport or private-key support.  A host
administrator supplies public keys through an approved deployment mechanism;
the runtime only accepts raw 32-byte Ed25519 public keys and identifies them
by SHA-256 fingerprint.  Revocation is fail-closed.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def public_key_fingerprint(raw_public_key: bytes) -> str:
    """Return the canonical SHA-256 fingerprint for a raw Ed25519 public key."""
    if not isinstance(raw_public_key, bytes) or len(raw_public_key) != 32:
        raise ValueError("an Ed25519 public key must be exactly 32 raw bytes")
    return hashlib.sha256(raw_public_key).hexdigest()


class Ed25519AuthorityKeyring:
    """Authority-to-public-key pin set with explicit key revocation.

    ``authority_public_keys`` is ``{authority_id: {fingerprint: raw_key}}``.
    The expected fingerprint is re-derived rather than trusted from config.
    A key may be present during a rotation, while any listed revoked key is
    refused immediately.
    """

    def __init__(self, authority_public_keys: Mapping[str, Mapping[str, bytes]],
                 *, revoked_fingerprints: frozenset[str] = frozenset()):
        self._keys: dict[str, dict[str, Ed25519PublicKey]] = {}
        self._revoked = frozenset(revoked_fingerprints)
        for authority, keys in authority_public_keys.items():
            if not isinstance(authority, str) or not authority or not keys:
                raise ValueError("each authority needs a non-empty public-key set")
            loaded: dict[str, Ed25519PublicKey] = {}
            for configured_fingerprint, raw_key in keys.items():
                fingerprint = public_key_fingerprint(raw_key)
                if configured_fingerprint != fingerprint:
                    raise ValueError("configured authority key fingerprint does not match public key")
                loaded[fingerprint] = Ed25519PublicKey.from_public_bytes(raw_key)
            self._keys[authority] = loaded
        if not self._keys:
            raise ValueError("at least one authority key is required")

    @property
    def authority_key_fingerprints(self) -> dict[str, frozenset[str]]:
        return {authority: frozenset(keys) for authority, keys in self._keys.items()}

    def verify(self, authority_id: str, key_fingerprint: str,
               payload: bytes, signature: bytes) -> bool:
        """Return false for unknown, revoked, malformed or invalid assertions."""
        key = self._keys.get(authority_id, {}).get(key_fingerprint)
        if key is None or key_fingerprint in self._revoked:
            return False
        if not isinstance(payload, bytes) or not isinstance(signature, bytes):
            return False
        try:
            key.verify(signature, payload)
        except (InvalidSignature, ValueError, TypeError):
            return False
        return True
