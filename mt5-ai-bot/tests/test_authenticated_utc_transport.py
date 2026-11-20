import sqlite3

from src.execution.authenticated_utc_transport import (
    ApprovedHostSignedUtcVerifier, AuthorityTimeAssertion, HostReceipt,
)


def receipt(**overrides):
    assertion = AuthorityTimeAssertion("authority-a", "family-a", "key-a", "epoch",
                                       "nonce-1", 1000.0, .01, b"valid")
    values = dict(host_identity="host", sent_monotonic_ns=10, received_monotonic_ns=20,
                  assertion=assertion)
    values.update(overrides)
    return HostReceipt(**values)


def verifier(database):
    return ApprovedHostSignedUtcVerifier(
        host_identity="host", authority_keys={"authority-a": frozenset(("key-a",))},
        replay_db=database,
        verify_detached=lambda fingerprint, payload, signature: fingerprint == "key-a" and signature == b"valid")


def test_authority_signs_only_assertion_and_replay_survives_restart(tmp_path):
    path = tmp_path / "replay.sqlite"
    database = sqlite3.connect(path)
    accepted = verifier(database).verify(receipt())
    assert accepted is not None
    assert accepted.receipt.received_monotonic_ns == 20
    database.commit()
    database.close()
    assert verifier(sqlite3.connect(path)).verify(receipt()) is None


def test_untrusted_signature_host_clock_and_authority_are_rejected():
    database = sqlite3.connect(":memory:")
    bad_signature = receipt(assertion=AuthorityTimeAssertion(
        "authority-a", "family-a", "key-a", "epoch", "nonce-x", 1000., .01, b"forged"))
    assert verifier(database).verify(bad_signature) is None
    assert verifier(database).verify(receipt(host_identity="other")) is None
    assert verifier(database).verify(receipt(received_monotonic_ns=10)) is None
    unknown = receipt(assertion=AuthorityTimeAssertion(
        "endpoint-label", "family-a", "key-a", "epoch", "nonce-y", 1000., .01, b"valid"))
    assert verifier(database).verify(unknown) is None
