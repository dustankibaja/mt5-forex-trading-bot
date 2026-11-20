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


def issued(checked, *, nonce="nonce-1", epoch="epoch", authority="authority-a", issued_ns=1, ttl_ns=100):
    return checked.issue_challenge(authority_id=authority, synchronization_epoch=epoch,
                                   issued_monotonic_ns=issued_ns, ttl_ns=ttl_ns,
                                   challenge=nonce)


def test_authority_signs_only_assertion_and_replay_survives_restart(tmp_path):
    path = tmp_path / "replay.sqlite"
    database = sqlite3.connect(path)
    checked = verifier(database)
    issued(checked)
    accepted = checked.verify(receipt())
    assert accepted is not None
    assert accepted.receipt.received_monotonic_ns == 20
    database.commit()
    database.close()
    assert verifier(sqlite3.connect(path)).verify(receipt()) is None


def test_untrusted_signature_host_clock_and_authority_are_rejected():
    database = sqlite3.connect(":memory:")
    checked = verifier(database)
    bad_signature = receipt(assertion=AuthorityTimeAssertion(
        "authority-a", "family-a", "key-a", "epoch", "nonce-x", 1000., .01, b"forged"))
    issued(checked, nonce="nonce-x")
    assert checked.verify(bad_signature) is None
    issued(checked, nonce="nonce-1")
    assert checked.verify(receipt(host_identity="other")) is None
    assert checked.verify(receipt(received_monotonic_ns=10)) is None
    unknown = receipt(assertion=AuthorityTimeAssertion(
        "endpoint-label", "family-a", "key-a", "epoch", "nonce-y", 1000., .01, b"valid"))
    assert checked.verify(unknown) is None


def test_unsolicited_expired_cross_host_and_duplicate_receipts_fail_closed():
    database = sqlite3.connect(":memory:")
    checked = verifier(database)
    assert checked.verify(receipt()) is None
    issued(checked, nonce="expired", issued_ns=1, ttl_ns=5)
    expired = receipt(assertion=AuthorityTimeAssertion(
        "authority-a", "family-a", "key-a", "epoch", "expired", 1000., .01, b"valid"),
        sent_monotonic_ns=6, received_monotonic_ns=7)
    assert checked.verify(expired) is None
    issued(checked, nonce="host-bound")
    cross_host = receipt(host_identity="other", assertion=AuthorityTimeAssertion(
        "authority-a", "family-a", "key-a", "epoch", "host-bound", 1000., .01, b"valid"))
    assert checked.verify(cross_host) is None
    issued(checked, nonce="once")
    one = receipt(assertion=AuthorityTimeAssertion(
        "authority-a", "family-a", "key-a", "epoch", "once", 1000., .01, b"valid"))
    assert checked.verify(one) is not None
    assert checked.verify(one) is None


def test_failed_consumption_transaction_leaves_challenge_unconsumed():
    database = sqlite3.connect(":memory:")
    checked = verifier(database)
    issued(checked, nonce="atomic")
    database.execute("""CREATE TRIGGER fail_consumption BEFORE INSERT ON consumed_utc_challenges
                        BEGIN SELECT RAISE(ABORT, 'simulated crash before commit'); END""")
    value = receipt(assertion=AuthorityTimeAssertion(
        "authority-a", "family-a", "key-a", "epoch", "atomic", 1000., .01, b"valid"))
    assert checked.verify(value) is None
    assert database.execute("SELECT COUNT(*) FROM consumed_utc_challenges").fetchone()[0] == 0
    database.execute("DROP TRIGGER fail_consumption")
    assert checked.verify(value) is not None
