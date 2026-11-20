# Signed UTC protocol and audit threat model

## Protocol

`emtifize-signed-utc-v1` requires an approved host to generate a unique random
challenge. An authority returns a detached signature over canonical UTF-8 JSON
with sorted keys and compact separators containing only: protocol version,
authority ID, independent source-family ID, pinned-key fingerprint,
synchronization epoch, challenge, UTC assertion and uncertainty. The host
records send and receipt monotonic timestamps separately; they are never
authority-signed facts.

The host accepts a receipt only after a reviewed cryptographic provider verifies
the signature against the authority-to-pinned-key mapping, the local
request/receipt interval is within policy, the challenge is unused in the
durable replay database, and the assertion has finite bounded uncertainty.
Ordinary NTP, endpoint labels, TLS alone, source labels and private fixture
factories are not authority authentication.

At least two signed, independently operated source families with overlapping
intervals are required. Calibration is derived from those exact verified
receipts; callers cannot pair an unrelated `Calibration` object with them.
Permanent provenance uses `authority:key-fingerprint`; changing transcript
digests are retained separately for audit traceability.

## Audit model

The local SQLite ledger appends an observation and its SHA-256 hash-chain audit
entry atomically. Application-level update/delete triggers, pair-count checks,
one-to-one observation/audit links, contiguous sequence checks and hash-chain
validation detect ordinary corruption, missing rows, orphans and altered rows.
`recorded_utc` and `audit_recorded_utc` are local audit timestamps only; neither
is certified UTC.

This does not protect against an attacker who can rewrite the entire database,
the SQLite binary, trigger definitions and every local checkpoint. The approved
host must periodically retain the latest audit hash in an independently
controlled, append-only location. A future security review must select and
approve the cryptographic provider, key-rotation policy, checkpoint store and
source-independence criteria.
