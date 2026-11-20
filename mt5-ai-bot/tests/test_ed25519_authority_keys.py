from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import sqlite3

from src.execution.authenticated_utc_transport import (
    ApprovedHostSignedUtcVerifier, AuthorityTimeAssertion, HostReceipt,
)
from src.execution.ed25519_authority_keys import (
    AuthorityBoundEd25519Verifier, Ed25519AuthorityKeyring, public_key_fingerprint,
)


def test_rfc8032_empty_message_vector_verifies_without_any_private_fixture_key():
    # RFC 8032, test 1.  Only public material and a published signature appear here.
    public = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    signature = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    fingerprint = public_key_fingerprint(public)
    keyring = Ed25519AuthorityKeyring({"rfc-test": {fingerprint: public}})
    assert keyring.verify("rfc-test", fingerprint, b"", signature)
    assert not keyring.verify("rfc-test", fingerprint, b"x", signature)


def test_rotation_and_revocation_are_authority_bound_and_fail_closed():
    private_a, private_b = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    raw_a = private_a.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    raw_b = private_b.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    fingerprint_a, fingerprint_b = public_key_fingerprint(raw_a), public_key_fingerprint(raw_b)
    payload = b"canonical assertion"
    signature_b = private_b.sign(payload)
    keyring = Ed25519AuthorityKeyring({"authority": {fingerprint_a: raw_a, fingerprint_b: raw_b}})
    assert keyring.verify("authority", fingerprint_b, payload, signature_b)
    assert not keyring.verify("other-authority", fingerprint_b, payload, signature_b)
    revoked = Ed25519AuthorityKeyring(
        {"authority": {fingerprint_a: raw_a, fingerprint_b: raw_b}},
        revoked_fingerprints=frozenset((fingerprint_b,)))
    assert not revoked.verify("authority", fingerprint_b, payload, signature_b)


def test_signed_transport_uses_the_real_keyring_when_configured():
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    fingerprint = public_key_fingerprint(raw)
    keyring = Ed25519AuthorityKeyring({"authority": {fingerprint: raw}})
    adapter = AuthorityBoundEd25519Verifier(keyring)
    checked = ApprovedHostSignedUtcVerifier(
        host_identity="host", authority_keys=keyring.authority_key_fingerprints,
        authority_verifier=adapter, replay_db=sqlite3.connect(":memory:"))
    challenge = checked.issue_challenge(authority_id="authority", synchronization_epoch="epoch",
                                        issued_monotonic_ns=1, ttl_ns=100, challenge="nonce")
    unsigned = AuthorityTimeAssertion("authority", "family", fingerprint, "epoch", challenge.challenge,
                                      1_000.0, .01, b"")
    assertion = AuthorityTimeAssertion("authority", "family", fingerprint, "epoch", challenge.challenge,
                                       1_000.0, .01, private.sign(unsigned.canonical_payload()))
    assert checked.verify(HostReceipt("host", 10, 20, assertion)) is not None
