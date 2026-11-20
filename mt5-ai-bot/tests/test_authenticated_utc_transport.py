from src.execution.authenticated_utc_transport import (
    ApprovedHostSignedUtcVerifier, SignedUtcTranscript,
)


def transcript(**overrides):
    values = dict(authority_id="authority-a", source_family="family-a", host_identity="host",
                  synchronization_epoch="epoch", nonce="nonce-1", utc_seconds=1000.0,
                  uncertainty_seconds=.01, sent_monotonic_ns=10, received_monotonic_ns=20,
                  signature=b"valid", key_fingerprint="key-a")
    values.update(overrides)
    return SignedUtcTranscript(**values)


def verifier():
    return ApprovedHostSignedUtcVerifier(
        host_identity="host", pinned_keys=frozenset(("key-a",)),
        approved_authorities=frozenset(("authority-a",)),
        verify_detached=lambda fingerprint, payload, signature: fingerprint == "key-a" and signature == b"valid")


def test_signed_transcript_requires_pinned_key_and_nonce_replay_protection():
    checked = verifier()
    accepted = checked.verify(transcript())
    assert accepted is not None and len(accepted.transcript_digest) == 64
    assert checked.verify(transcript()) is None


def test_untrusted_signature_host_clock_and_authority_are_rejected():
    assert verifier().verify(transcript(signature=b"forged")) is None
    assert verifier().verify(transcript(host_identity="other")) is None
    assert verifier().verify(transcript(received_monotonic_ns=10)) is None
    assert verifier().verify(transcript(authority_id="endpoint-label")) is None
