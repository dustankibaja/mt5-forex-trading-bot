# Approved-host transport verifier

This is a design and fixture contract, not an active network client. It must
run only on an administrator-approved Windows host that owns its own MT5 DEMO
session. It must not import sandbox credentials, account profiles, journals or
private test attestations.

## Required implementation

1. The verifier obtains time from at least two independently operated,
   authenticated sources. It validates the source identity (for example a
   pinned authenticated endpoint or a documented, independently verified NTP
   association) and records the verification material locally.
2. For every measurement it records request/receipt monotonic times, network
   delay/dispersion, UTC interval, uncertainty bound, source fingerprint,
   clock-drift bound and an opaque synchronization epoch. A source conflict,
   host clock step, suspend/resume, expiry or excessive uncertainty revokes the
   epoch.
3. A reviewed host-only adapter converts those retained records to the private
   `AuthenticatedReferenceSet` boundary. Generic callers, the Flutter client
   and test fixtures cannot mint production evidence.
4. The adapter binds its measurement to a stable host identity and to the
   verified local DEMO binding. Native MQL5 and Python observations include the
   same host identity, raw provider timestamp, bid/ask and monotonic receipt
   time before quote certification is considered.

## Fixture tests

Fixtures must cover valid two-source calibration, untrusted input, host
mismatch, expired calibration, source disagreement, sleep/resume, host-clock
step, stale/repeated monotonic input and account/epoch changes. Fixtures prove
the fail-closed state machine only; they are not evidence of UTC, broker time
or a DEMO fill.

## Operator boundary

The host administrator separately authorizes Windows Time/DNS/network work and
retains the raw diagnostics. No sandbox firewall rule is changed or bypassed.
Only after actual bounded UTC evidence exists may the host collect fresh MT5
build-6327 native/Python ticks and begin a new UTC-day risk observation.
